"""Optional, offline Tesseract word-evidence preview for standalone P&ID reading.

Requires a separately installed local Tesseract executable and language data.
No network, model training, symbolic inference, plant state or host R1 writes.
OCR boxes refer to the rendered page and are unreviewed observations only.
"""
from __future__ import annotations
from math import ceil, isfinite
from hashlib import sha256
from ..api import canonical_json, sha256_hex, stable_id

MAX_PREVIEW_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_PAGES = 500
MAX_WORDS_PER_PAGE = 15000
MAX_PREVIEW_RESULT_BYTES = 8 * 1024 * 1024


def verify_ocr_preview(result: dict) -> bool:
    if not isinstance(result,dict):
        return False
    try:
        expected=sha256_hex(canonical_json({k:v for k,v in result.items() if k!='result_sha256'}).encode('utf-8'))
        return result.get('result_sha256')==expected and result.get('adapter') in ('standalone_ocr_preview_v2','standalone_ocr_preview_v3')
    except (ValueError,TypeError):
        return False


ENGINES = ('tesseract', 'rapidocr', 'auto')


def tesseract_available() -> bool:
    """True when a local Tesseract executable can be found (does not run OCR)."""
    try:
        import shutil
        import pytesseract
        cmd = pytesseract.pytesseract.tesseract_cmd
        return bool(shutil.which(cmd))
    except ImportError:
        return False


def rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def available_engines() -> list[str]:
    return [name for name, ok in (('tesseract', tesseract_available()), ('rapidocr', rapidocr_available())) if ok]


_RAPID = None
TILE_PX = 1200          # large drawings are read tile by tile so 5-8 pt lettering is not shrunk away
TILE_OVERLAP_PX = 150
_STATS: dict = {}
_HOOK: dict = {}       # {"tile": callable(done, total)} set for the duration of one ocr_pdf_preview call (one analysis runs at a time)


def reset_diagnostics() -> None:
    """Start a fresh per-run counter set (the OCR result dict itself stays unchanged and hash-stable)."""
    _STATS.clear()
    _STATS.update({"tiles_attempted": 0, "tiles_successful": 0, "tile_failures": 0, "tile_error_classes": [],
                   "pages_attempted": 0, "words_per_page": {}, "duplicate_words_merged": 0})


def last_diagnostics() -> dict:
    """Counters of the most recent ``ocr_pdf_preview`` call in this process (a copy)."""
    return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in _STATS.items()}


def _run_tile(engine, array):
    """One engine call. A failing tile is counted and skipped instead of silently ending the whole drawing."""
    _STATS["tiles_attempted"] = _STATS.get("tiles_attempted", 0) + 1
    try:
        found, _t = engine(array)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, caller decides whether the page is PARTIAL or FAILED
        _STATS["tile_failures"] = _STATS.get("tile_failures", 0) + 1
        name = type(exc).__name__
        if name not in _STATS.setdefault("tile_error_classes", []):
            _STATS["tile_error_classes"].append(name)
        return None
    _STATS["tiles_successful"] = _STATS.get("tiles_successful", 0) + 1
    return found or []
TILE_THRESHOLD_PX = 1500


def _rapid_engine():
    global _RAPID
    if _RAPID is None:
        from rapidocr_onnxruntime import RapidOCR
        # detector side limit large enough that a whole tile is processed at native resolution
        import os
        kwargs = dict(det_limit_side_len=1280, det_limit_type='max')
        threads = os.environ.get('PID_OCR_THREADS', '')
        if threads.isdigit() and int(threads) > 0:      # several OCR processes sharing a PC should not each use every core
            n = int(threads)
            kwargs.update(det_intra_op_num_threads=n, cls_intra_op_num_threads=n, rec_intra_op_num_threads=n)
        _RAPID = RapidOCR(**kwargs)
    return _RAPID


