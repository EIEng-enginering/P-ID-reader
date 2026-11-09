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
MAX_JUNCTION_ITEMS_PER_PAGE = 1500
# Relative cost of every stage (including the Rev X ones). The progress bar follows this plan, so it can only reach 100 % after the last
# stage has finished and the run has been recorded.
PROGRESS_WEIGHTS = {"classify": 2, "geometry": 6, "raster": 4, "symbols": 2, "linework": 2, "catalogue": 2, "signals": 2, "ocr": 22, "text_links": 2,
                    "raster_network": 3, "raster_centrelines": 3, "symbol_library": 26, "engineering_graph": 14, "control_loops": 2, "doc_text": 4, "record": 5}
_W_TOTAL = float(sum(PROGRESS_WEIGHTS.values()))
_W_START, _acc = {}, 0.0
for _k, _w in PROGRESS_WEIGHTS.items():
    _W_START[_k] = _acc / _W_TOTAL
    _acc += _w
del _k, _w, _acc


def analyze_drawing(db, extraction_id: str, *, ocr_engine: str | None = "auto",
                    catalogue_id: str | None = None, use_example_catalogue: bool = True,
                    progress: Callable[[str, float, str], None] = _noop,
                    cancel: CancelToken | None = None, preset: str = "standard", record: bool = True,
                    library_symbols: bool = False) -> dict:
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
        progress(stage, _W_START[stage], message)

    def sub(stage: str, fraction: float, message: str) -> None:
        """Progress inside a stage: ``fraction`` 0..1 of that stage's share of the bar. Never reports 100 % before the end."""
        span = PROGRESS_WEIGHTS[stage] / _W_TOTAL
        progress(stage, min(0.995, _W_START[stage] + span * max(0.0, min(1.0, fraction))), message)

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
    profiles: dict = {}
    recorder.begin("classify")
    progress("classify", 0.0, "Classifying pages and finding title block, tables and notes")
    try:
        check()
        page_analysis = analyse_pages(source, pages, source_sha256=source_sha, profiles_out=profiles)
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
                ocr = ocr_pdf_preview(source, pages=pages, engine=ocr_engine, cancel=cancel,
                                      progress=lambda f, m: sub("ocr", 0.9 * f, m))
                ocr_counters = last_diagnostics()
                from .ocr_adaptive import augment_ocr
                sub("ocr", 0.9, "Re-reading pages that gave no text (other orientations and contrast)")
                ocr, ocr_trace = augment_ocr(source, ocr, page_analysis, preset=preset, cancel=cancel)
                sub("ocr", 1.0, "OCR finished")
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
            from ..formats import ocr_source as _ocr_mod
            _ocr_mod._HOOK.clear()
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
    items: list[dict] = []
    recorder.begin("symbol_library")
    if library_symbols:
        progress("symbol_library", _W_START["symbol_library"], "Searching for valves, actuators, instruments and equipment")
    if not library_symbols:
        recorder.end("symbol_library", "SKIPPED", "library symbol detection not requested")
    else:
        try:
            check()
            from .symbol_detect import detect_symbols
            sym_items, sym_stats = [], {"pages": 0, "candidates": 0, "partial_pages": 0, "tiles": 0, "weak_class_withheld": 0}
            sym_by_page: dict[int, list[dict]] = {}
            todo = [pg for pg in page_analysis if pg["counts"]["graphics_count"] or pg["counts"]["image_count"]]   # no ink at all: nothing to search
            for pi, pg in enumerate(todo):
                check()
                found = detect_symbols(source, pg["page"], preset=preset if preset in ("quick", "standard", "deep") else "standard", cancel=cancel,
                                       progress=lambda f, m, pi=pi, n=len(todo), pn=pg["page"]: sub("symbol_library", (pi + f) / n, f"Page {pn}: {m}"))
                sym_stats["pages"] += 1
                sym_stats["candidates"] += len(found["candidates"])
                sym_stats["tiles"] += found["tiles_processed"]
                sym_stats["partial_pages"] += found["status"] == "PARTIAL"
                sym_by_page[pg["page"]] = found["candidates"]
                for c in found["candidates"]:
                    sym_stats["weak_class_withheld"] += c["confidence_status"] == "WEAK_CLASS_WITHHELD"
                    sym_items.append({"item_id": c["id"], "item_kind": "OCCURRENCE", "tag_normalized": None, "page": c["page"],
                                      "producer": "symbol-detect-v1", "review_state": "PROPOSED_UNVERIFIED", "truth_class": "STRUCTURALLY_DERIVED",
                                      "occurrence": {k: c[k] for k in ("template_id", "graphical_family", "shape_variant", "engineering_class",
                                                                       "class_candidates", "actuation", "function", "raw_score", "score_kind", "precision",
                                                                       "confidence_status", "rotation", "size_pt", "alternatives")},
                                      "bbox": c["bbox"], "ports": c["ports"],
                                      "evidence": [{"page": c["page"], "bbox": c["bbox"], "source_sha256": source_sha, **c["evidence"]}]})
            items += sym_items
            counts["library_symbols"] = sym_stats["candidates"]
            recorder.end("symbol_library", "DONE", f"{sym_stats['candidates']} symbol candidates on {sym_stats['pages']} page(s)",
                         candidates=sym_stats["candidates"], pages_processed=sym_stats["pages"], tile_count=sym_stats["tiles"],
                         cap_truncations=sym_stats["partial_pages"], diagnostics={"stats": sym_stats})
        except Cancelled:
            raise
        except Exception as exc:
            recorder.end("symbol_library", "FAILED", f"{type(exc).__name__}: {exc}")
    graphs: list[dict] = []
    recorder.begin("engineering_graph")
    if not (library_symbols and recorder.outcomes.get("symbol_library", {}).get("status") in ("SUCCESS", "PARTIAL")):
        recorder.end("engineering_graph", "SKIPPED", "needs library symbol detection")
    else:
        try:
            from .vector_network import analyze_vector_network
            from .engineering_graph import build_graph
            g_stats = {"pages": 0, "edges": 0, "conflicts": 0, "junctions": 0, "partial_pages": 0, "unattached_ports": 0, "arrows": 0}
            graph_items: list[dict] = []
            gpages = [pg for pg in page_analysis if pg["page"] in sym_by_page]
            for gi, pg in enumerate(gpages):
                check()
                sub("engineering_graph", gi / max(1, len(gpages)), f"Page {pg['page']}: tracing drawn lines and junctions")
                vec = analyze_vector_network(source, pg["page"], cancel=cancel,
                                             progress=lambda f, m, gi=gi, n=len(gpages), pn=pg["page"]: sub("engineering_graph", (gi + f) / n, f"Page {pn}: {m}"))
                words = [{"id": f"nat-{pg['page']}-{i}", "text": w["text"], "bbox": w["bbox"], "source": "NATIVE"}
                         for i, w in enumerate((profiles.get(pg["page"]) or {}).get("words", []))]
                words += [{"id": w["id"], "text": w["text"], "bbox": w["bbox"], "source": "OCR"} for w in ocr_words_by_page.get(pg["page"], [])]
                graph = build_graph(page=pg["page"], page_size_pt=tuple(vec["page_size_pt"]), occurrences=[c for c in sym_by_page[pg["page"]] if c["confidence_status"] != "WEAK_CLASS_WITHHELD"], vector=vec,
                                    words=words, source_sha256=source_sha)
                graphs.append(graph)
                g_stats["pages"] += 1
                g_stats["edges"] += len(graph["edges"])
                g_stats["conflicts"] += len(graph["conflicts"])
                g_stats["junctions"] += vec["counts"]["junctions"]
                g_stats["arrows"] += vec["counts"]["arrows"]
                g_stats["partial_pages"] += vec["status"] == "PARTIAL"
                g_stats["unattached_ports"] += graph["quality"]["unattached_ports"]
                for n in graph["nodes"]:
                    if n["node_kind"] == "PORT":
                        graph_items.append({"item_id": n["node_id"], "item_kind": "PORT", "tag_normalized": None, "page": n["page"], "port": n,
                                            "evidence": [{"page": n["page"], "x": n["x"], "y": n["y"], "source_sha256": source_sha}],
                                            "review_state": "PROPOSED_UNVERIFIED", "producer": "engineering-graph-v2"})
                    elif n["tag"]:
                        graph_items.append({"item_id": "tag-" + n["node_id"], "item_kind": "ATTRIBUTE", "tag_normalized": n["tag"]["text"].upper(),
                                            "page": n["page"], "truth_class": "CONTEXTUAL_INFERENCE", "review_state": "PROPOSED_UNVERIFIED",
                                            "attribute": {"field_name": "TAG_ASSOCIATION", "verbatim": n["tag"]["text"], "occurrence_id": n["node_id"],
                                                          "status": n["tag"]["assignment"], "alternatives": n["tag"]["alternatives"]},
                                            "evidence": [{"page": n["page"], "bbox": n["tag"]["bbox"], "word_ids": [n["tag"]["word_id"]]},
                                                         {"page": n["page"], "bbox": n["bbox"], "occurrence_id": n["node_id"]}]})
                for e in graph["edges"]:
                    graph_items.append({"item_id": e["edge_id"], "item_kind": "RELATION", "tag_normalized": None, "page": e["page"], "relation": e,
                                        "truth_class": "STRUCTURALLY_DERIVED", "review_state": "PROPOSED_UNVERIFIED", "producer": "engineering-graph-v2",
                                        "evidence": [{"page": e["page"], **e["evidence"]}]})
                for cf in graph["conflicts"]:
                    graph_items.append({"item_id": cf["conflict_id"], "item_kind": "CONFLICT", "tag_normalized": None, "page": pg["page"], "conflict": cf,
                                        "truth_class": "CONFLICTING", "review_state": "NEEDS_REVIEW", "evidence": [{"page": pg["page"], **cf}]})
                for a in graph["asset_hypotheses"]:
                    graph_items.append({"item_id": a["asset_id"], "item_kind": "ASSET_HYPOTHESIS", "tag_normalized": (a["tag_text"] or "").upper() or None,
                                        "page": pg["page"], "asset": a, "truth_class": "CONTEXTUAL_INFERENCE", "review_state": "PROPOSED_UNVERIFIED",
                                        "evidence": [{"page": pg["page"], "occurrences": a["occurrences"]}]})
                # Only junctions that carry a question or a supporting mark are stored as evidence items. Plain joined contacts (every symbol
                # outline touches the pipe) are counted in the stage statistics instead: a dense sheet has tens of thousands of them.
                kept_j = [j for j in vec["junctions"] if j["status"] in ("UNKNOWN_CROSSING", "SEPARATED_FAVOURED", "JOINED_SUPPORTED", "SEPARATED_SUPPORTED")]
                if len(kept_j) > MAX_JUNCTION_ITEMS_PER_PAGE:
                    g_stats["junction_items_capped"] = g_stats.get("junction_items_capped", 0) + len(kept_j) - MAX_JUNCTION_ITEMS_PER_PAGE
                    kept_j = kept_j[:MAX_JUNCTION_ITEMS_PER_PAGE]
                for j in kept_j:
                    if True:
                        graph_items.append({"item_id": j["id"], "item_kind": "EVIDENCE", "tag_normalized": None, "page": pg["page"], "junction": j,
                                            "truth_class": "DIRECT_OBSERVATION", "review_state": "PROPOSED_UNVERIFIED",
                                            "evidence": [{"page": pg["page"], "point_norm": j["point_norm"]}]})
            items += graph_items
            counts["graph_edges"] = g_stats["edges"]
            recorder.end("engineering_graph", "DONE", f"{g_stats['edges']} drawn-connection proposals, {g_stats['conflicts']} conflicts on {g_stats['pages']} page(s)",
                         candidates=g_stats["edges"], pages_processed=g_stats["pages"],
                         cap_truncations=g_stats["partial_pages"] + (1 if g_stats.get("junction_items_capped") else 0),
                         diagnostics={"stats": g_stats})
        except Cancelled:
            raise
        except Exception as exc:
            recorder.end("engineering_graph", "FAILED", f"{type(exc).__name__}: {exc}")
    loops_result: dict = {}
    recorder.begin("control_loops")
    progress("control_loops", _W_START["control_loops"], "Assembling instrument loops")
    if not graphs:
        recorder.end("control_loops", "SKIPPED", "needs the typed graph")
    else:
        try:
            check()
            from .control_loops import build_loops
            loop_words = {}
            for pg in page_analysis:
                loop_words[pg["page"]] = [{"id": f"nat-{pg['page']}-{i}", "text": w["text"], "bbox": w["bbox"]}
                                          for i, w in enumerate((profiles.get(pg["page"]) or {}).get("words", []))] + \
                                         [{"id": w["id"], "text": w["text"], "bbox": w["bbox"]} for w in ocr_words_by_page.get(pg["page"], [])]
            loops_result = build_loops(graphs, loop_words)
            loop_items = []
            for lp in loops_result["loops"]:
                loop_items.append({"item_id": lp["loop_id"], "item_kind": "LOOP", "tag_normalized": lp["loop_number"], "page": lp["page"], "loop": lp,
                                   "truth_class": lp["truth_class"], "review_state": lp["review_state"], "evidence": lp["evidence"]})
            for rel in loops_result["relations"]:
                loop_items.append({"item_id": rel["relation_id"], "item_kind": "RELATION", "tag_normalized": None, "page": rel["page"], "relation": rel,
                                   "truth_class": rel["truth_class"], "review_state": rel["review_state"], "evidence": rel["evidence"]})
            for pm in loops_result["protective_device_mentions"] + loops_result["text_mentions"]:
                loop_items.append({"item_id": pm["item_id"], "item_kind": "ATTRIBUTE", "tag_normalized": (pm.get("tag") or "").upper() or None, "page": pm["page"],
                                   "attribute": {"field_name": pm.get("kind", "PROTECTIVE_DEVICE_MENTION"), **{k: v for k, v in pm.items() if k not in ("evidence",)}},
                                   "truth_class": "CONTEXTUAL_INFERENCE", "review_state": pm["review_state"], "evidence": pm["evidence"]})
            items += loop_items
            counts["loops"] = len(loops_result["loops"])
            recorder.end("control_loops", "DONE", f"{len(loops_result['loops'])} loop record(s), {len(loops_result['relations'])} control relation(s)",
                         candidates=len(loop_items), diagnostics={"linked": sum(1 for x in loops_result["loops"] if x["status"] == "LINKED_BY_DRAWN_SIGNAL")})
        except Cancelled:
            raise
        except Exception as exc:
            recorder.end("control_loops", "FAILED", f"{type(exc).__name__}: {exc}")
    recorder.begin("doc_text")
    progress("doc_text", _W_START["doc_text"], "Reading tables, notes and title block")
    try:
        check()
        from .doc_text import extract_document_text
        text_items, text_stats = extract_document_text(page_analysis, profiles, ocr_words_by_page, source_sha)
        items += text_items
        counts["doc_text_items"] = len(text_items)
        recorder.end("doc_text", "DONE", f"{text_stats['tables']} tables, {text_stats['table_values']} values, {text_stats['notes']} notes",
                     candidates=len(items), pages_processed=text_stats["pages"], cap_truncations=text_stats["capped_pages"],
                     diagnostics={"stats": text_stats})
    except Cancelled:
        raise
    except Exception as exc:
        recorder.end("doc_text", "FAILED", f"{type(exc).__name__}: {exc}")
    run_id = None
    r5: dict = {}
    from . import r5_features
    if r5_features.mode("PAGE_FRAME") != r5_features.OFF:
        try:                                    # provenance only: reads page metadata, never rescales or re-reads any geometry
            from ..formats.page_provenance import read_pdf_provenance
            r5["page_provenance"] = read_pdf_provenance(source)
        except Exception as exc:                # a metadata failure must never hide the analysis
            r5["page_provenance"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "pages": []}
    progress("record", _W_START["record"], "Saving the analysis run")
    if record:
        try:
            from .intelligence_store import record_run
            regions = [r for p in page_analysis for r in p["regions"]]
            run_id = record_run(db, extraction_id, preset=preset, status=health["drawing_status"],
                                outcomes=recorder.ordered(), regions=regions, items=items,
                                summary={"health": health, "counts": counts, "pages": [
                                    {k: p[k] for k in ("page", "classification", "reason", "ocr_policy", "counts", "frame")}
                                    for p in page_analysis],
                                    # R5: stored with the run only when PID_R5_PAGE_FRAME=on; SHADOW returns it in the result, never in the record
                                    **({"page_provenance": r5["page_provenance"]} if r5 and r5_features.mode("PAGE_FRAME") == r5_features.ON else {})},
                                config=recorder.config)
        except Exception as exc:  # recording must never hide the analysis result
            health["record_error"] = f"{type(exc).__name__}: {exc}"
    progress("done", 1.0, "Analysis finished")
    return {"extraction_id": extraction_id, "analyses": ids, "counts": counts, "stages": stages,
            "outcomes": recorder.ordered(), "health": health, "page_analysis": page_analysis, "run_id": run_id,
            "items": items, "graphs": graphs, "loops": loops_result,
            **({"r5_shadow": r5} if r5 and r5_features.mode("PAGE_FRAME") == r5_features.SHADOW else {}),
            "notice": "All results are unreviewed proposals read from the drawing; none verifies the plant."}


def summary_json(result: dict) -> str:
    return canonical_json(result)
