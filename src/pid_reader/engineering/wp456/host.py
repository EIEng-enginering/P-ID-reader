"""Optional adapter against the supplied c0908b9 WP123 integration snapshot.

Imports the host only inside functions. Core modules need only Python stdlib.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import math
import os
from pathlib import Path
from .common import box, seal
from .pipeline import build
from .readings import propose_regions


def store_path():
    override=os.environ.get('PID_WP456_STORE')
    if override: return Path(override)
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local'/'share')/'PIDReader'/'wp456'/'review.sqlite'


def dimensions(pdf_bytes):
    import pdfplumber
    from ...formats.page_coordinates import frame_from_pdfplumber
    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        # The evidence frame is the host PageFrame media frame, i.e. pdfplumber's rotation-aware top-left view of the page.
        # (The pack used the unrotated MediaBox, which swaps width and height on 90/270 degree pages and distorts the
        # physical-distance rules of the associations.)
        out={}
        for i,p in enumerate(doc.pages):
            f=frame_from_pdfplumber(p)
            out[i+1]=(f.media_width,f.media_height)
        return out


def pdf_renderer(pdf_bytes):
    """Frame-aware ROI renderer. Rotation mapping is delegated to host PageFrame."""
    def render(roi):
        import pdfplumber
        import pypdfium2
        from PIL import Image, ImageEnhance
        from ...formats.page_coordinates import frame_from_pdfplumber
        with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
            if not 1<=roi['page']<=len(doc.pages): raise ValueError('Invalid page')
            frame=frame_from_pdfplumber(doc.pages[roi['page']-1])
        rb=frame.media_bbox_to_render_clipped(box(roi['bbox']))
        if rb is None: raise ValueError('Selected region lies outside CropBox')
        pdf=pypdfium2.PdfDocument(pdf_bytes)
        try:
            pg=pdf[roi['page']-1]; width,height=pg.get_size()
            if abs(width-frame.crop_width)>.5 or abs(height-frame.crop_height)>.5:
                raise ValueError('Host PDF frame disagrees with raster dimensions')
            scale=min(4.,math.sqrt(16_000_000/(width*height))*.98)
            bitmap=pg.render(scale=scale)
            image=bitmap.to_pil().convert('L')
            try:
                # Actual rounded crop boundaries must be used in inverse map.
                x0=max(0,math.floor(rb['x0']*image.width)); x1=min(image.width,math.ceil(rb['x1']*image.width))
                y0=max(0,math.floor(rb['y0']*image.height)); y1=min(image.height,math.ceil(rb['y1']*image.height))
                if x0>=x1 or y0>=y1: raise ValueError('Empty crop')
                iw,ih=image.size
                crop=image.crop((x0,y0,x1,y1))
            finally:
                image.close(); bitmap.close()
            factor=min(3.,math.sqrt(3_300_000/(crop.width*crop.height)))
            resized=crop.resize((max(1,int(crop.width*factor)),max(1,int(crop.height*factor))),Image.Resampling.LANCZOS)
            crop.close()
            enhanced=ImageEnhance.Contrast(resized).enhance(1.7); resized.close()
            def mapper(b):
                return frame.bbox_to_media({'x0':(x0+b['x0']*(x1-x0))/iw,'y0':(y0+b['y0']*(y1-y0))/ih,
                                            'x1':(x0+b['x1']*(x1-x0))/iw,'y1':(y0+b['y1']*(y1-y0))/ih})
            return enhanced,mapper
        finally:
            pdf.close()
    return render


def analyse(pdf_bytes,page,words,detections,*,scan_bubbles=False,profile='auto',
            reread_enabled=False,selected=None,cancelled=lambda:False,segments=None,ports=None,junctions=None,symbol_evidence=None):
    from ..wp123_session import analyse_page
    from ..wp123_recovery import recover_wp123
    from .ocr import reread
    if any(w['page']!=page for w in words) or any(d['page']!=page for d in detections):
        raise ValueError('Host page adapter requires evidence from the current page only')
    initial=analyse_page(pdf_bytes,page,words,detections,scan_bubbles=scan_bubbles,profile=profile)
    combined=list(words); ocr_status={'status':'NOT_REQUESTED','words':[]}
    if reread_enabled:
        if selected and selected['page']!=page: raise ValueError('Selection belongs to another page')
        rois=propose_regions(words,initial['bubble_candidates'],selected=selected)
        ocr_status=reread(rois['regions'],source_sha256=sha256(pdf_bytes).hexdigest(),
                          renderer=pdf_renderer(pdf_bytes),cancelled=cancelled)
        combined+=ocr_status['words']
        # Re-scan circles after OCR where requested; raw evidence is retained.
        initial=analyse_page(pdf_bytes,page,combined,detections,scan_bubbles=scan_bubbles,profile=profile)
    result=build(initial,combined,page_sizes=dimensions(pdf_bytes),segments=segments,ports=ports,junctions=junctions,symbol_evidence=symbol_evidence)
    result['ocr_run']={k:v for k,v in ocr_status.items() if k!='words'}
    result['ocr_evidence']=combined
    return seal(result)


def geometry_from_project(db, extraction_id, page, source_sha256):
    """Read existing centreline evidence, else raw strokes; never classify service.

    This read-only adapter is deliberately limited to table shapes present in
    the supplied v13 snapshot. Unrecognised schema fails visibly.
    """
    import json
    choices=(('raster_centreline_analysis','centrelines'),('raster_analysis','stroke_candidates'))
    for table,key in choices:
        row=db.db.execute('SELECT result_json FROM '+table+' WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1',
                          (extraction_id,)).fetchone()
        if not row: continue
        doc=json.loads(row[0])
        if doc.get('source_sha256')!=source_sha256: raise ValueError('Stored geometry belongs to another PDF')
        if doc.get('coordinate_frame')!='PDFPLUMBER_MEDIA_NORMALIZED_V1':
            raise ValueError('Unsupported geometry coordinate frame')
        result=[]
        for r in doc.get(key,[]):
            if r['page']!=page: continue
            a,b=r['endpoints']
            result.append({'id':r['id'],'page':page,'a':a,'b':b,'line_kind':'UNKNOWN',
                           'evidence_ids':r.get('source_stroke_ids',[r['id']]),'origin':table})
        if result: return result
    return []
