"""Replay supplied evidence. Optional actual OCR experiment, not ground truth."""
from pathlib import Path
import argparse
import importlib.util
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pid_reader.engineering.wp456.pipeline import build,export
from pid_reader.engineering.wp456.common import digest
from pid_reader.engineering.wp456.ocr import reread
from pid_reader.engineering.wp456.readings import propose_regions


def read(path):return json.loads(path.read_text(encoding='utf8'))


def replay(output,with_ocr=False):
    evidence=ROOT/'examples'/'wp456'/'evidence'/'s418'
    upstream=read(evidence/'wp123_result.json');words=read(evidence/'words.json')
    geometry=read(evidence/'geometry.json');sizes={int(k):v for k,v in read(evidence/'page_sizes.json').items()}
    before=build(upstream,words,page_sizes=sizes,segments=geometry['segments'])
    export(before,output/'baseline_replay')
    summary={'source_sha256':upstream['source_sha256'],'baseline_readings':len(upstream['readings']),
             'wp04_readings':len(before['wp04']['readings']),
             'document_fields_before':len(upstream['document_fields']),
             'document_fields_after':len(before['wp04']['document_fields']),
             'symbol_links_proposed':sum(a['state']=='ASSOCIATION_PROPOSED' for a in before['wp05']['associations']),
             'geometry_edges':len(before['wp06']['graph']['edges']),
             'geometry_line_kinds':sorted({e['line_kind'] for e in before['wp06']['graph']['edges']}),
             'accuracy_status':'NOT_RUN_NO_APPROVED_REFERENCE','new_ocr_status':'NOT_REQUESTED'}
    if with_ocr:
        # This replay renderer is intentionally limited to the verified S418
        # unrotated/uncropped fixture. The host adapter uses PageFrame instead.
        import pypdfium2
        from PIL import Image,ImageEnhance
        pdf_path=evidence/'S418_cer_455653_p003.pdf'
        def renderer(roi):
            pdf=pypdfium2.PdfDocument(str(pdf_path))
            try:
                pg=pdf[roi['page']-1]
                if tuple(round(x) for x in pg.get_size())!=(1222,790):raise ValueError('Replay renderer only supports supplied S418 fixture')
                bitmap=pg.render(scale=3.5);image=bitmap.to_pil().convert('L')
                try:
                    b=roi['bbox'];iw,ih=image.size
                    x0,y0,x1,y1=[round(v*n) for v,n in zip((b['x0'],b['y0'],b['x1'],b['y1']),(iw,ih,iw,ih))]
                    crop=image.crop((x0,y0,x1,y1));factor=min(3.,(3_300_000/(crop.width*crop.height))**.5)
                    resized=crop.resize((int(crop.width*factor),int(crop.height*factor)),Image.Resampling.LANCZOS);crop.close()
                    enhanced=ImageEnhance.Contrast(resized).enhance(1.7);resized.close()
                finally:image.close();bitmap.close()
                def mapper(b):return {'x0':(x0+b['x0']*(x1-x0))/iw,'x1':(x0+b['x1']*(x1-x0))/iw,
                                      'y0':(y0+b['y0']*(y1-y0))/ih,'y1':(y0+b['y1']*(y1-y0))/ih}
                return enhanced,mapper
            finally:pdf.close()
        # Balance bubbles and suspect line crops; do not spend the entire
        # bounded run on the first eight circles in drawing order.
        regions=propose_regions(words,upstream['bubble_candidates'])['regions']
        buckets={reason:[r for r in regions if r['reason']==reason] for reason in
                 ('BUBBLE_INTERIOR','LINE_NUMBER_REREAD','TAG_REREAD','TITLE_FIELD_REREAD')}
        balanced=[]
        while any(buckets.values()):
            for rows in buckets.values():
                if rows:balanced.append(rows.pop(0))
        ocr=reread(balanced,source_sha256=upstream['source_sha256'],renderer=renderer,
                   max_regions=8,total_seconds=60,call_seconds=5,rotations=(0,90,270),psms=(6,11))
        (output/'ocr_experiment.json').write_text(json.dumps(ocr,indent=2)+'\n')
        spec=importlib.util.spec_from_file_location('reference_wp123',ROOT/'examples'/'wp456'/'evidence'/'reference_wp123_recovery.py')
        ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
        combined=words+ocr['words']
        dets=[{k:v for k,v in d.items() if k not in ('eligibility','filter_reason')} for d in upstream['detector_decisions']]
        recovered=ref.recover_wp123(pdf_path.read_bytes(),combined,dets,profile='auto',bubbles=upstream['bubble_candidates'])
        after=build(recovered,combined,page_sizes=sizes,segments=geometry['segments']);export(after,output/'ocr_experiment')
        summary['new_ocr_status']=ocr['status'];summary['new_ocr_words']=len(ocr['words']);summary['new_ocr_seconds']=ocr['elapsed_seconds']
        summary['experimental_readings']=len(after['wp04']['readings'])
        summary['line_alternatives']=[r for r in after['wp04']['line_reviews'] if r['alternatives']]
        summary['bubble_options']=[r for r in after['wp04']['bubble_readings'] if r['options']]
    (output/'replay_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--with-ocr',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True);replay(args.output,args.with_ocr)