def _rapid_lines(image):
    """(quad, text, score) lines in image pixels; big images are tiled with overlap and de-duplicated."""
    import numpy as np
    engine = _rapid_engine()
    width, height = image.size
    if max(width, height) <= TILE_THRESHOLD_PX:
        found = _run_tile(engine, np.asarray(image))
        if found is None:
            raise RuntimeError("OCR_RUNTIME_EXCEPTION: the only OCR tile failed (" + ",".join(_STATS.get("tile_error_classes", [])) + ")")
        return list(found)
    lines = []
    step = TILE_PX - TILE_OVERLAP_PX
    ys = list(range(0, max(1, height - TILE_OVERLAP_PX), step))
    xs = list(range(0, max(1, width - TILE_OVERLAP_PX), step))
    total_tiles, done_tiles = len(ys) * len(xs), 0
    for y in ys:
        for x in xs:
            if _HOOK.get("tile"):
                _HOOK["tile"](done_tiles, total_tiles)        # reports progress and honours Cancel between tiles
            done_tiles += 1
            crop = image.crop((x, y, min(width, x + TILE_PX), min(height, y + TILE_PX)))
            found = _run_tile(engine, np.asarray(crop))
            for quad, text, conf in (found or []):
                lines.append(([[p[0] + x, p[1] + y] for p in quad], text, conf))
    if _STATS.get("tile_failures") and not _STATS.get("tiles_successful"):
        raise RuntimeError("OCR_RUNTIME_EXCEPTION: every OCR tile failed (" + ",".join(_STATS.get("tile_error_classes", [])) + ")")
    # overlap duplicates: same text with nearly the same box -> keep the higher score
    kept = []
    for quad, text, conf in sorted(lines, key=lambda l: -float(l[2])):
        cx = sum(p[0] for p in quad) / 4
        cy = sum(p[1] for p in quad) / 4
        if any(t == text and abs(cx - kx) < 12 and abs(cy - ky) < 12 for _q, t, _c, kx, ky in kept):
            continue
        kept.append((quad, text, conf, cx, cy))
    return [(q, t, c) for q, t, c, _x, _y in kept]


def _rapid_version() -> str:
    from importlib import metadata
    try:
        return 'rapidocr-onnxruntime ' + metadata.version('rapidocr-onnxruntime') + ' / onnxruntime ' + metadata.version('onnxruntime')
    except metadata.PackageNotFoundError:
        return 'rapidocr-onnxruntime unknown'


def _rapid_words(image) -> list[tuple[str, float, int, int, int, int, bool]]:
    """Pretrained offline PP-OCR line recognition split into word boxes.

    The detector returns text lines. Multi-token lines are divided into word
    boxes in proportion to character counts, which is an approximation that is
    recorded on each word as ``split=PROPORTIONAL_FROM_LINE``.
    """
    out = []
    for quad, text, conf in _rapid_lines(image):
        text = str(text).strip()
        if not text:
            continue
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        left, top = int(min(xs)), int(min(ys))
        wid, hei = int(max(xs)) - left, int(max(ys)) - top
        if wid < 1 or hei < 1:
            continue
        score = max(0.0, min(1.0, float(conf)))
        tokens = text.split()
        vertical = hei > 1.5 * wid and len(text) > 1
        if len(tokens) == 1 or vertical:
            out.append((text, score, left, top, wid, hei, False))
            continue
        total = len(text)
        cursor = 0
        for token in tokens:
            start = text.index(token, cursor)
            cursor = start + len(token)
            x0 = left + int(round(wid * start / total))
            x1 = left + int(round(wid * cursor / total))
            if x1 > x0:
                out.append((token, score, x0, top, x1 - x0, hei, True))
    return out


def _tesseract_words(image, timeout_seconds: int):
    import pytesseract
    from pytesseract import Output
    raw = pytesseract.image_to_data(image, output_type=Output.DICT, timeout=timeout_seconds)
    out = []
    for i, text in enumerate(raw['text']):
        text = str(text).strip()
        if not text:
            continue
        try:
            conf = max(0, min(100, float(raw['conf'][i]))) / 100.0
            if not isfinite(conf):
                conf = 0.0
        except (ValueError, TypeError):
            conf = 0.0
        out.append((text, conf, int(raw['left'][i]), int(raw['top'][i]), int(raw['width'][i]), int(raw['height'][i]), False))
    return out


