from __future__ import annotations
from io import BytesIO
import pytest


@pytest.fixture(autouse=True)
def _r5_settings_isolated(tmp_path_factory, monkeypatch):
    """The R5 switches may be stored per user; tests must never read or write the real settings file."""
    monkeypatch.setenv("PID_R5_SETTINGS", str(tmp_path_factory.mktemp("r5set") / "r5_features.json"))


@pytest.fixture(autouse=True)
def _tr1_isolated(tmp_path_factory, monkeypatch):
    """TR1 switches default OFF; a test must never inherit the developer's switches or touch the real TR1 data folder."""
    for name in ("PIDLAB_SYMBOL_FRCNN_TR1", "PIDLAB_SYMBOL_CATALOGUE_TR1", "PIDLAB_CORRECTION_QUEUE_TR1", "PIDLAB_TRAINING_BATCH_TR1",
                 "PIDLAB_LOCAL_TRAINER_TR1", "PIDLAB_MODEL_REGISTRY_TR1", "PIDLAB_TAG_ASSIGN_R3", "PIDLAB_GRAPH_CONSERVATIVE_R3", "PIDLAB_FINE_CLASS_R3", "PIDLAB_TILE_MERGE_R3", "PIDLAB_TR1_PYTHON", "PIDLAB_TR1_MODEL_DIR", "PIDLAB_TR1_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    base = tmp_path_factory.mktemp("tr1")
    monkeypatch.setenv("PIDLAB_TR1_SETTINGS", str(base / "tr1_features.json"))
    monkeypatch.setenv("PIDLAB_TR1_HOME", str(base / "home"))


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
