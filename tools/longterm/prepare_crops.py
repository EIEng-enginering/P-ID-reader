"""Freeze reviewed/draft source crops into a dataset; never invent transcriptions."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from pid_reader.engineering.wp08.render import Renderer
from pid_reader.engineering.longterm.data import sha
p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);p.add_argument('--annotations',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():p.error('Choose a new versioned dataset directory')
annotations=json.loads(a.annotations.read_text(encoding='utf8'));fingerprint=sha(a.pdf)
if annotations['source_sha256']!=fingerprint:p.error('Source hash mismatch')
items=annotations['items']
if not 1<=len(items)<=1000:p.error('Crop count budget is 1..1000')
a.output.mkdir(parents=True);pdf=a.pdf.read_bytes();rows=[]
for i,item in enumerate(items):
    with Renderer(pdf,item['page']) as renderer:image,actual,metadata=renderer.render(item['bbox'],scale=6)
    path=a.output/f'crop-{i:04d}.png'
    try:image.save(path)
    finally:image.close()
    # A draft remains a draft and is refused by the supervised trainer.
    rows.append(dict(item,image_path=path.name,image_sha256=sha(path),source_path=str(a.pdf.resolve()),source_sha256=fingerprint,
                     origin='HUMAN_SOURCE_PIXELS',bbox=actual,coordinate_frame='MEDIA_NORMALIZED_TOP_LEFT',
                     review_status=item.get('review_status','DRAFT_ANALYST_NOT_INDEPENDENT'),render=metadata))
(a.output/'dataset.json').write_text(json.dumps(dict(schema='pid-longterm-crops-v1',items=rows),indent=2))
print(a.output/'dataset.json')
