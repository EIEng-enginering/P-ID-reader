"""One-call, resumable analysis pipeline for a stored drawing (standalone product).

Runs the existing evidence layers in dependency order and stores each one in the
project database:

    geometry -> symbols -> linework -> symbol catalogue -> signals
             -> OCR (offline) -> text/tag links

Every layer is a *proposal*; nothing is reviewed, accepted, or treated as a
plant fact. Stages are idempotent: stores use content-derived ids, so re-running
on an unchanged drawing returns the same analysis ids. A failed or unavailable
stage is recorded and the remaining independent stages still run.
"""
from __future__ import annotations

from typing import Callable

from ..api import CancelToken, Cancelled, canonical_json

STAGES = ("geometry", "raster", "symbols", "linework", "catalogue", "signals", "ocr", "text_links", "raster_network", "raster_centrelines")


def _noop(_stage: str, _fraction: float, _message: str) -> None:
    return None


PIPELINE_VERSION = "pipeline-rev-x-1"


def analyze_drawing(db, extraction_id: str, *, ocr_engine: str | None = "auto",
                    catalogue_id: str | None = None, use_example_catalogue: bool = True,
                    progress: Callable[[str, float, str], None] = _noop,
                    cancel: CancelToken | None = None, preset: str = "standard", record: bool = True) -> dict:
    """Run every available layer for ``extraction_id``.

    ``ocr_engine``: ``None`` skips OCR; ``'auto'`` uses Tesseract if installed,
    else RapidOCR if installed, else records OCR as ``SKIPPED``.
    Returns ``{"extraction_id", "analyses": {stage: id}, "counts": {...},
    "stages": {stage: {"status", "detail"}}, "outcomes": [StageOutcome...], "health": {...}, "run_id"}``.
    ``stages`` keeps the legacy DONE/SKIPPED/FAILED/NOT_RUN vocabulary; ``outcomes`` and ``health`` (Rev X) separate
    "did not run", "failed" and "ran and found nothing", and ``health['drawing_status']`` is never a success claim for
    an empty result. With ``record=True`` the run is stored in the additive v13 tables.
    """
    from .stage_telemetry import StageRecorder, ocr_diagnostics, evaluate_health
    from .page_regions import analyse_pages
    from .topology import analyze_pdf_topology
    from .symbols import build_symbol_proposals
    from .linework import build_linework_proposals
    from .signal_links import build_signal_links
    from .text_links import build_text_links

    stages: dict[str, dict] = {s: {"status": "NOT_RUN", "detail": ""} for s in STAGES}
    ids: dict[str, str] = {}
    counts: dict[str, int] = {}
    total = len(STAGES)

    def check() -> None:
        if cancel is not None:
            cancel.check()

    def mark(stage: str, status: str, detail: str = "", **fields) -> None:
        stages[stage] = {"status": status, "detail": detail}
        recorder.end(stage, status, detail, **fields)

    def step(stage: str, message: str) -> None:
        recorder.begin(stage)
        progress(stage, STAGES.index(stage) / total, message)

    extraction = db.export_extraction(extraction_id)
    source = db.get_source_pdf(extraction["document"]["sha256"])
    if source is None:
        raise ValueError("Source PDF bytes are not embedded in this project; analysis cannot be reproduced")
    pages = tuple(x["page"] for x in extraction["pages"] if x.get("read_status") == "READ")
    if not pages:
        pages = tuple(x["page"] for x in extraction["pages"])
    source_sha = extraction["document"]["sha256"]
    recorder = StageRecorder(source_sha, {"pipeline": PIPELINE_VERSION, "ocr_engine": ocr_engine, "preset": preset,
                                          "catalogue_id": catalogue_id, "pages": list(pages)})

    page_analysis: list[dict] = []
    recorder.begin("classify")
    try:
        check()
        page_analysis = analyse_pages(source, pages, source_sha256=source_sha)
        recorder.end("classify", "DONE", f"{len(page_analysis)} page(s) classified",
                     pages_processed=len(page_analysis), regions_processed=sum(len(p["regions"]) for p in page_analysis),
                     candidates=sum(len(p["regions"]) for p in page_analysis))
    except Cancelled:
        raise
    except Exception as exc:
        recorder.end("classify", "FAILED", f"{type(exc).__name__}: {exc}")

    topology = None
    try:
        check(); step("geometry", "Tracing vector geometry")
        topology = analyze_pdf_topology(source, pages=pages)
        ids["geometry"] = db.add_geometry_analysis(extraction_id, topology)
        counts["segments"] = len(topology["segments"])
        counts["contacts"] = len(topology["contact_candidates"])
        mark("geometry", "DONE", f"{counts['segments']} strokes, {counts['contacts']} contacts")
    except Cancelled:
        raise
    except Exception as exc:  # recorded, later stages that depend on it are skipped
        mark("geometry", "FAILED", f"{type(exc).__name__}: {exc}")

    # Rev S: raster evidence for pages with no native straight vector strokes.
    # This is independent of native topology and never changes its conclusions.
    try:
        check(); step("raster", "Observing scanned linework and geometric valve glyphs")
        from .raster_geometry import raster_available, analyze_raster_geometry
        if not raster_available():
            mark("raster", "SKIPPED", "Install optional local raster dependencies (opencv/numpy/pdfium)")
        else:
            vector_pages = {row["page"] for row in (topology or {}).get("segments", [])}
            scan_pages = tuple(n for n in pages if n not in vector_pages)
            if not scan_pages:
                mark("raster", "SKIPPED", "native straight strokes available on selected pages; raster is opt-in via CLI")
            else:
                result = analyze_raster_geometry(source, pages=scan_pages, cancel=cancel)
                ids["raster"] = db.add_raster_analysis(extraction_id, result)
                counts["raster_strokes"] = len(result["stroke_candidates"])
                counts["raster_filled_valves"] = len(result["filled_valve_candidates"])
                counts["raster_outlined_valves"] = len(result.get("outline_valve_candidates", []))
                mark("raster", "DONE", f"{counts['raster_strokes']} raster strokes, {counts['raster_filled_valves']} filled and {counts['raster_outlined_valves']} outlined glyph proposals")
    except Cancelled:
        raise
    except Exception as exc:
        mark("raster", "FAILED", f"{type(exc).__name__}: {exc}")

    symbols = None
    if "geometry" in ids:
        try:
            check(); step("symbols", "Finding outline symbols")
            symbols = build_symbol_proposals(extraction, db.get_geometry_analysis(ids["geometry"]))
            ids["symbols"] = db.add_symbol_analysis(extraction_id, ids["geometry"], symbols)
            counts["symbols"] = len(symbols["symbol_candidates"])
            mark("symbols", "DONE", f"{counts['symbols']} outline candidates, {len(symbols['port_candidates'])} port hypotheses")
        except Cancelled:
            raise
        except Exception as exc:
            mark("symbols", "FAILED", f"{type(exc).__name__}: {exc}")
    else:
        mark("symbols", "SKIPPED", "needs geometry")

    if "symbols" in ids:
        try:
            check(); step("linework", "Classifying valves and line styles")
            lw = build_linework_proposals(extraction, db.get_geometry_analysis(ids["geometry"]),
                                          db.get_symbol_analysis(ids["symbols"]))
            ids["linework"] = db.add_linework_analysis(extraction_id, ids["geometry"], ids["symbols"], lw)
            counts["valves"] = len(lw["valve_candidates"])
            mark("linework", "DONE", f"{counts['valves']} valve candidates")
        except Cancelled:
            raise
        except Exception as exc:
            mark("linework", "FAILED", f"{type(exc).__name__}: {exc}")
    else:
        mark("linework", "SKIPPED", "needs symbols")

    if "linework" in ids:
        try:
            check(); step("catalogue", "Matching symbol templates")
            cid = catalogue_id
            if cid is None and use_example_catalogue:
                from .symbol_catalog import example_catalog
                cid = db.register_symbol_catalogue(example_catalog())
            if cid is None:
                mark("catalogue", "SKIPPED", "no symbol catalogue selected")
            else:
                aid, result = db.analyze_symbol_catalogue(extraction_id, ids["geometry"], ids["symbols"],
                                                          ids["linework"], cid)
                ids["catalogue"] = aid
                counts["catalogue_matches"] = len(result["candidates"])
                mark("catalogue", "DONE", f"{counts['catalogue_matches']} template matches (catalogue {cid[-8:]})")
        except Cancelled:
            raise
        except Exception as exc:
            mark("catalogue", "FAILED", f"{type(exc).__name__}: {exc}")

        try:
            check(); step("signals", "Looking for signal-line endpoints")
            sig = build_signal_links(extraction, db.get_geometry_analysis(ids["geometry"]),
                                     db.get_symbol_analysis(ids["symbols"]),
                                     db.get_linework_analysis(ids["linework"]))
            ids["signals"] = db.add_signal_analysis(extraction_id, ids["geometry"], ids["symbols"],
                                                    ids["linework"], sig)
            counts["signal_candidates"] = len(sig["candidates"])
            mark("signals", "DONE", f"{counts['signal_candidates']} signal-style candidates")
        except Cancelled:
            raise
        except Exception as exc:
            mark("signals", "FAILED", f"{type(exc).__name__}: {exc}")
    else:
        mark("catalogue", "SKIPPED", "needs linework")
        mark("signals", "SKIPPED", "needs linework")

    ocr = None
    ocr_exception = ""
    ocr_counters: dict = {}
    ocr_trace: list[dict] = []
    from ..formats.ocr_source import available_engines, last_diagnostics
    engines_now = available_engines()
    if ocr_engine is None:
        mark("ocr", "SKIPPED", "OCR disabled")
    else:
        try:
            check(); step("ocr", "Reading text with offline OCR")
            from ..formats.ocr_source import ocr_pdf_preview
            if ocr_engine == "auto" and not engines_now:
                mark("ocr", "SKIPPED", "no offline OCR engine installed (Tesseract or RapidOCR)")
            else:
                ocr = ocr_pdf_preview(source, pages=pages, engine=ocr_engine)
                ocr_counters = last_diagnostics()
                from .ocr_adaptive import augment_ocr
                ocr, ocr_trace = augment_ocr(source, ocr, page_analysis, preset=preset, cancel=cancel)
                ids["ocr"] = db.add_ocr_analysis(extraction_id, ocr)
                counts["ocr_words"] = sum(len(p["words"]) for p in ocr["pages"])
                mark("ocr", "DONE", f"{counts['ocr_words']} words ({ocr['algorithm']})",
                     tile_count=ocr_counters.get("tiles_attempted", 0), candidates=counts["ocr_words"],
                     pages_processed=len(ocr["pages"]), evidence_count=counts["ocr_words"],
                     output_sha256=ocr["result_sha256"], diagnostics={"adaptive_trace": ocr_trace})
        except Cancelled:
            raise
        except Exception as exc:
            ocr_exception = f"{type(exc).__name__}: {exc}"
            ocr_counters = last_diagnostics()
            if str(exc).startswith("OCR_RUNTIME_EXCEPTION"):
                ocr_exception = str(exc)
            mark("ocr", "FAILED", f"{type(exc).__name__}: {exc}")

    if "symbols" in ids and "ocr" in ids:
        try:
            check(); step("text_links", "Associating tag text with symbols")
            links = build_text_links(extraction, db.get_symbol_analysis(ids["symbols"]),
                                     db.get_ocr_analysis(ids["ocr"]))
            ids["text_links"] = db.add_text_link_analysis(extraction_id, ids["symbols"], ids["ocr"], links)
            counts["text_links"] = len(links["proposals"])
            mark("text_links", "DONE", f"{counts['text_links']} symbol/tag proposals")
        except Cancelled:
            raise
        except Exception as exc:
            mark("text_links", "FAILED", f"{type(exc).__name__}: {exc}")
    else:
        mark("text_links", "SKIPPED", "needs symbols and OCR")

    if 'raster' in ids:
        try:
            check();step('raster_network','Classifying raster stroke context and unresolved contacts')
            from .raster_network import build_raster_network
            raster_result=db.get_raster_analysis(ids['raster'])
            context=build_raster_network(raster_result,ocr)
            ids['raster_network']=db.add_raster_network_analysis(
                extraction_id,ids['raster'],context,ocr_analysis_id=ids.get('ocr'))
            counts['raster_contacts']=len(context['contact_candidates'])
            mark('raster_network','DONE',f"{counts['raster_contacts']} unresolved contact proposals")
        except Cancelled:
            raise
        except Exception as exc:
            mark('raster_network','FAILED',f'{type(exc).__name__}: {exc}')
    else:
        mark('raster_network','SKIPPED','requires raster evidence')

    if 'raster_network' in ids and 'raster' in ids:
        try:
            check();step('raster_centrelines','Consolidating duplicate-supported raster centrelines')
            from .raster_centrelines import build_raster_centrelines
            raster_result=db.get_raster_analysis(ids['raster'])
            network=db.get_raster_network_analysis(ids['raster_network'])
            lines=build_raster_centrelines(raster_result,network)
            ids['raster_centrelines']=db.add_raster_centreline_analysis(
                extraction_id,ids['raster'],ids['raster_network'],lines)
            counts['raster_centrelines']=len(lines['centrelines'])
            counts['raster_gaps']=len(lines['gap_candidates'])
            mark('raster_centrelines','DONE',f"{counts['raster_centrelines']} centrelines, {counts['raster_gaps']} unresolved gaps")
        except Cancelled:
            raise
        except Exception as exc:
            mark('raster_centrelines','FAILED',f'{type(exc).__name__}: {exc}')
    else:
        mark('raster_centrelines','SKIPPED','requires raster network evidence')

    progress("done", 1.0, "Analysis finished")

    # ---- Rev X health: separate "did not run", "failed" and "ran and found nothing"
    ink_pages: set[int] = set()
    if topology:
        ink_pages |= {row["page"] for row in topology.get("segments", [])}
    if "raster" in ids:
        ink_pages |= {row["page"] for row in db.get_raster_analysis(ids["raster"]).get("stroke_candidates", [])}
    ocr_words_by_page = {p["page"]: p["words"] for p in (ocr or {}).get("pages", [])}
    native_words = {p["page"]: p["counts"]["word_count"] for p in page_analysis}
    ocr_diag = ocr_diagnostics(
        requested=ocr_engine is not None, engine_choice=ocr_engine or "off", engines_available=engines_now,
        stage_status=recorder.outcomes.get("ocr", {}).get("status", "NOT_RUN"),
        pages_selected=[] if ocr_engine is None else list(pages), counters=ocr_counters, native_words=native_words,
        ocr_words={n: len(w) for n, w in ocr_words_by_page.items()},
        recognized_tags=sum(1 for o in extraction["objects"] if o.get("attributes", {}).get("source") == "OCR"),
        exception=ocr_exception, retry_count=len(ocr_trace))
    if recorder.outcomes.get("ocr"):
        recorder.outcomes["ocr"]["diagnostics"]["ocr"] = ocr_diag
    health = evaluate_health(
        page_analysis=page_analysis, outcomes=recorder.outcomes, ocr_diag=ocr_diag, ink_pages=ink_pages,
        ocr_words_by_page=ocr_words_by_page,
        symbol_stage_status=recorder.outcomes.get("symbols", {}).get("status", "NOT_RUN"),
        graph_nodes=counts.get("symbols", 0))
    run_id = None
    if record:
        try:
            from .intelligence_store import record_run
            regions = [r for p in page_analysis for r in p["regions"]]
            run_id = record_run(db, extraction_id, preset=preset, status=health["drawing_status"],
                                outcomes=recorder.ordered(), regions=regions,
                                summary={"health": health, "counts": counts, "pages": [
                                    {k: p[k] for k in ("page", "classification", "reason", "ocr_policy", "counts", "frame")}
                                    for p in page_analysis]},
                                config=recorder.config)
        except Exception as exc:  # recording must never hide the analysis result
            health["record_error"] = f"{type(exc).__name__}: {exc}"
    return {"extraction_id": extraction_id, "analyses": ids, "counts": counts, "stages": stages,
            "outcomes": recorder.ordered(), "health": health, "page_analysis": page_analysis, "run_id": run_id,
            "notice": "All results are unreviewed proposals read from the drawing; none verifies the plant."}


def summary_json(result: dict) -> str:
    return canonical_json(result)