def ocr_pdf_preview(pdf_bytes: bytes, *, pages: tuple[int,...] | None = None,
                    dpi: int | None = None, max_pixels: int = 12_000_000,
                    timeout_seconds: int = 30, engine: str = 'tesseract', cancel=None, progress=None) -> dict:
    if (dpi is not None and (type(dpi) is not int or not 72<=dpi<=300)) or type(max_pixels) is not int or not 1<=max_pixels<=12_000_000:
        raise ValueError('Unsupported OCR rendering profile')
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=300:
        raise ValueError('Unsupported OCR timeout')
    if engine not in ENGINES:
        raise ValueError('Unknown OCR engine')
    if engine == 'auto':
        if tesseract_available():
            engine = 'tesseract'
        elif rapidocr_available():
            engine = 'rapidocr'
        else:
            raise RuntimeError('No offline OCR engine is installed (need Tesseract or rapidocr-onnxruntime)')
    if not isinstance(pdf_bytes,bytes) or not pdf_bytes.startswith(b'%PDF-'):
        raise ValueError('OCR preview only accepts PDF bytes')
    if len(pdf_bytes)>MAX_PREVIEW_BYTES:
        raise ValueError('OCR preview exceeds the input byte budget')
    try:
        import pypdfium2 as pdfium
        import pdfplumber
        from io import BytesIO
        from .page_coordinates import frame_from_pdfplumber
    except ImportError as exc:
        raise RuntimeError('Optional offline PDFium/pdfplumber packages not available') from exc
    try:
        import pytesseract
    except ImportError as exc:
        if engine == 'tesseract':
            raise RuntimeError('Optional offline Tesseract OCR package (pytesseract) not available') from exc
        pytesseract = None
    if engine == 'rapidocr' and not rapidocr_available():
        raise RuntimeError('rapidocr-onnxruntime is not installed')
    reset_diagnostics()
    pdf=pdfium.PdfDocument(pdf_bytes)
    count=len(pdf)
    if not 1<=count<=MAX_PREVIEW_PAGES:
        raise ValueError('OCR page-count budget exceeded')
    chosen=tuple(range(1,count+1)) if pages is None else tuple(pages)
    if not chosen or len(chosen)!=len(set(chosen)) or any(type(n) is not int or not 1<=n<=count for n in chosen):
        raise ValueError('Unique, valid OCR page selection required')
    auto_dpi = dpi is None
    if dpi is None:
        # Default 180 dpi; RapidOCR gets up to 240 dpi (small drawing lettering needs the pixels)
        # as far as the pixel budget allows for the largest selected page.
        dpi=180
        if engine=='rapidocr':
            biggest=max(pdf[n-1].get_size()[0]*pdf[n-1].get_size()[1] for n in chosen)
            dpi=int(max(72,min(240,72*(max_pixels/biggest)**0.5*0.97)))
    document_sha=sha256(pdf_bytes).hexdigest()
    if engine == 'rapidocr':
        engine_version=_rapid_version()
    else:
        try:
            engine_version=str(pytesseract.get_tesseract_version())
        except pytesseract.TesseractNotFoundError:
            # A missing binary is reported by image_to_data below with a clear error;
            # this keeps injected/mocked word engines usable.
            engine_version='UNAVAILABLE'
    output=[]
    with pdfplumber.open(BytesIO(pdf_bytes)) as geometry_pdf:
      frames = {page_number: frame_from_pdfplumber(geometry_pdf.pages[page_number-1]) for page_number in chosen}
    for page_index, page_number in enumerate(chosen):
        if cancel is not None:
            cancel.check()
        if progress is not None:
            progress(page_index/len(chosen), f'OCR page {page_number} ({page_index+1} of {len(chosen)})')

        def _tile_hook(done, total, page_index=page_index, page_number=page_number):
            if cancel is not None:
                cancel.check()
            if progress is not None:
                progress((page_index+done/max(1, total))/len(chosen), f'OCR page {page_number}: text block {done+1} of {total}')
        _HOOK['tile']=_tile_hook
        page=pdf[page_number-1]
        width,height=page.get_size()
        frame=frames[page_number]
        if abs(frame.crop_width-width)>0.5 or abs(frame.crop_height-height)>0.5:
            raise ValueError('PDFium/pdfplumber rendered page geometry disagrees')
        scale=dpi/72.0
        if not all(isfinite(v) and v>0 for v in (width,height)):
            raise ValueError('Invalid OCR page dimensions')
        if ceil(width*scale)*ceil(height*scale)>max_pixels:
            if not auto_dpi:
                raise ValueError('OCR page render exceeds pixel budget')
            # automatic resolution: shrink this page's render just enough to fit the budget
            scale*=(max_pixels/(ceil(width*scale)*ceil(height*scale)))**0.5*0.97
        bitmap=page.render(scale=scale)
        image=bitmap.to_pil().convert('RGB')
        if engine == 'rapidocr':
            raw_words=_rapid_words(image)
        else:
            raw_words=_tesseract_words(image,timeout_seconds)
        words=[]
        by_id={}                       # word id -> index in ``words``
        for text,conf,left,top,wid,hei,split in raw_words:
            if wid<1 or hei<1:
                continue
            bbox={'x0':round(max(0,left/image.width),7),'y0':round(max(0,top/image.height),7),
                  'x1':round(min(1,(left+wid)/image.width),7),'y1':round(min(1,(top+hei)/image.height),7)}
            if bbox['x0']>=bbox['x1'] or bbox['y0']>=bbox['y1']:
                continue
            bbox=frame.bbox_to_media(bbox)
            word={'id':stable_id('ocr',document_sha,page_number,bbox,text),
                  'text':text,'page':page_number,'bbox':bbox,
                  'raw_ocr_score':round(conf,4),'review_state':'PROPOSED',
                  'engine':'local_rapidocr' if engine=='rapidocr' else 'local_tesseract'}
            if split:
                word['split']='PROPORTIONAL_FROM_LINE'
            # Two overlapping tiles can report the same drawn token inside two different lines; the proportional split then
            # yields two words with one identical box and text, hence one identical id. They are the same observation: keep
            # the higher raw engine score (never rescored) and count the merge, so the OCR result stays valid.
            seen=by_id.get(word['id'])
            if seen is not None:
                _STATS['duplicate_words_merged']=_STATS.get('duplicate_words_merged',0)+1
                if word['raw_ocr_score']>words[seen]['raw_ocr_score']:
                    words[seen]=word
                continue
            by_id[word['id']]=len(words)
            words.append(word)
            if len(words)>MAX_WORDS_PER_PAGE:
                raise ValueError('OCR word-count budget exceeded')
        _STATS['pages_attempted']=_STATS.get('pages_attempted',0)+1
        _STATS.setdefault('words_per_page',{})[page_number]=len(words)
        output.append({'page':page_number,'render_transform':frame.as_metadata(),'words':words,
                       'limitations':'OCR words are unreviewed text proposals; no symbol or plant interpretation follows.'})
    result={'adapter':'standalone_ocr_preview_v3',
            'source_sha256':document_sha,'algorithm':'rapidocr-onnx-line-ocr-v3' if engine=='rapidocr' else 'tesseract-word-ocr-v3', 'coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1',
            'engine_version':engine_version,'dpi':dpi,'selected_pages':list(chosen),
            'page_count':count,'pages':output,
            'limitations':'Requires a local offline OCR engine (Tesseract or RapidOCR/ONNX). Word boxes use MediaBox top-left normalized coordinates after CropBox mapping. Not a Worksheet R1 host extraction result; confidence is not calibrated accuracy.'}
    result['result_sha256']=sha256_hex(canonical_json(result).encode('utf-8'))
    if len(canonical_json(result).encode('utf-8'))>MAX_PREVIEW_RESULT_BYTES:
        raise ValueError('OCR result exceeds output budget')
    _HOOK.clear()
    return result


