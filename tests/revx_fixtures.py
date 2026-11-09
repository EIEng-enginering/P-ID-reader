"""Original-geometry synthetic PDFs for the Rev X test-suite (no client or standards content)."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

W, H = 1190.0, 842.0  # A3 landscape in points


def _lines(c, count: int) -> None:
    """Dense plain vector strokes (stand-in for outlined lettering and pipework)."""
    c.setLineWidth(0.4)
    for i in range(count):
        x = 40 + (i % 60) * 17
        y = 120 + (i // 60) * 9
        c.line(x, y, x + 9, y + (3 if i % 2 else 0))


def sheet_pdf(*, dense: int = 0, title: bool = True, notes: bool = False, table: bool = False, border: bool = False,
              raster: bool = False, body_words: int = 0, rotate: int = 0, crop: tuple | None = None,
              revision: bool = False) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H), pageCompression=0, invariant=1)
    if border:
        c.setLineWidth(1)
        c.line(20, 20, W - 20, 20)
        c.line(20, H - 20, W - 20, H - 20)
        c.line(20, 20, 20, H - 20)
        c.line(W - 20, 20, W - 20, H - 20)
    if raster:
        from PIL import Image, ImageDraw
        img = Image.new("L", (1700, 1200), 255)
        d = ImageDraw.Draw(img)
        for i in range(40):
            d.line([(60 + i * 38, 100), (60 + i * 38, 1100)], fill=0, width=3)
        d.rectangle([300, 300, 700, 600], outline=0, width=5)
        c.drawImage(ImageReader(img), 0, 0, width=W, height=H)
    if dense:
        _lines(c, dense)
    c.setFont("Helvetica", 7)
    for i in range(body_words):
        c.drawString(60 + (i % 20) * 52, 700 - (i // 20) * 11, f"W{i:03d}")
    if title:
        x0, y0 = W - 330, 30
        c.rect(x0, y0, 300, 120)
        c.line(x0, y0 + 60, x0 + 300, y0 + 60)
        c.setFont("Helvetica", 8)
        for i, t in enumerate(["DRAWING NO: 0209-01-ML-02-001", "TITLE: STATION PIPING AND INSTRUMENT",
                               "SCALE: NONE   SHEET 1 OF 2", "DATE: 2015-02-11   APPROVED: AB", "REV C   STATUS: PRELIMINARY"]):
            c.drawString(x0 + 8, y0 + 100 - i * 12, t)
    if revision:
        c.setFont("Helvetica", 7)
        x0, ytop = W - 330, H - 50
        widths = [30, 62, 128, 26, 26, 28]
        edges = [x0]
        for wd in widths:
            edges.append(edges[-1] + wd)
        for r in range(4):
            c.line(x0, ytop - r * 14, edges[-1], ytop - r * 14)
        for e in edges:
            c.line(e, ytop, e, ytop - 42)
        rows = [["REV", "DATE", "DESCRIPTION", "BY", "CHK", "APPR"], ["A", "2014-01-01", "ISSUED FOR REVIEW", "AB", "CD", "EF"],
                ["B", "2014-06-01", "REVISED PER COMMENTS", "AB", "CD", "EF"]]
        for r, row in enumerate(rows):
            for k, cell in enumerate(row):
                c.drawString(edges[k] + 2, ytop - r * 14 - 10, cell)
    if notes:
        c.setFont("Helvetica", 7)
        for i, t in enumerate(["NOTES:", "1. ALL DIMENSIONS IN MM", "2. HOLD 1 TIE-IN POINT TO BE CONFIRMED",
                               "3. SEE LEGEND FOR SYMBOLS"]):
            c.drawString(40, 160 - i * 10, t)
    if table:
        x0, y0 = 420, 40
        c.setFont("Helvetica", 7)
        c.drawString(x0, y0 + 105, "STATION DATA")
        for r in range(5):
            c.line(x0, y0 + r * 20, x0 + 220, y0 + r * 20)
        for k in range(4):
            c.line(x0 + k * 73, y0, x0 + k * 73, y0 + 80)
        for r, row in enumerate([("ITEM", "DESIGN", "OPERATING"), ("PRESSURE", "6895", "3450"), ("TEMP", "60", "15")]):
            for k, cell in enumerate(row):
                c.drawString(x0 + 4 + k * 73, y0 + 62 - r * 20, cell)
    c.showPage()
    c.save()
    data = buf.getvalue()
    if rotate or crop:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import RectangleObject
        reader = PdfReader(BytesIO(data))
        writer = PdfWriter()
        page = reader.pages[0]
        if crop:
            page.cropbox = RectangleObject(list(crop))
        if rotate:
            page.rotate(rotate)
        writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        data = out.getvalue()
    return data


# ---------------------------------------------------------------------------------------------------- symbol sheets
def draw_symbol(c, kind: str, cx: float, cy: float, s: float, rot: int = 0, *, lw: float = 0.8) -> None:
    """Draw a symbol with plain reportlab path code (independent of the library's own drawers). (cx, cy) = centre, PDF points."""
    c.saveState()
    c.translate(cx, cy)
    c.rotate(-rot)                 # clockwise rotation like the library
    c.setLineWidth(lw)
    c.setStrokeGray(0)
    c.setFillGray(0)
    h = s * 0.6

    def poly(pts, fill=0, stroke=1):
        p = c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        p.close()
        c.drawPath(p, fill=fill, stroke=stroke)

    def bowtie(fill=0):
        poly([(-s / 2, -h / 2), (-s / 2, h / 2), (0, 0)], fill=fill)
        poly([(s / 2, -h / 2), (s / 2, h / 2), (0, 0)], fill=fill)
    if kind == "gate":
        bowtie()
    elif kind == "bowtie_filled":
        bowtie(fill=1)
    elif kind == "globe":
        bowtie()
        c.circle(0, 0, s * 0.12, stroke=0, fill=1)
    elif kind == "ball":
        bowtie()
        c.circle(0, 0, s * 0.17, stroke=1, fill=0)
    elif kind == "butterfly":
        bowtie()
        c.line(0, -h / 2, 0, h / 2)
    elif kind == "check":
        hh = s * 0.7
        poly([(-s / 2 + s * .05, -hh / 2 + hh * .05), (-s / 2 + s * .05, hh / 2 - hh * .05), (s * .35, 0)])
        c.line(s * .45, -hh / 2, s * .45, hh / 2)
    elif kind == "inst_field":
        c.circle(0, 0, s / 2, stroke=1, fill=0)
    elif kind == "inst_panel":
        c.circle(0, 0, s / 2, stroke=1, fill=0)
        c.line(-s / 2, 0, s / 2, 0)
    elif kind == "flange":
        c.line(-s * 0.04, -h / 2, -s * 0.04, h / 2)
        c.line(s * 0.04, -h / 2, s * 0.04, h / 2)
    elif kind == "flow_arrow":
        poly([(-s / 2, -h / 3), (-s / 2, h / 3), (s / 2, 0)], fill=1)
    elif kind == "vessel_v":
        w, hh = s, s * 2.2
        c.line(-w / 2, -hh * .32, -w / 2, hh * .32)
        c.line(w / 2, -hh * .32, w / 2, hh * .32)
        c.ellipse(-w / 2, hh * .32 - hh * .18, w / 2, hh * .32 + hh * .18, stroke=1, fill=0) if False else None
        p = c.beginPath()
        p.moveTo(-w / 2, hh * .32)
        p.curveTo(-w / 2, hh * .5, w / 2, hh * .5, w / 2, hh * .32)
        c.drawPath(p, stroke=1, fill=0)
        p = c.beginPath()
        p.moveTo(-w / 2, -hh * .32)
        p.curveTo(-w / 2, -hh * .5, w / 2, -hh * .5, w / 2, -hh * .32)
        c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


def draw_actuator(c, kind: str, cx: float, cy: float, s: float, *, lw: float = 0.8) -> None:
    """Actuator head above a valve centred at (cx, cy) with body width ``s`` (stem starts at the valve apex)."""
    c.saveState()
    c.setLineWidth(lw)
    c.setStrokeGray(0)
    top = cy + s * 0.30                       # valve apex is the stem root (just above the body)
    if kind == "manual":
        c.line(cx, top, cx, top + s * 0.62)
        c.line(cx - s * 0.32, top + s * 0.62, cx + s * 0.32, top + s * 0.62)
    elif kind == "diaphragm":
        c.line(cx, top, cx, top + s * 0.28)
        p = c.beginPath()
        p.moveTo(cx - s * 0.34, top + s * 0.28)
        p.curveTo(cx - s * 0.34, top + s * 0.72, cx + s * 0.34, top + s * 0.72, cx + s * 0.34, top + s * 0.28)
        p.close()
        c.drawPath(p, stroke=1, fill=0)
    elif kind == "motor":
        c.line(cx, top, cx, top + s * 0.22)
        c.circle(cx, top + s * 0.22 + s * 0.2, s * 0.2, stroke=1, fill=0)
    c.restoreState()


def symbol_sheet_pdf(items: list[dict], *, size=(600.0, 420.0), pipe: bool = True, raster: bool = False, noise: int = 0) -> bytes:
    """items: ``{"kind", "x", "y", "s", "rot"?, "actuator"?}`` in points (origin bottom-left)."""
    buf = BytesIO()
    pw, ph = size
    c = canvas.Canvas(buf, pagesize=size, pageCompression=0, invariant=1)
    if pipe:
        c.setLineWidth(0.8)
        ys = sorted({it["y"] for it in items if it.get("pipe", not it["kind"].startswith(("inst", "vessel")))})
        for y in ys:
            c.line(10, y, pw - 10, y)
    for it in items:
        draw_symbol(c, it["kind"], it["x"], it["y"], it["s"], it.get("rot", 0))
        if it.get("actuator"):
            draw_actuator(c, it["actuator"], it["x"], it["y"], it["s"])
    c.setLineWidth(0.4)
    for i in range(noise):
        c.line(5 + (i * 37) % int(pw - 20), 5 + (i * 53) % int(ph - 20), 9 + (i * 37) % int(pw - 20), 9 + (i * 53) % int(ph - 20))
    c.showPage()
    c.save()
    data = buf.getvalue()
    if raster:
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(data)[0].render(scale=2.2).to_pil().convert("L")
        buf2 = BytesIO()
        c2 = canvas.Canvas(buf2, pagesize=size, pageCompression=0, invariant=1)
        c2.drawImage(ImageReader(img), 0, 0, width=pw, height=ph)
        c2.showPage()
        c2.save()
        data = buf2.getvalue()
    return data
