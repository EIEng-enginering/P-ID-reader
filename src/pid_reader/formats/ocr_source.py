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


def ocr_pdf_preview(pdf_bytes: bytes, *, pages: tuple[int,...] | None = None,
                    dpi: int = 180, max_pixels: int = 12_000_000,
                    timeout_seconds: int = 30) -> dict:
    if type(dpi) is not int or not 72<=dpi<=300 or type(max_pixels) is not int or not 1<=max_pixels<=12_000_000:
        raise ValueError('Unsupported OCR rendering profile')
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=300:
        raise ValueError('Unsupported OCR timeout')
    if not isinstance(pdf_bytes,bytes) or not pdf_bytes.startswith(b'%PDF-'):
        raise ValueError('OCR preview only accepts PDF bytes')
    if len(pdf_bytes)>MAX_PREVIEW_BYTES:
        raise ValueError('OCR preview exceeds the input byte budget')
    try:
        import pypdfium2 as pdfium
        import pdfplumber
        from io import BytesIO
        from .page_coordinates import frame_from_pdfplumber
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise RuntimeError('Optional offline PDFium/Tesseract OCR packages not available') from exc
    pdf=pdfium.PdfDocument(pdf_bytes)
    count=len(pdf)
    if not 1<=count<=MAX_PREVIEW_PAGES:
        raise ValueError('OCR page-count budget exceeded')
    chosen=tuple(range(1,count+1)) if pages is None else tuple(pages)
    if not chosen or len(chosen)!=len(set(chosen)) or any(type(n) is not int or not 1<=n<=count for n in chosen):
        raise ValueError('Unique, valid OCR page selection required')
    document_sha=sha256(pdf_bytes).hexdigest()
    engine_version=str(pytesseract.get_tesseract_version())
    output=[]
    with pdfplumber.open(BytesIO(pdf_bytes)) as geometry_pdf:
      frames = {page_number: frame_from_pdfplumber(geometry_pdf.pages[page_number-1]) for page_number in chosen}
    for page_number in chosen:
        page=pdf[page_number-1]
        width,height=page.get_size()
        frame=frames[page_number]
        if abs(frame.crop_width-width)>0.5 or abs(frame.crop_height-height)>0.5:
            raise ValueError('PDFium/pdfplumber rendered page geometry disagrees')
        scale=dpi/72.0
        if not all(isfinite(v) and v>0 for v in (width,height)):
            raise ValueError('Invalid OCR page dimensions')
        if ceil(width*scale)*ceil(height*scale)>max_pixels:
            raise ValueError('OCR page render exceeds pixel budget')
        bitmap=page.render(scale=scale)
        image=bitmap.to_pil().convert('RGB')
        raw=pytesseract.image_to_data(image,output_type=Output.DICT,timeout=timeout_seconds)
        words=[]
        for i,text in enumerate(raw['text']):
            text=str(text).strip()
            if not text:
                continue
            try:
                conf=max(0,min(100,float(raw['conf'][i])))/100.0
                if not isfinite(conf): conf=0.0
            except (ValueError,TypeError):
                conf=0.0
            left=int(raw['left'][i]);top=int(raw['top'][i]);wid=int(raw['width'][i]);hei=int(raw['height'][i])
            if wid<1 or hei<1:
                continue
            bbox={'x0':round(max(0,left/image.width),7),'y0':round(max(0,top/image.height),7),
                  'x1':round(min(1,(left+wid)/image.width),7),'y1':round(min(1,(top+hei)/image.height),7)}
            if bbox['x0']>=bbox['x1'] or bbox['y0']>=bbox['y1']:
                continue
            bbox=frame.bbox_to_media(bbox)
            words.append({'id':stable_id('ocr',document_sha,page_number,bbox,text),
                          'text':text,'page':page_number,'bbox':bbox,
                          'raw_ocr_score':round(conf,4),'review_state':'PROPOSED',
                          'engine':'local_tesseract'})
            if len(words)>MAX_WORDS_PER_PAGE:
                raise ValueError('OCR word-count budget exceeded')
        output.append({'page':page_number,'render_transform':frame.as_metadata(),'words':words,
                       'limitations':'OCR words are unreviewed text proposals; no symbol or plant interpretation follows.'})
    result={'adapter':'standalone_ocr_preview_v3',
            'source_sha256':document_sha,'algorithm':'tesseract-word-ocr-v3', 'coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1',
            'engine_version':engine_version,'dpi':dpi,'selected_pages':list(chosen),
            'page_count':count,'pages':output,
            'limitations':'Requires local Tesseract. Word boxes use MediaBox top-left normalized coordinates after CropBox mapping. Not a Worksheet R1 host extraction result; confidence is not calibrated accuracy.'}
    result['result_sha256']=sha256_hex(canonical_json(result).encode('utf-8'))
    if len(canonical_json(result).encode('utf-8'))>MAX_PREVIEW_RESULT_BYTES:
        raise ValueError('OCR result exceeds output budget')
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