def validate_ocr_frame_for_pdf(result: dict, pdf_bytes: bytes) -> list[str]:
    """Reject mismatched/missing CropBox metadata when importing OCR evidence.

    Legacy v2 previews remain usable for uncropped pages, but cannot be safely
    imported as source coordinates for cropped PDFs.  V3 explicitly records
    the rotation-aware render-to-source transform for every page.
    """
    from io import BytesIO
    from hashlib import sha256
    import pdfplumber
    from .page_coordinates import frame_from_pdfplumber
    errors=[]
    if not verify_ocr_preview(result) or result.get('source_sha256') != sha256(pdf_bytes).hexdigest():
        return ['OCR source checksum does not match original PDF']
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
            for entry in result.get('pages',[]):
                index=entry.get('page')
                if type(index) is not int or not 1<=index<=len(doc.pages):
                    errors.append('Invalid OCR page selection')
                    continue
                frame=frame_from_pdfplumber(doc.pages[index-1])
                if result['adapter']=='standalone_ocr_preview_v3':
                    if result.get('coordinate_frame')!='PDFPLUMBER_MEDIA_NORMALIZED_V1' or entry.get('render_transform')!=frame.as_metadata():
                        errors.append(f'Page {index} OCR coordinate transform differs from original PDF')
                        continue
                    for word in entry.get('words',[]):
                        b=word.get('bbox',{})
                        try:
                            frame.media_to_render(b['x0'],b['y0'])
                            frame.media_to_render(b['x1'],b['y1'])
                        except (KeyError,TypeError,ValueError):
                            errors.append(f'Page {index} OCR word lies outside rendered CropBox')
                            break
                else:
                    if (abs(frame.crop_x0)>.001 or abs(frame.crop_top)>.001 or
                        abs(frame.crop_width-frame.media_width)>.001 or
                        abs(frame.crop_height-frame.media_height)>.001):
                        errors.append(f'Legacy OCR v2 on cropped page {index} lacks the source transform')
    except (OSError,TypeError,ValueError,IndexError) as exc:
        errors.append('Failed to inspect PDF geometry for OCR evidence')
    return errors
