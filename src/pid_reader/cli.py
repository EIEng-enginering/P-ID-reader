"""Offline standalone command-line interface; no use of Worksheet private databases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from .api import ReadParams, RefusedInput, LimitExceeded, read_pid, canonical_json
from .engineering.project import ProjectStore


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):      # OCR text can hold characters the Windows console codepage cannot encode
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p=argparse.ArgumentParser(prog="pid-reader",description="Evidence-first P&ID reader development CLI")
    sub=p.add_subparsers(dest="cmd",required=True)
    create=sub.add_parser("init-project");create.add_argument("database")
    imp=sub.add_parser("import-pdf");imp.add_argument("database");imp.add_argument("pdf");imp.add_argument("--output-json");imp.add_argument("--revision-id",default="")
    imp.add_argument("--ocr",choices=("auto","tesseract","rapidocr","off"),default="auto",help="OCR for image-only pages (offline); off = refuse them as the frozen R1 reader does")
    lst=sub.add_parser("list");lst.add_argument("database");lst.add_argument("--text",default="");lst.add_argument("--limit",type=int,default=100)
    show=sub.add_parser("show");show.add_argument("database");show.add_argument("observation_id")
    graph=sub.add_parser("connections");graph.add_argument("database");graph.add_argument("observation_id")
    rev=sub.add_parser("review");rev.add_argument("database");rev.add_argument("observation_id");rev.add_argument("--actor",required=True)
    rev.add_argument("--decision",required=True,choices=["ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","IGNORED_REGION"])
    rev.add_argument("--reason",default="");rev.add_argument("--edited-json")
    exp=sub.add_parser("export");exp.add_argument("database");exp.add_argument("extraction_id");exp.add_argument("destination")
    dxf=sub.add_parser("inspect-dxf"); dxf.add_argument("dxf"); dxf.add_argument("--output-json")
    ocr=sub.add_parser("ocr-preview"); ocr.add_argument("pdf"); ocr.add_argument("--output-json")
    ocr.add_argument("--engine",choices=("auto","tesseract","rapidocr"),default="auto",help="Offline OCR engine (auto: Tesseract if installed else RapidOCR)")
    # Rev S: offline raster geometry is standalone; native/R1 evidence remains separate.
    rp=sub.add_parser("raster-preview",help="Observe raster lines, filled and outlined bowtie glyphs without a database")
    rp.add_argument("pdf");rp.add_argument("--pages",nargs="*",type=int)
    rp.add_argument("--dpi",type=int,default=144);rp.add_argument("--output-json")
    ra=sub.add_parser("analyze-raster");ra.add_argument("database");ra.add_argument("extraction_id")
    ra.add_argument("--dpi",type=int,default=144);ra.add_argument("--pages",nargs="*",type=int);ra.add_argument("--output-json")
    rl=sub.add_parser("raster-valves");rl.add_argument("database");rl.add_argument("analysis_id")
    rl.add_argument("--limit",type=int,default=200)
    rr=sub.add_parser("review-raster-valve");rr.add_argument("database");rr.add_argument("candidate_id")
    rr.add_argument("--actor",required=True);rr.add_argument("--reason",required=True)
    rr.add_argument("--decision",required=True,choices=["ACCEPTED_AS_READING","REJECTED","UNRESOLVED"])
    rn=sub.add_parser('analyze-raster-network',help='Build review-only raster contacts, optionally with source-matched OCR')
    rn.add_argument('database');rn.add_argument('extraction_id');rn.add_argument('raster_analysis_id')
    rn.add_argument('--ocr-analysis-id',default=None);rn.add_argument('--output-json')
    cna=sub.add_parser('analyze-raster-centrelines',help='Derive source-bound raster centrelines and unresolved gaps')
    cna.add_argument('database');cna.add_argument('extraction_id')
    cna.add_argument('raster_analysis_id');cna.add_argument('raster_network_analysis_id')
    cna.add_argument('--output-json')
    cng=sub.add_parser('raster-gaps',help='List proposed short collinear gaps (not pipe connections)')
    cng.add_argument('database');cng.add_argument('analysis_id');cng.add_argument('--limit',type=int,default=200)
    cnr=sub.add_parser('review-raster-gap')
    cnr.add_argument('database');cnr.add_argument('candidate_id');cnr.add_argument('--actor',required=True)
    cnr.add_argument('--reason',required=True)
    cnr.add_argument('--decision',required=True,choices=['CONTINUOUS_AS_DRAWN','SEPARATE_AS_DRAWN','UNRESOLVED','REJECTED'])
    cnt=sub.add_parser('trace-raster-centrelines',help='Trace reviewed drawing-only continuity')
    cnt.add_argument('database');cnt.add_argument('analysis_id');cnt.add_argument('start_centreline_id')
    cnt.add_argument('--include-unreviewed',action='store_true');cnt.add_argument('--max-hops',type=int,default=20)
    nc=sub.add_parser('raster-contacts');nc.add_argument('database');nc.add_argument('analysis_id')
    nc.add_argument('--limit',type=int,default=200)
    nr=sub.add_parser('review-raster-contact');nr.add_argument('database');nr.add_argument('candidate_id')
    nr.add_argument('--actor',required=True);nr.add_argument('--reason',required=True)
    nr.add_argument('--decision',required=True,choices=['CONTACT_AS_DRAWN','NOT_CONTACT_AS_DRAWN','UNRESOLVED','REJECTED'])
    topo=sub.add_parser("analyze-topology");topo.add_argument("database");topo.add_argument("extraction_id");topo.add_argument("--output-json")
    cand=sub.add_parser("topology-candidates");cand.add_argument("database");cand.add_argument("analysis_id");cand.add_argument("--kind",default="");cand.add_argument("--limit",type=int,default=100)
    trev=sub.add_parser("review-topology");trev.add_argument("database");trev.add_argument("candidate_id")
    trev.add_argument("--actor",required=True);trev.add_argument("--decision",required=True,choices=["CONNECTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"])
    trev.add_argument("--reason",required=True)
    sy=sub.add_parser("analyze-symbols");sy.add_argument("database");sy.add_argument("extraction_id")
    sy.add_argument("geometry_analysis_id");sy.add_argument("--output-json")
    syc=sub.add_parser("symbol-candidates");syc.add_argument("database");syc.add_argument("analysis_id")
    syc.add_argument("--candidate-class",default="");syc.add_argument("--limit",type=int,default=200)
    syr=sub.add_parser("review-symbol");syr.add_argument("database");syr.add_argument("candidate_id")
    syr.add_argument("--actor",required=True);syr.add_argument("--decision",required=True,
        choices=["ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","UNRESOLVED"])
    syr.add_argument("--reason",required=True);syr.add_argument("--edited-json")
    lw=sub.add_parser("analyze-linework");lw.add_argument("database");lw.add_argument("extraction_id")
    lw.add_argument("geometry_analysis_id");lw.add_argument("symbol_analysis_id");lw.add_argument("--output-json")
    lwc=sub.add_parser("linework-candidates");lwc.add_argument("database");lwc.add_argument("analysis_id")
    lwc.add_argument("--kind",default="");lwc.add_argument("--limit",type=int,default=200)
    lwr=sub.add_parser("review-linework");lwr.add_argument("database");lwr.add_argument("candidate_id")
    lwr.add_argument("--actor",required=True);lwr.add_argument("--decision",required=True,
        choices=["ACCEPTED_AS_READING","REJECTED","UNRESOLVED"])
    lwr.add_argument("--reason",required=True)
    dtrace=sub.add_parser("trace-drawing");dtrace.add_argument("database");dtrace.add_argument("linework_analysis_id")
    dtrace.add_argument("start_segment_id");dtrace.add_argument("--include-unreviewed",action="store_true")
    dtrace.add_argument("--max-hops",type=int,default=15)
    oi=sub.add_parser("import-ocr");oi.add_argument("database");oi.add_argument("extraction_id")
    oi.add_argument("--ocr-json",help="Existing standalone OCR result; otherwise run local Tesseract on embedded source")
    oi.add_argument("--output-json")
    oi.add_argument("--engine",choices=("auto","tesseract","rapidocr"),default="auto")
    ol=sub.add_parser("ocr-words");ol.add_argument("database");ol.add_argument("analysis_id")
    ol.add_argument("--text",default="");ol.add_argument("--limit",type=int,default=200)
    tl=sub.add_parser("analyze-text-links");tl.add_argument("database");tl.add_argument("extraction_id")
    tl.add_argument("symbol_analysis_id");tl.add_argument("ocr_analysis_id");tl.add_argument("--output-json")
    tc=sub.add_parser("text-link-candidates");tc.add_argument("database");tc.add_argument("analysis_id")
    tc.add_argument("--state",default="");tc.add_argument("--limit",type=int,default=200)
    tr=sub.add_parser("review-text-link");tr.add_argument("database");tr.add_argument("proposal_id")
    tr.add_argument("--actor",required=True);tr.add_argument("--reason",required=True)
    tr.add_argument("--decision",required=True,choices=["ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","UNRESOLVED"])
    tr.add_argument("--selected-text")
    se=sub.add_parser("symbol-evidence");se.add_argument("database");se.add_argument("text_link_analysis_id")
    se.add_argument("symbol_candidate_id")
    sg=sub.add_parser("analyze-signals");sg.add_argument("database");sg.add_argument("extraction_id")
    sg.add_argument("geometry_analysis_id");sg.add_argument("symbol_analysis_id")
    sg.add_argument("linework_analysis_id");sg.add_argument("--output-json")
    sc=sub.add_parser("signal-candidates");sc.add_argument("database");sc.add_argument("analysis_id")
    sc.add_argument("--limit",type=int,default=200)
    sr=sub.add_parser("review-signal");sr.add_argument("database");sr.add_argument("candidate_id")
    sr.add_argument("--actor",required=True);sr.add_argument("--reason",required=True)
    sr.add_argument("--decision",required=True,choices=["SUPPORTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"])
    tp=sub.add_parser("register-tag-profile");tp.add_argument("database");tp.add_argument("profile_json")
    te=sub.add_parser("evaluate-tag-profile");te.add_argument("database");te.add_argument("text_link_analysis_id")
    te.add_argument("profile_id");te.add_argument("--output-json")
    tg=sub.add_parser("get-tag-profile");tg.add_argument("database");tg.add_argument("profile_id")
    # Rev M: source-bound document navigation and explicitly reviewed signal paths.
    st=sub.add_parser("trace-signal");st.add_argument("database");st.add_argument("signal_analysis_id")
    st.add_argument("start_segment_id");st.add_argument("--include-unreviewed",action="store_true")
    st.add_argument("--max-hops",type=int,default=15);st.add_argument("--persist",action="store_true")
    sts=sub.add_parser("signal-trace-snapshot");sts.add_argument("database");sts.add_argument("trace_id")
    rd=sub.add_parser("register-drawing");rd.add_argument("database");rd.add_argument("extraction_id")
    rd.add_argument("--drawing-no",required=True);rd.add_argument("--revision",required=True)
    rd.add_argument("--facility",required=True);rd.add_argument("--area",required=True)
    rd.add_argument("--actor",required=True);rd.add_argument("--reason",required=True)
    ld=sub.add_parser("drawings");ld.add_argument("database");ld.add_argument("--search",default="")
    ld.add_argument("--limit",type=int,default=200)
    ma=sub.add_parser("annotate-offpage");ma.add_argument("database");ma.add_argument("extraction_id")
    ma.add_argument("--page",type=int,required=True);ma.add_argument("--bbox-json",required=True)
    ma.add_argument("--label",required=True);ma.add_argument("--actor",required=True);ma.add_argument("--reason",required=True)
    loa=sub.add_parser("offpage-annotations");loa.add_argument("database");loa.add_argument("--extraction-id")
    loa.add_argument("--limit",type=int,default=500)
    cm=sub.add_parser("analyze-crosssheet");cm.add_argument("database");cm.add_argument("extraction_ids",nargs="+")
    cm.add_argument("--output-json")
    cl=sub.add_parser("crosssheet-candidates");cl.add_argument("database");cl.add_argument("analysis_id")
    cl.add_argument("--limit",type=int,default=200)
    cr=sub.add_parser("review-crosssheet");cr.add_argument("database");cr.add_argument("candidate_id")
    cr.add_argument("--actor",required=True);cr.add_argument("--reason",required=True)
    cr.add_argument("--decision",required=True,choices=["LINKED_AS_DRAWN","NOT_LINKED_AS_DRAWN","UNRESOLVED","REJECTED"])
    dt=sub.add_parser("trace-drawings");dt.add_argument("database");dt.add_argument("analysis_id")
    dt.add_argument("start_extraction_id");dt.add_argument("--include-unreviewed",action="store_true")
    dt.add_argument("--max-hops",type=int,default=12)
    # Rev N: project-scoped template recognition, no model training.
    scatalog=sub.add_parser('register-symbol-catalogue');scatalog.add_argument('database')
    scatalog.add_argument('--catalogue-json',help='Optional project catalogue; if omitted register original synthetic examples')
    catalogread=sub.add_parser('get-symbol-catalogue');catalogread.add_argument('database');catalogread.add_argument('catalogue_id')
    catalogrun=sub.add_parser('analyze-symbol-catalogue');catalogrun.add_argument('database')
    catalogrun.add_argument('extraction_id');catalogrun.add_argument('geometry_analysis_id')
    catalogrun.add_argument('symbol_analysis_id');catalogrun.add_argument('linework_analysis_id')
    catalogrun.add_argument('catalogue_id');catalogrun.add_argument('--output-json')
    cataloglist=sub.add_parser('catalogue-candidates');cataloglist.add_argument('database')
    cataloglist.add_argument('analysis_id');cataloglist.add_argument('--candidate-class',default='')
    cataloglist.add_argument('--limit',type=int,default=200)
    catalogreview=sub.add_parser('review-catalogue');catalogreview.add_argument('database')
    catalogreview.add_argument('candidate_id');catalogreview.add_argument('--actor',required=True)
    catalogreview.add_argument('--decision',required=True,choices=['ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','UNRESOLVED'])
    catalogreview.add_argument('--reason',required=True);catalogreview.add_argument('--edited-json')
    # Rev O: bounded batch import, source-revision proposal comparisons and indexed search.
    bi=sub.add_parser('batch-import');bi.add_argument('database');bi.add_argument('inputs',nargs='+')
    bi.add_argument('--actor',required=True);bi.add_argument('--stop-after',type=int)
    bi.add_argument('--ocr',choices=('auto','tesseract','rapidocr','off'),default='auto')
    bi.add_argument('--in-process',action='store_true',help='Read PDFs inside this process (default: isolated child with time/memory limits)')
    br=sub.add_parser('batch-resume');br.add_argument('database');br.add_argument('batch_id')
    br.add_argument('--stop-after',type=int)
    br.add_argument('--in-process',action='store_true')
    br.add_argument('--ocr',choices=('auto','tesseract','rapidocr','off'),default='auto')
    bs=sub.add_parser('batch-status');bs.add_argument('database');bs.add_argument('batch_id')
    rc=sub.add_parser('compare-revisions');rc.add_argument('database');rc.add_argument('before_extraction_id')
    rc.add_argument('after_extraction_id');rc.add_argument('--output-json')
    rg=sub.add_parser('revision-comparison');rg.add_argument('database');rg.add_argument('comparison_id')
    ps=sub.add_parser('project-search');ps.add_argument('database');ps.add_argument('--tag',default='')
    ps.add_argument('--object-class',default='');ps.add_argument('--drawing-no',default='')
    ps.add_argument('--facility',default='');ps.add_argument('--limit',type=int,default=200)
    # Rev P: source-linked paged registers, graph views and bounded, offline reports.
    wr=sub.add_parser("register-page");wr.add_argument("database")
    wr.add_argument("--extraction-id",default="");wr.add_argument("--text",default="")
    wr.add_argument("--object-class",default="");wr.add_argument("--state",default="")
    wr.add_argument("--drawing-no",default="");wr.add_argument("--limit",type=int,default=100)
    wr.add_argument("--offset",type=int,default=0)
    wg=sub.add_parser("graph-view");wg.add_argument("database")
    wg.add_argument("--extraction-id",default="");wg.add_argument("--limit",type=int,default=100)
    wg.add_argument("--offset",type=int,default=0)
    wg.add_argument("--accepted-endpoints-only",action="store_true")
    wc=sub.add_parser("crosssheet-view");wc.add_argument("database")
    wc.add_argument("--analysis-id",default="");wc.add_argument("--limit",type=int,default=100)
    report=sub.add_parser("report-export");report.add_argument("database");report.add_argument("destination")
    report.add_argument("--format",choices=["json","csv","html"],required=True)
    report.add_argument("--extraction-ids",nargs="*");report.add_argument("--max-records",type=int,default=20000)
    report.add_argument("--overwrite",action="store_true")
    backup=sub.add_parser("backup-project");backup.add_argument("database");backup.add_argument("destination")
    wp=sub.add_parser('recover-wp123',help='WP01-03 additive OCR-register, detector triage and tag matching (sidecars only)')
    wp.add_argument('pdf');wp.add_argument('--ocr-csv',help='Previously exported source OCR words CSV')
    wp.add_argument('--ocr-source-sha256',help='Expected source SHA for external OCR CSV evidence')
    wp.add_argument('--detections-json',help='Existing model detections JSON; optional')
    wp.add_argument('--rois-json',help='Optional manual-review ROI manifest for offline high-resolution Tesseract')
    wp.add_argument('--scan-bubbles',action='store_true',help='Optional OCR-anchored raster circle proposals')
    wp.add_argument('--ocr-engine',choices=['auto','tesseract','rapidocr'],default='auto')
    wp.add_argument('--region-profile',choices=['auto','none','s418'],default='auto')
    wp.add_argument('--page',type=int,default=1,help='PDF page the detections (and an OCR CSV) belong to (default 1)')
    wp.add_argument('--output-dir',required=True)
    wp.add_argument('--store-database',help='Optional independent WP123 SQLite sidecar (never Worksheet DB)')
    tr=sub.add_parser('trainer',help='Background symbol-detector training (detached, low priority): start, status, pause, resume, cancel')
    tr.add_argument('action',choices=['start','status','pause','resume','cancel','tray','shortcut','autoresume','lineage','evaluate']);tr.add_argument('--state-dir',help='run folder (default %LOCALAPPDATA%/PIDReader/training/tr1; never OneDrive)')
    tr.add_argument('--tiles-dir');tr.add_argument('--torch-python',default='C:/PIDWork/venv312_torch/Scripts/python.exe');tr.add_argument('--init',help='starting weights (default: the repo E5 weights)')
    tr.add_argument('--from-scratch',action='store_true',help='start from COCO-style --init instead of continuing trained weights');tr.add_argument('--epochs',type=int,default=6)
    tr.add_argument('--mark',type=int,help='lineage: finished-run id to mark');tr.add_argument('--entry',type=int,help='evaluate: finished-run id to score (default: the newest)');tr.add_argument('--status',choices=['usable','rejected'],help='lineage: new status for --mark');tr.add_argument('--desktop',help='folder for the shortcut (default: your Desktop)');tr.add_argument('--threads',type=int,default=2);tr.add_argument('--hours-per-day',type=float,default=0.0,help='0 = no daily limit (default)');tr.add_argument('--lr',type=float,default=0.005)
    wpr=sub.add_parser('wp123-review',help='Append named human decision to isolated WP123 sidecar')
    wpr.add_argument('database');wpr.add_argument('analysis_id');wpr.add_argument('target_id')
    wpr.add_argument('--actor',required=True);wpr.add_argument('--reason',required=True)
    wpr.add_argument('--decision',required=True,choices=['ACCEPTED_AS_READING','CORRECTED_READING','REJECTED','UNRESOLVED'])
    wpr.add_argument('--corrected-text')
    wpv=sub.add_parser('wp123-audit',help='Validate independent WP123 append-only review chain')
    wpv.add_argument('database')
    aa=sub.add_parser("analyze-all",help="Run every analysis layer on a stored drawing (proposals only)")
    aa.add_argument("database");aa.add_argument("extraction_id")
    aa.add_argument("--ocr",choices=("auto","tesseract","rapidocr","off"),default="auto")
    aa.add_argument("--catalogue-id",default=None)
    aa.add_argument("--depth",choices=("quick","standard","deep"),default="standard",help="CPU time budget of the analysis")
    aa.add_argument("--no-library-symbols",action="store_true",help="skip library symbol detection, typed graph and loops")
    aa.add_argument("--full",action="store_true",help="print every item and graph instead of counts")
    rs=sub.add_parser("reconcile-sheets",help="Off-page matches and same-tag identity proposals across the drawings of a project (proposals only)")
    rs.add_argument("database");rs.add_argument("--extraction-id",action="append",default=None)
    ei=sub.add_parser("export-intelligence",help="Write the engineering-intelligence-v1 JSON of the latest run (schema-validated)")
    ei.add_argument("database");ei.add_argument("extraction_id");ei.add_argument("destination")
    ap2=sub.add_parser("export-ai-package",help="Write the AI-ready package (manifest, registers, graphs, evidence, prompt) into a new sub-folder")
    ap2.add_argument("database");ap2.add_argument("extraction_id");ap2.add_argument("folder")
    rl=sub.add_parser("review-ledger",help="R5: list ambiguous/blocked connection candidates (never topology); --record adds a named human decision. Needs PID_R5_REVIEW_LEDGER=on or shadow")
    rl.add_argument("database");rl.add_argument("extraction_id");rl.add_argument("--record");rl.add_argument("--actor");rl.add_argument("--decision");rl.add_argument("--reason")
    dx=sub.add_parser("export-dexpi",help="R5: PROPOSED DEXPI 2.0.1 export + sidecar + separate checks into FOLDER. Off unless PID_R5_DEXPI=on or shadow. Not a conformance claim")
    dx.add_argument("database");dx.add_argument("extraction_id");dx.add_argument("folder");dx.add_argument("--include-unreviewed",action="store_true")
    dx.add_argument("--dexpi-files",help="folder with the official Core.xml and Plant.xml (structure check) and DEXPI_XML_Schema.xsd (needs lxml)")
    sub.add_parser("r5-features",help="Show every R5 switch (OFF/SHADOW/ON) and the features kept disabled")
    sub.add_parser("tr1-status",help="TR1: show every PIDLAB_*_TR1 switch and whether the learned detector can run (all OFF by default)")
    td=sub.add_parser("tr1-detect",help="TR1: run the learned symbol detector on one PDF page (PROPOSED detections only). Needs PIDLAB_SYMBOL_FRCNN_TR1=on and the optional torch component")
    td.add_argument("pdf");td.add_argument("--page",type=int,default=1);td.add_argument("--timeout",type=float,default=None);td.add_argument("--output-json")
    xp=sub.add_parser("export-xlsx",help="Excel workbook of registers, loops, lines, findings and checks (unverified readings)")
    xp.add_argument("database");xp.add_argument("destination");xp.add_argument("--extraction-id",action="append",default=None)
    gx=sub.add_parser("graph-export",help="Canonical proposed-connectivity graph of one drawing (JSON or GraphML)")
    gx.add_argument("database");gx.add_argument("extraction_id");gx.add_argument("destination")
    gx.add_argument("--format",choices=("json","graphml"),default="json")
    ed=sub.add_parser("export-drawings",help="Save each drawing as its own files (JSON, HTML, graph) named after the original PDF")
    ed.add_argument("database");ed.add_argument("folder");ed.add_argument("--extraction-id",action="append",default=None)
    ts=sub.add_parser("teach-symbol",help="Box one symbol and find look-alikes on the page (no training)")
    ts.add_argument("database");ts.add_argument("extraction_id");ts.add_argument("--page",type=int,required=True)
    ts.add_argument("--box",type=float,nargs=4,metavar=("X0","Y0","X1","Y1"),required=True,help="normalised, top-left origin")
    ts.add_argument("--label",required=True);ts.add_argument("--kind",default="OTHER")
    ts.add_argument("--threshold",type=float,default=0.72);ts.add_argument("--actor",required=True)
    si=sub.add_parser("sheet-info",help="Title block, line sizes/numbers, set-points, loops and reading checks of one drawing")
    si.add_argument("database");si.add_argument("extraction_id")
    gp=sub.add_parser("gui",help="Open the desktop application");gp.add_argument("database",nargs="?",default=None)
    sub.add_parser("gui-legacy",help="Original Rev Q development viewer (kept for audit)").add_argument("database")
    args=p.parse_args(argv)
    try:
        if args.cmd=='wp123-review':
            from .engineering.wp123_store import WP123Store
            with WP123Store(args.database) as store:
                event_id=store.review(args.analysis_id,args.target_id,actor=args.actor,decision=args.decision,
                                      reason=args.reason,corrected_text=args.corrected_text)
                print(canonical_json({'review_id':event_id,'audit_errors':store.verify_audit()}))
            return 0
        if args.cmd=='wp123-audit':
            from .engineering.wp123_store import WP123Store
            with WP123Store(args.database) as store:
                errors=store.verify_audit()
                print(canonical_json({'audit_ok':not errors,'errors':errors}))
            return 0 if not errors else 2
        if args.cmd=='trainer':
            from .engineering.trainer_service import service as trainer_service
            state=args.state_dir or str(trainer_service.default_state_dir())
            if args.action=='start':
                root=Path(__file__).resolve().parents[2]
                cfg=dict(state_dir=state,tiles_dir=args.tiles_dir or 'C:/PIDWork/tr1/tiles',torch_python=args.torch_python,epochs=args.epochs,threads=args.threads,
                         daily_budget_s=int(args.hours_per_day*3600),lr=args.lr,init=args.init or (str(root/'models'/'E5_weights_epoch_02.pt') if args.from_scratch else 'auto'),init_trained=not args.from_scratch)
                print(canonical_json(trainer_service.start(cfg)))
            elif args.action=='status':
                print(canonical_json(trainer_service.status(state)))
            elif args.action=='lineage':
                trainer_service.register_finished_run(state)
                if args.mark:
                    trainer_service.mark_lineage(state,args.mark,args.status or 'usable')
                print(canonical_json({'lineage':trainer_service.read_lineage(state)}))
            elif args.action=='evaluate':
                from .engineering.trainer_service import evaluate as trainer_eval
                trainer_service.register_finished_run(state)
                cfg=dict(trainer_service.DEFAULTS,**(trainer_service.read_json(Path(state)/'config.json',{}) or {}))
                print(canonical_json(trainer_eval.evaluate_guarded(state,cfg,entry_id=args.entry)))
            elif args.action=='autoresume':
                out=trainer_service.resume_if_interrupted(state)
                from .engineering.trainer_service import evaluate as trainer_eval
                if out.get('action')=='none' and trainer_eval.evaluation_pending(state):
                    out['evaluation']='started' if trainer_eval.spawn_evaluation(state) else 'not started'
                print(canonical_json(out))
            elif args.action=='shortcut':
                from .ui.training_tray import make_desktop_shortcut
                print(canonical_json({'shortcut':str(make_desktop_shortcut(args.desktop,state))}))
            elif args.action=='tray':
                print(canonical_json({'tray_launched':trainer_service.ensure_tray(state),'state_dir':state}))
            else:
                getattr(trainer_service,args.action)(state);print(canonical_json({'requested':args.action,'state_dir':state}))
            return 0
        if args.cmd=='recover-wp123':
            from .engineering.wp123_recovery import read_ocr_csv,read_detectors,recover_wp123,save_wp123
            from .engineering.wp123_roi import supplemental_ocr
            source=Path(args.pdf).read_bytes()
            if args.ocr_csv:
                from hashlib import sha256
                if args.ocr_source_sha256 and args.ocr_source_sha256!=sha256(source).hexdigest():
                    raise ValueError('External OCR declared source SHA does not match PDF')
                words=read_ocr_csv(args.ocr_csv,page=args.page)
            else:
                from .formats.ocr_source import ocr_pdf_preview
                preview=ocr_pdf_preview(source,engine=args.ocr_engine)
                words=[{'id':w['id'],'text':w['text'],'page':w['page'],
                        'bbox':w['bbox'],'raw_score':w['raw_ocr_score'],
                        'review_state':'PROPOSED_UNVERIFIED'}
                       for page in preview['pages'] for w in page['words']]
            if args.rois_json:
                rois=json.loads(Path(args.rois_json).read_text(encoding='utf-8'))
                words+=supplemental_ocr(source,rois)
            if args.detections_json:
                from hashlib import sha256
                import pdfplumber
                from io import BytesIO
                from .formats.page_coordinates import frame_from_pdfplumber
                with pdfplumber.open(BytesIO(source)) as _pl:
                    _frame=frame_from_pdfplumber(_pl.pages[args.page-1])
                detections=read_detectors(args.detections_json,expected_source_sha256=sha256(source).hexdigest(),page_frame=_frame)
            else:detections=[]
            if args.scan_bubbles:
                from .engineering.wp123_bubbles import scan_pdf_bubbles
                from .engineering.wp123_recovery import infer_regions
                bubbles=scan_pdf_bubbles(source,words,infer_regions(words,profile=args.region_profile),page=args.page)
            else:bubbles=[]
            result=recover_wp123(source,words,detections,profile=args.region_profile,bubbles=bubbles)
            save_wp123(result,args.output_dir)
            analysis_id=None
            if args.store_database:
                from .engineering.wp123_store import WP123Store
                with WP123Store(args.store_database) as store:analysis_id=store.add(result)
            print(canonical_json({'analysis_id':analysis_id,'result_sha256':result['result_sha256'],
                                   'summary':result['summary'],'output_dir':args.output_dir}))
            return 0
        if args.cmd=="raster-preview":
            from .engineering.raster_geometry import analyze_raster_geometry
            result=analyze_raster_geometry(Path(args.pdf).read_bytes(),
                pages=tuple(args.pages) if args.pages else None,dpi=args.dpi)
            data=canonical_json(result)
            if args.output_json:Path(args.output_json).write_text(data,encoding="utf-8")
            else:print(data)
            return 0
        if args.cmd=="ocr-preview":
            from .formats.ocr_source import ocr_pdf_preview
            result=ocr_pdf_preview(Path(args.pdf).read_bytes(),engine=args.engine)
            text=canonical_json(result)
            if args.output_json:
                Path(args.output_json).write_text(text,encoding="utf-8")
            else:
                print(text)
            return 0
        if args.cmd=="inspect-dxf":
            from .formats.dxf_source import read_dxf
            result=read_dxf(Path(args.dxf).read_bytes())
            text=canonical_json(result)
            if args.output_json:
                Path(args.output_json).write_text(text,encoding="utf-8")
            else:
                print(text)
            return 0
        if args.cmd=="r5-features":
            from .engineering import r5_features
            print(canonical_json(r5_features.inventory()))
            return 0
        if args.cmd=="tr1-status":
            from .tr1 import detector as tr1_detector, flags as tr1_flags
            print(canonical_json({"flags":tr1_flags.inventory(),"detector":tr1_detector.status()}))
            return 0
        if args.cmd=="tr1-detect":
            from .tr1 import detector as tr1_detector
            res=tr1_detector.detect(args.pdf,args.page,timeout_s=args.timeout)
            res.pop("record",None)
            text=canonical_json(res)
            if args.output_json:
                Path(args.output_json).write_text(text,encoding="utf-8")
            else:
                print(text)
            return 0 if res["status"]=="DONE" else (3 if res["status"]=="UNAVAILABLE" else 4)
        if args.cmd=="gui":
            from .ui.app import run_app
            return run_app(args.database)
        if args.cmd=="gui-legacy":
            from .ui.desktop import run_ui
            return run_ui(args.database)
        with ProjectStore(args.database) as db:
            if args.cmd=="init-project":
                print("Local project created:",args.database)
            elif args.cmd=="import-pdf":
                source=Path(args.pdf)
                data=source.read_bytes()
                if args.ocr=="off":
                    doc=read_pid(data,ReadParams(),filename=source.name,document_revision_id=args.revision_id)
                else:
                    from .engineering.standalone_read import read_pid_standalone
                    doc=read_pid_standalone(data,ReadParams(),filename=source.name,document_revision_id=args.revision_id,ocr_engine=args.ocr)
                extraction=db.add_extraction(doc,source_pdf_bytes=data)
                if args.output_json:
                    Path(args.output_json).write_text(canonical_json(doc),encoding="utf-8")
                print(canonical_json({"extraction_id":extraction,"objects":len(doc["objects"]),"connections":len(doc["connections"]),"pages":len(doc["pages"]),"warnings":len(doc["warnings"])}))
            elif args.cmd=="analyze-raster":
                from .engineering.raster_geometry import analyze_raster_geometry
                extraction=db.export_extraction(args.extraction_id)
                source=db.get_source_pdf(extraction["document"]["sha256"])
                if source is None: raise ValueError("Embedded PDF source required")
                result=analyze_raster_geometry(source,pages=tuple(args.pages) if args.pages else tuple(x["page"] for x in extraction["pages"]),dpi=args.dpi)
                aid=db.add_raster_analysis(args.extraction_id,result)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"raster_strokes":len(result["stroke_candidates"]),
                        "filled_valves":len(result["filled_valve_candidates"]),
                        "outlined_valves":len(result.get("outline_valve_candidates",[]))}))
            elif args.cmd=="raster-valves":
                print(canonical_json(db.list_raster_valves(args.analysis_id,limit=args.limit)))
            elif args.cmd=="review-raster-valve":
                print(db.review_raster_valve(args.candidate_id,actor=args.actor,decision=args.decision,reason=args.reason))
            elif args.cmd=='analyze-raster-network':
                from .engineering.raster_network import build_raster_network
                raster=db.get_raster_analysis(args.raster_analysis_id)
                ocr=db.get_ocr_analysis(args.ocr_analysis_id) if args.ocr_analysis_id else None
                derived=build_raster_network(raster,ocr)
                aid=db.add_raster_network_analysis(args.extraction_id,args.raster_analysis_id,
                                                  derived,ocr_analysis_id=args.ocr_analysis_id)
                if args.output_json:Path(args.output_json).write_text(canonical_json(derived),encoding='utf-8')
                print(canonical_json({'analysis_id':aid,'contacts':len(derived['contact_candidates']),
                                      'strokes':len(derived['stroke_evidence'])}))
            elif args.cmd=='analyze-raster-centrelines':
                from .engineering.raster_centrelines import build_raster_centrelines
                raster=db.get_raster_analysis(args.raster_analysis_id)
                network=db.get_raster_network_analysis(args.raster_network_analysis_id)
                derived=build_raster_centrelines(raster,network)
                aid=db.add_raster_centreline_analysis(args.extraction_id,args.raster_analysis_id,
                                                       args.raster_network_analysis_id,derived)
                if args.output_json:Path(args.output_json).write_text(canonical_json(derived),encoding='utf-8')
                print(canonical_json({'analysis_id':aid,'centrelines':len(derived['centrelines']),
                                      'gaps':len(derived['gap_candidates'])}))
            elif args.cmd=='raster-gaps':
                print(canonical_json(db.list_raster_centreline_gaps(args.analysis_id,limit=args.limit)))
            elif args.cmd=='review-raster-gap':
                print(db.review_raster_centreline_gap(args.candidate_id,actor=args.actor,
                                                       decision=args.decision,reason=args.reason))
            elif args.cmd=='trace-raster-centrelines':
                from .engineering.raster_centrelines import trace_reviewed_centrelines
                print(canonical_json(trace_reviewed_centrelines(db,args.analysis_id,args.start_centreline_id,
                                  include_unreviewed=args.include_unreviewed,max_hops=args.max_hops)))
            elif args.cmd=='raster-contacts':
                print(canonical_json(db.list_raster_network_contacts(args.analysis_id,limit=args.limit)))
            elif args.cmd=='review-raster-contact':
                print(db.review_raster_network_contact(args.candidate_id,actor=args.actor,
                        decision=args.decision,reason=args.reason))
            elif args.cmd=="export-xlsx":
                from .engineering.xlsx_export import export_xlsx
                out=export_xlsx(db,args.destination,extraction_ids=args.extraction_id)
                print(canonical_json({"workbook":str(out)}))
            elif args.cmd=="export-drawings":
                from .engineering.drawing_export import export_drawings
                res=export_drawings(db,args.extraction_id,args.folder)
                print(canonical_json({"folder":res["folder"],"saved":[{"drawing":n,"files":[str(p) for p in ps]} for n,ps in res["saved"]],
                                      "failed":[{"drawing":n,"reason":r} for n,r in res["failed"]]}))
            elif args.cmd=="graph-export":
                from .engineering.graph_export import canonical_graph,to_graphml
                graph=canonical_graph(db,args.extraction_id)
                text=to_graphml(graph) if args.format=="graphml" else canonical_json(graph)
                Path(args.destination).write_text(text,encoding="utf-8")
                print(canonical_json({"destination":str(args.destination),"format":args.format,"nodes":len(graph["nodes"]),
                                      "edges":len(graph["edges"]),"review_policy":graph["review_policy"]}))
            elif args.cmd=="teach-symbol":
                from .engineering.examples import teach_symbol
                x0,y0,x1,y1=args.box
                aid,result=teach_symbol(db,args.extraction_id,page=args.page,bbox={"x0":x0,"y0":y0,"x1":x1,"y1":y1},
                                        label=args.label,class_hint=args.kind,actor=args.actor,threshold=args.threshold)
                print(canonical_json({"analysis_id":aid,"matches":len(result["matches"]),
                                      "top_scores":[m["score"] for m in result["matches"][:10]]}))
            elif args.cmd=="sheet-info":
                from .engineering.checks import consistency_checks,instrument_loops
                from .engineering.findings import latest_analysis_ids,list_findings
                from .engineering.sheet_fields import sheet_fields
                ex=db.export_extraction(args.extraction_id);ids=latest_analysis_ids(db,args.extraction_id)
                words=db.list_ocr_words(ids["ocr"],limit=2000) if "ocr" in ids else []
                fields=sheet_fields(ex,words)
                symbols=[f["detail"] for f in list_findings(db,args.extraction_id,"symbols",limit=2000)]
                print(canonical_json({"sheet_fields":fields,"loops":instrument_loops(ex),"checks":consistency_checks(ex,symbols,fields)}))
            elif args.cmd=="analyze-all":
                from .engineering.pipeline import analyze_drawing
                out=analyze_drawing(db,args.extraction_id,ocr_engine=None if args.ocr=="off" else args.ocr,
                                    catalogue_id=args.catalogue_id,preset=args.depth,library_symbols=not args.no_library_symbols,
                                    progress=lambda st,fr,msg:print(f"[{fr:4.0%}] {msg}",file=sys.stderr))
                if not args.full:
                    out=dict(out)
                    for heavy in ("items","graphs","page_analysis"):
                        out[heavy]=f"{len(out[heavy])} (use --full to print)" if heavy!="page_analysis" else [{k:p[k] for k in ("page","classification","reason")} for p in out[heavy]]
                    out["loops"]={"loops":len(out["loops"].get("loops",[])),"relations":len(out["loops"].get("relations",[]))}
                print(canonical_json(out))
            elif args.cmd=="reconcile-sheets":
                from .engineering.crosssheet import reconcile_project
                res=reconcile_project(db,args.extraction_id)
                print(canonical_json({"sheets":[{"sheet":s["sheet_id"],"drawing_ref":s["drawing_ref"]} for s in res["sheets"]],"connectors":len(res["connectors"]),
                                      "candidates":res["candidates"],"conflicts":res["conflicts"],"insufficient":res["insufficient"],
                                      "identity":res["identity"],"run_id":res["run_id"]}))
            elif args.cmd=="export-intelligence":
                from .engineering.intelligence import build_snapshot,validate_snapshot
                snap=build_snapshot(db,args.extraction_id)
                problems=validate_snapshot(snap)
                if problems:
                    raise ValueError("Snapshot failed validation: "+"; ".join(problems[:5]))
                target=Path(args.destination)
                if target.exists():
                    raise FileExistsError("Refusing to overwrite an existing file")
                target.write_text(json.dumps(snap,indent=1,sort_keys=True),encoding="utf-8")
                print(canonical_json({"written":str(target),"status":snap["package"]["status"],"entities":len(snap["entities"]),"relationships":len(snap["relationships"])}))
            elif args.cmd=="export-ai-package":
                from .engineering.intelligence import export_package
                print(canonical_json({"package":str(export_package(db,args.extraction_id,args.folder))}))
            elif args.cmd=="review-ledger":
                from .engineering import r5_features
                from .engineering.connection_review import ledger_for_run,record_review
                if r5_features.mode("REVIEW_LEDGER")==r5_features.OFF:
                    raise ValueError("REVIEW_LEDGER_OFF: set PID_R5_REVIEW_LEDGER=on (or shadow) to use the review ledger")
                if args.record:
                    print(canonical_json({"decision_id":record_review(db,args.extraction_id,args.record,actor=args.actor or "",decision=args.decision or "",reason=args.reason or "")}))
                else:
                    print(canonical_json(ledger_for_run(db,args.extraction_id)))
            elif args.cmd=="export-dexpi":
                from .engineering.dexpi_proposed import export_dexpi_proposed
                from .engineering.intelligence import build_snapshot
                files=Path(args.dexpi_files) if args.dexpi_files else None
                reg=tuple(str(files/n) for n in ("Core.xml","Plant.xml") if files and (files/n).is_file()) if files else ()
                xsd=files/"DEXPI_XML_Schema.xsd" if files and (files/"DEXPI_XML_Schema.xsd").is_file() else None
                print(canonical_json(export_dexpi_proposed(build_snapshot(db,args.extraction_id),args.folder,include_unreviewed=args.include_unreviewed,registry_files=reg,xsd_path=xsd)))
            elif args.cmd=="list":
                print(json.dumps(db.list_objects(text=args.text,limit=args.limit),indent=2))
            elif args.cmd=="show":
                print(json.dumps({"observation":db.get_object(args.observation_id),"review":db.effective_review(args.observation_id)},indent=2))
            elif args.cmd=="connections":
                print(json.dumps(db.connected_to(args.observation_id),indent=2))
            elif args.cmd=="review":
                edited=json.loads(Path(args.edited_json).read_text(encoding="utf-8")) if args.edited_json else None
                print(db.review(args.observation_id,actor=args.actor,decision=args.decision,reason=args.reason,edited=edited))
            elif args.cmd=='register-symbol-catalogue':
                from .engineering.symbol_catalog import example_catalog
                catalogue=(json.loads(Path(args.catalogue_json).read_text(encoding='utf-8'))
                           if args.catalogue_json else example_catalog())
                print(canonical_json({'catalogue_id':db.register_symbol_catalogue(catalogue),
                                       'templates':len(catalogue['templates'])}))
            elif args.cmd=='get-symbol-catalogue':
                print(canonical_json(db.get_symbol_catalogue(args.catalogue_id)))
            elif args.cmd=='analyze-symbol-catalogue':
                aid,result=db.analyze_symbol_catalogue(args.extraction_id,args.geometry_analysis_id,
                    args.symbol_analysis_id,args.linework_analysis_id,args.catalogue_id)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding='utf-8')
                print(canonical_json({'analysis_id':aid,'candidates':len(result['candidates'])}))
            elif args.cmd=='catalogue-candidates':
                print(canonical_json(db.list_catalogue_candidates(args.analysis_id,
                    candidate_class=args.candidate_class,limit=args.limit)))
            elif args.cmd=='review-catalogue':
                edited=json.loads(Path(args.edited_json).read_text(encoding='utf-8')) if args.edited_json else None
                print(db.review_catalogue_candidate(args.candidate_id,actor=args.actor,
                    decision=args.decision,reason=args.reason,edited=edited))
            elif args.cmd=="import-ocr":
                from .formats.ocr_source import ocr_pdf_preview
                extraction=db.export_extraction(args.extraction_id)
                if args.ocr_json:
                    result=json.loads(Path(args.ocr_json).read_text(encoding="utf-8"))
                else:
                    source=db.get_source_pdf(extraction["document"]["sha256"])
                    if source is None:raise ValueError("Embedded PDF source bytes are required")
                    result=ocr_pdf_preview(source,pages=tuple(x["page"] for x in extraction["pages"]),engine=args.engine)
                aid=db.add_ocr_analysis(args.extraction_id,result)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"words":sum(len(p["words"]) for p in result["pages"])}))
            elif args.cmd=="ocr-words":
                print(json.dumps(db.list_ocr_words(args.analysis_id,text=args.text,limit=args.limit),indent=2))
            elif args.cmd=="analyze-text-links":
                from .engineering.text_links import build_text_links
                extraction=db.export_extraction(args.extraction_id)
                symbols=db.get_symbol_analysis(args.symbol_analysis_id)
                ocr=db.get_ocr_analysis(args.ocr_analysis_id)
                result=build_text_links(extraction,symbols,ocr)
                aid=db.add_text_link_analysis(args.extraction_id,args.symbol_analysis_id,args.ocr_analysis_id,result)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"proposals":len(result["proposals"]),
                      "ambiguous":sum(p["association_state"]=="MULTIPLE_TEXT_OPTIONS" for p in result["proposals"])}))
            elif args.cmd=="text-link-candidates":
                print(json.dumps(db.list_text_link_proposals(args.analysis_id,state=args.state,limit=args.limit),indent=2))
            elif args.cmd=="review-text-link":
                print(db.review_text_link(args.proposal_id,actor=args.actor,decision=args.decision,
                                          reason=args.reason,selected_text=args.selected_text))
            elif args.cmd=="symbol-evidence":
                print(json.dumps(db.symbol_evidence(args.text_link_analysis_id,args.symbol_candidate_id),indent=2))
            elif args.cmd=="analyze-topology":
                from .engineering.topology import analyze_pdf_topology
                extraction=db.export_extraction(args.extraction_id)
                source=db.get_source_pdf(extraction["document"]["sha256"])
                if not source:
                    raise ValueError("The source PDF bytes were not embedded in this project; analysis cannot be reproduced")
                page_numbers=tuple(x["page"] for x in extraction["pages"])
                result=analyze_pdf_topology(source,pages=page_numbers)
                analysis=db.add_geometry_analysis(args.extraction_id,result)
                if args.output_json:
                    Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":analysis,"segments":len(result["segments"]),"contacts":len(result["contact_candidates"]),"shapes":len(result["shape_candidates"]),"warnings":result["warnings"]}))
            elif args.cmd=="topology-candidates":
                print(json.dumps(db.list_geometry_candidates(args.analysis_id,kind=args.kind,limit=args.limit),indent=2))
            elif args.cmd=="review-topology":
                print(db.review_geometry(args.candidate_id,actor=args.actor,decision=args.decision,reason=args.reason))
            elif args.cmd=="analyze-symbols":
                from .engineering.symbols import build_symbol_proposals
                extraction=db.export_extraction(args.extraction_id)
                topo=db.get_geometry_analysis(args.geometry_analysis_id)
                result=build_symbol_proposals(extraction,topo)
                aid=db.add_symbol_analysis(args.extraction_id,args.geometry_analysis_id,result)
                if args.output_json:
                    Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"symbols":len(result["symbol_candidates"]),
                                      "ports":len(result["port_candidates"])}))
            elif args.cmd=="symbol-candidates":
                print(json.dumps(db.list_symbol_candidates(args.analysis_id,limit=args.limit,
                                       candidate_class=args.candidate_class),indent=2))
            elif args.cmd=="review-symbol":
                edit=json.loads(Path(args.edited_json).read_text(encoding="utf-8")) if args.edited_json else None
                print(db.review_symbol(args.candidate_id,actor=args.actor,decision=args.decision,
                      reason=args.reason,edited=edit))
            elif args.cmd=="analyze-linework":
                from .engineering.linework import build_linework_proposals
                extraction=db.export_extraction(args.extraction_id)
                topology=db.get_geometry_analysis(args.geometry_analysis_id)
                symbols=db.get_symbol_analysis(args.symbol_analysis_id)
                result=build_linework_proposals(extraction,topology,symbols)
                aid=db.add_linework_analysis(args.extraction_id,args.geometry_analysis_id,args.symbol_analysis_id,result)
                if args.output_json:
                    Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"valves":len(result["valve_candidates"]),
                    "valve_ports":len(result["valve_port_candidates"]),
                    "possible_signal_strokes":sum(x["role"]=="SIGNAL_STYLE_CANDIDATE" for x in result["stroke_roles"]),
                    "mixed_style_contacts":len(result["mixed_style_contacts"])}))
            elif args.cmd=="linework-candidates":
                print(json.dumps(db.list_linework_candidates(args.analysis_id,kind=args.kind,limit=args.limit),indent=2))
            elif args.cmd=="review-linework":
                print(db.review_linework(args.candidate_id,actor=args.actor,decision=args.decision,reason=args.reason))
            elif args.cmd=="trace-drawing":
                print(json.dumps(db.trace_drawing(args.linework_analysis_id,args.start_segment_id,
                    include_unreviewed=args.include_unreviewed,max_hops=args.max_hops),indent=2))
            elif args.cmd=="analyze-signals":
                from .engineering.signal_links import build_signal_links
                result=build_signal_links(db.export_extraction(args.extraction_id),
                    db.get_geometry_analysis(args.geometry_analysis_id),
                    db.get_symbol_analysis(args.symbol_analysis_id),
                    db.get_linework_analysis(args.linework_analysis_id))
                aid=db.add_signal_analysis(args.extraction_id,args.geometry_analysis_id,
                    args.symbol_analysis_id,args.linework_analysis_id,result)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"signal_candidates":len(result["candidates"])}))
            elif args.cmd=="signal-candidates":
                print(json.dumps(db.list_signal_candidates(args.analysis_id,limit=args.limit),indent=2))
            elif args.cmd=="review-signal":
                print(db.review_signal(args.candidate_id,actor=args.actor,decision=args.decision,reason=args.reason))
            elif args.cmd=="register-tag-profile":
                profile=json.loads(Path(args.profile_json).read_text(encoding="utf-8"))
                print(db.register_tag_profile(profile))
            elif args.cmd=="get-tag-profile":
                print(canonical_json(db.get_tag_profile(args.profile_id)))
            elif args.cmd=="evaluate-tag-profile":
                eid,result=db.evaluate_tag_profile(args.text_link_analysis_id,args.profile_id)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"evaluation_id":eid,"records":len(result["entries"])}))
            elif args.cmd=="trace-signal":
                print(canonical_json(db.trace_signal(args.signal_analysis_id,args.start_segment_id,
                    include_unreviewed=args.include_unreviewed,max_hops=args.max_hops,persist=args.persist)))
            elif args.cmd=="signal-trace-snapshot":
                print(canonical_json(db.get_signal_trace_snapshot(args.trace_id)))
            elif args.cmd=="register-drawing":
                print(db.register_drawing(args.extraction_id,drawing_no=args.drawing_no,
                    revision_label=args.revision,facility=args.facility,area=args.area,
                    actor=args.actor,reason=args.reason))
            elif args.cmd=="drawings":
                print(canonical_json(db.list_drawings(search=args.search,limit=args.limit)))
            elif args.cmd=="annotate-offpage":
                box=json.loads(Path(args.bbox_json).read_text(encoding="utf-8"))
                print(db.annotate_offpage(args.extraction_id,page=args.page,bbox=box,
                    label=args.label,actor=args.actor,reason=args.reason))
            elif args.cmd=="offpage-annotations":
                print(canonical_json(db.list_offpage_annotations(extraction_id=args.extraction_id,limit=args.limit)))
            elif args.cmd=="analyze-crosssheet":
                aid,result=db.analyze_crosssheet(args.extraction_ids)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding="utf-8")
                print(canonical_json({"analysis_id":aid,"proposals":len(result["candidates"])}))
            elif args.cmd=="crosssheet-candidates":
                print(canonical_json(db.list_crosssheet_candidates(args.analysis_id,limit=args.limit)))
            elif args.cmd=="review-crosssheet":
                print(db.review_crosssheet(args.candidate_id,actor=args.actor,
                    decision=args.decision,reason=args.reason))
            elif args.cmd=="trace-drawings":
                print(canonical_json(db.trace_drawings(args.analysis_id,args.start_extraction_id,
                    include_unreviewed=args.include_unreviewed,max_hops=args.max_hops)))
            elif args.cmd=='batch-import':
                from .engineering.batch import start_batch,resume_batch
                bid=start_batch(db,args.inputs,actor=args.actor)
                job=resume_batch(db,bid,stop_after=args.stop_after,isolated=not args.in_process,ocr_engine=args.ocr)
                print(canonical_json({'batch_id':bid,'state':job['state'],'counts':job['counts']}))
            elif args.cmd=='batch-resume':
                from .engineering.batch import resume_batch
                job=resume_batch(db,args.batch_id,stop_after=args.stop_after,isolated=not args.in_process,ocr_engine=args.ocr)
                print(canonical_json({'batch_id':job['batch_id'],'state':job['state'],'counts':job['counts']}))
            elif args.cmd=='batch-status':
                print(canonical_json(db.get_batch(args.batch_id)))
            elif args.cmd=='compare-revisions':
                cid,result=db.compare_revisions(args.before_extraction_id,args.after_extraction_id)
                if args.output_json:Path(args.output_json).write_text(canonical_json(result),encoding='utf-8')
                print(canonical_json({'comparison_id':cid,'source_state':result['source_state'],
                    'events':len(result['events']),'unmatched_before':len(result['unmatched_before']),
                    'unmatched_after':len(result['unmatched_after'])}))
            elif args.cmd=='revision-comparison':
                print(canonical_json(db.get_revision_comparison(args.comparison_id)))
            elif args.cmd=='project-search':
                print(canonical_json(db.search_project(tag=args.tag,object_class=args.object_class,
                    drawing_no=args.drawing_no,facility=args.facility,limit=args.limit)))
            elif args.cmd=="register-page":
                from .engineering.workspace import register_page
                print(canonical_json(register_page(db, extraction_id=args.extraction_id,text=args.text,
                    object_class=args.object_class,state=args.state,drawing_no=args.drawing_no,
                    limit=args.limit,offset=args.offset)))
            elif args.cmd=="graph-view":
                from .engineering.workspace import drawing_graph_view
                print(canonical_json(drawing_graph_view(db,extraction_id=args.extraction_id,
                    limit=args.limit,offset=args.offset,accepted_endpoints_only=args.accepted_endpoints_only)))
            elif args.cmd=="crosssheet-view":
                from .engineering.workspace import crosssheet_graph_view
                print(canonical_json(crosssheet_graph_view(db,analysis_id=args.analysis_id,limit=args.limit)))
            elif args.cmd=="report-export":
                from .engineering.reports import make_report,save_report
                document=make_report(db,extraction_ids=args.extraction_ids,max_records=args.max_records)
                save_report(document,args.destination,fmt=args.format,overwrite=args.overwrite)
                print(canonical_json({"destination":str(args.destination),"format":args.format,
                    "readings":document["summary"]["reading_count"],
                    "report_sha256":document["report_sha256"],"notice":document["notice"]}))
            elif args.cmd=="backup-project":
                print(str(db.backup(args.destination)))
            elif args.cmd=="export":
                Path(args.destination).write_text(canonical_json(db.export_extraction(args.extraction_id)),encoding="utf-8")
                print("Exported",args.destination)
        return 0
    except (RefusedInput,LimitExceeded,ValueError,KeyError,OSError) as e:
        print(f"Operation refused: {type(e).__name__}",file=sys.stderr)
        return 2
    except RuntimeError as e:
        if type(e).__name__!="TesseractUnavailable":raise
        print(f"Operation not run: {e}",file=sys.stderr)
        return 3

if __name__=="__main__":
    raise SystemExit(main())
