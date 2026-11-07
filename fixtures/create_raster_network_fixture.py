"""Generate a synthetic scan-only testing PDF, not a labelled industrial P&ID."""
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

TARGET = Path(__file__).with_name('synthetic_raster_network_context.pdf')
image=Image.new('RGB',(1050,700),'white')
d=ImageDraw.Draw(image)
# Process-looking geometry is deliberately unlabelled and unverified.
d.line([(80,150),(340,150)],fill='black',width=3)
d.line([(215,150),(215,255)],fill='black',width=3)
d.line([(405,155),(595,155)],fill='black',width=3)
d.line([(480,70),(480,245)],fill='black',width=3)
d.line([(680,160),(840,160)],fill='black',width=3)
# Near-frame line and line below an annotation in the title-block area.
d.line([(4,4),(1040,4)],fill='black',width=3)
d.line([(700,358),(890,358)],fill='black',width=3)
try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',36)
except OSError:font=ImageFont.load_default()
d.text((695,310),'PT-101',font=font,fill='black')
# Outlined bowtie: two end bases and four diagonals to centre.
d.line([(805,480),(805,535)],fill='black',width=3)
d.line([(865,480),(865,535)],fill='black',width=3)
for p in [(805,480),(805,535),(865,480),(865,535)]:
    d.line([p,(835,507)],fill='black',width=3)

bio=BytesIO();image.save(bio,format='PNG');bio.seek(0)
c=Canvas(str(TARGET),pagesize=(1050,700),pageCompression=1)
c.drawImage(ImageReader(bio),0,0,width=1050,height=700)
c.showPage();c.save()
print(TARGET)
