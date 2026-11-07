"""Generate synthetic public-domain project fixtures; no real facility drawing used."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import json
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A3
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/"fixtures"
FIX.mkdir(exist_ok=True)


def vector_fixture():
    destination=FIX/"synthetic_pid_vector.pdf"
    c=Canvas(str(destination),pagesize=A3)
    width,height=A3
    c.setTitle("Synthetic P&ID Reader Development Fixture")
    c.setLineWidth(1.3)
    c.setFont("Helvetica-Bold",14)
    c.drawString(40,height-40,"SYNTHETIC P&ID / NOT AN OPERATING FACILITY")
    c.setFont("Helvetica",12)
    c.roundRect(135,height-230,180,65,15,stroke=1,fill=0)
    c.drawString(190,height-199,"V-101")
    # instrument bubble with connected dashed signal: visual only, do not assume a valid loop
    c.circle(285,height-115,19,stroke=1,fill=0)
    c.drawCentredString(285,height-119,"PT-101")
    c.setDash(4,3)
    c.line(285,height-134,285,height-165)
    c.setDash([])
    # process strokes and a line branch
    c.line(40,height-197,135,height-197)
    c.line(315,height-197,520,height-197)
    c.line(390,height-197,390,height-270)
    c.line(390,height-270,450,height-270)
    c.line(520,height-197,630,height-197)
    c.line(650,height-197,780,height-197)
    # valve with two triangles
    p=c.beginPath();p.moveTo(630,height-189);p.lineTo(650,height-205);p.lineTo(630,height-205);p.close()
    c.drawPath(p,stroke=1,fill=0)
    p=c.beginPath();p.moveTo(650,height-189);p.lineTo(630,height-205);p.lineTo(650,height-205);p.close()
    c.drawPath(p,stroke=1,fill=0)
    c.drawCentredString(640,height-222,"XV-201")
    c.drawString(730,height-180,'6"-P-1501-A1A')
    c.drawString(380,height-295,"P-102A")
    c.drawString(40,height-330,"NOTE 1: This drawing is a synthetic benchmark fixture only.")
    # Title block
    c.rect(450,45,350,100,stroke=1,fill=0)
    c.line(450,82,800,82)
    c.drawString(461,115,"DRAWING: SYN-PID-001")
    c.drawString(461,94,"REV: A")
    c.drawString(461,60,"SHEET: 1 OF 1")
    c.showPage();c.save()
    return destination


def raster_fixture():
    destination=FIX/"synthetic_pid_raster.pdf"
    im=Image.new("RGB",(900,500),"white")
    draw=ImageDraw.Draw(im)
    draw.rectangle((100,170,480,280),outline="black",width=4)
    draw.text((225,210),"V-101",fill="black")
    draw.line((25,220,100,220),fill="black",width=4)
    draw.line((480,220,800,220),fill="black",width=4)
    draw.text((120,40),"SYNTHETIC SCANNED DRAWING",fill="black")
    c=Canvas(str(destination),pagesize=A3)
    c.drawImage(ImageReader(im),40,280,width=760,height=420)
    c.showPage();c.save()
    return destination

if __name__=="__main__":
    v=vector_fixture();r=raster_fixture()
    (FIX/"synthetic_gold_intent.json").write_text(json.dumps({
        "fixture":"synthetic_pid_vector.pdf", "purpose":"synthetic development demonstrations only",
        "expected_visible_tags":["V-101","PT-101","XV-201","P-102A"],
        "known_limitations":"Visual valve geometry, loops and actual physical connectivity require specialist algorithms; do not assume the initial reader will infer them.",
    },indent=2),encoding="utf-8")
    print(v,r)
