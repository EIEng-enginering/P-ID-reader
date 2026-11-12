"""Optional high-resolution, local-only OCR of explicit engineering review regions.

This is a bounded supplemental source of observations, not an automatic fix to
model output and never a source of accepted plant facts. The regions are
MediaBox-normalized and transformation-aware for CropBox and rotation.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import math
from ..api import stable_id
from ..formats.page_coordinates import frame_from_pdfplumber
from .wp123_recovery import _box, _overlap_area, _area

MAX_ROIS=48
MAX_ROI_PIXELS=3_500_000


class TesseractUnavailable(RuntimeError):
    """The optional Tesseract program is not installed or not on PATH (the Python package alone is not enough)."""


def tesseract_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def supplemental_ocr(pdf_bytes:bytes, roi_manifest: list[dict], *, dpi:int=290, timeout_seconds:int=20) -> list[dict]:
    if not isinstance(pdf_bytes,bytes) or not pdf_bytes.startswith(b'%PDF-') or len(pdf_bytes)>16*1024*1024:
        raise ValueError('Invalid source PDF')
    if type(dpi) is not int or not 120<=dpi<=450 or type(timeout_seconds) is not int or not 1<=timeout_seconds<=60:
        raise ValueError('Unsupported OCR rendering budget')
    if not isinstance(roi_manifest,list) or len(roi_manifest)>MAX_ROIS:
        raise ValueError('Too many OCR regions')
    import pypdfium2
    import pdfplumber
    import pytesseract
    from PIL import ImageEnhance
    source=sha256(pdf_bytes).hexdigest()
    result=[]
    pdf=pypdfium2.PdfDocument(pdf_bytes)
    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        frames=[frame_from_pdfplumber(p) for p in doc.pages]
    try:
        for i,roi in enumerate(roi_manifest):
            if not isinstance(roi,dict) or type(roi.get('page')) is not int or not 1<=roi['page']<=len(pdf):
                raise ValueError('Invalid OCR ROI page')
            b=_box(roi['bbox']);frame=frames[roi['page']-1]
            cropped=frame.media_bbox_to_render_clipped(b)
            if cropped is None:raise ValueError('Region outside visible PDF CropBox')
            page=pdf[roi['page']-1]
            width,height=page.get_size()
            if abs(width-frame.crop_width)>.5 or abs(height-frame.crop_height)>.5:
                raise ValueError('PDF render coordinates do not agree with extracted geometry')
            # Render PDFium page, then crop. Limit whole-page render memory.
            scale=dpi/72
            if math.ceil(width*scale)*math.ceil(height*scale)>20_000_000:
                scale*=math.sqrt(20_000_000/(math.ceil(width*scale)*math.ceil(height*scale)))*.95
            image=page.render(scale=scale).to_pil().convert('L')
            px=[int(round(v*image.size[j%2])) for j,v in enumerate((cropped['x0'],cropped['y0'],cropped['x1'],cropped['y1']))]
            if px[2]<=px[0] or px[3]<=px[1]:raise ValueError('Empty OCR region')
            raw=image.crop(tuple(px))
            if raw.width*raw.height>MAX_ROI_PIXELS:
                ratio=math.sqrt(MAX_ROI_PIXELS/(raw.width*raw.height))*.98
                raw=raw.resize((max(1,int(raw.width*ratio)),max(1,int(raw.height*ratio))))
            # Tiny CAD labels benefit from enlargement of the *cropped region*,
            # not wasteful enlargement of the entire drawing page.
            from PIL import Image
            factor=min(3.0,math.sqrt(MAX_ROI_PIXELS/max(1,raw.width*raw.height))*.95)
            if factor>1.15:
                raw=raw.resize((int(raw.width*factor),int(raw.height*factor)),Image.Resampling.LANCZOS)
            raw=ImageEnhance.Contrast(raw).enhance(1.8)
            if not tesseract_available():
                raise TesseractUnavailable('TESSERACT_NOT_INSTALLED: the optional high-resolution region re-read needs the Tesseract program on PATH; '
                                       'nothing was read and no result was invented')
            try:
                for psm in (6,11):
                    data=pytesseract.image_to_data(raw,config=f'--psm {psm}',timeout=timeout_seconds,
                                                    output_type=pytesseract.Output.DICT)
                    for j,text in enumerate(data['text']):
                        text=str(text).strip()
                        if not text or len(text)>100:continue
                        try: score=max(0.,min(1.,float(data['conf'][j])/100))
                        except (ValueError,TypeError):score=0.
                        left=float(data['left'][j]);top=float(data['top'][j]);w=float(data['width'][j]);h=float(data['height'][j])
                        if min(w,h)<=0:continue
                        rb={'x0':max(0.,min(1.,(px[0]+left* (px[2]-px[0])/raw.width)/image.width)),
                            'y0':max(0.,min(1.,(px[1]+top* (px[3]-px[1])/raw.height)/image.height)),
                            'x1':max(0.,min(1.,(px[0]+(left+w)*(px[2]-px[0])/raw.width)/image.width)),
                            'y1':max(0.,min(1.,(px[1]+(top+h)*(px[3]-px[1])/raw.height)/image.height))}
                        if rb['x1']<=rb['x0'] or rb['y1']<=rb['y0']:continue
                        mb=frame.bbox_to_media(rb)
                        result.append({'id':stable_id('wp123-roi-ocr',source,roi['page'],mb,text),
                            'text':text,'page':roi['page'],'bbox':mb,'raw_score':round(score,4),
                            'engine':'local_tesseract_roi','roi_id':str(roi.get('id',i)),
                            'review_state':'PROPOSED_UNVERIFIED'})
            finally:
                image.close()
    finally:
        pdf.close()
    # PSM6 and PSM11 often return the same word. Keep highest-scoring near
    # duplicate, while retaining competing readings rather than choosing one.
    unique=[]
    for row in sorted(result,key=lambda r:(-r['raw_score'],r['id'])):
        if any(q['text'].upper()==row['text'].upper() and q['page']==row['page'] and
                _overlap_area(q['bbox'],row['bbox']) >= .65*min(_area(q['bbox']),_area(row['bbox'])) for q in unique):
            continue
        unique.append(row)
    return sorted(unique,key=lambda r:(r['page'],r['bbox']['y0'],r['bbox']['x0'],r['id']))
