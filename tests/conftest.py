from __future__ import annotations
from io import BytesIO
import pytest

@pytest.fixture
def synthetic_pdf():
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.pagesizes import A3
    b=BytesIO()
    c=Canvas(b,pagesize=A3)
    w,h=A3
    c.setTitle("Synthetic P&ID demonstration - not real plant data")
    c.setLineWidth(1.5)
    c.setFont("Helvetica",12)
    c.drawString(70,h-75,"SYNTHETIC P&ID - TEST DRAWING")
    c.drawString(70,h-105,"V-101")
    c.drawString(220,h-105,"PT-101")
    c.drawString(390,h-105,"XV-201")
    c.drawString(490,h-105,"P-102A")
    c.line(60,h-190,180,h-190)
    c.line(180,h-190,260,h-190)
    c.line(260,h-190,370,h-190)
    c.line(180,h-190,180,h-260)
    c.line(270,h-265,370,h-265)
    c.drawString(60,h-315,"Notes: This is a synthetic fixture only")
    c.showPage();c.save()
    return b.getvalue()

@pytest.fixture
def raster_pdf():
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    b=BytesIO(); c=Canvas(b,pagesize=(400,300))
    c.drawImage(ImageReader(Image.new("RGB",(64,64),"white")),30,30,width=100,height=100)
    c.showPage();c.save()
    return b.getvalue()
