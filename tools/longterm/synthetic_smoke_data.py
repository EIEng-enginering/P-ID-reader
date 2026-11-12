"""Synthetic TRAIN-only crops for checking training machinery, never accuracy."""
import argparse,hashlib,json,random
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--count',type=int,default=12);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True);rng=random.Random(121126);items=[]
try:font=ImageFont.truetype('DejaVuSans.ttf',28)
except OSError:font=ImageFont.load_default(size=28)
for i in range(a.count):
    text=f"{rng.choice(['HPF','GHS','DR','PC','WP'])}-{rng.randint(10000,99999)}-{rng.choice(['33.4','114.3','168.3'])}-C3S-{rng.choice(['40','80','XXS'])}"
    image=Image.new('RGB',(640,64),'white');ImageDraw.Draw(image).text((8,12),text,font=font,fill='black')
    path=a.output/f'crop-{i}.png';image.save(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
    items.append(dict(id=f'synthetic-{i}',split='TRAIN',family_id='SYNTHETIC_SMOKE_V1',source_sha256=sha,
                      origin='SYNTHETIC',text=text,image_path=path.name,image_sha256=sha))
(a.output/'dataset.json').write_text(json.dumps(dict(schema='pid-longterm-crops-v1',items=items),indent=2))
print(a.output/'dataset.json')
