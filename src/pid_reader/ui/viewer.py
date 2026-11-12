"""Drawing viewer: PDF page + layered, selectable recognition overlays."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

LAYER_COLOURS = {
    "readings": "#1f77d4", "symbols": "#9c27b0", "linework": "#e67e22", "catalogue": "#009688",
    "text_links": "#2e9e5b", "geometry": "#d32f2f", "signals": "#e91e8c",
    "raster": "#7a3dc0", "examples": "#00acc1", "search": "#f2c200", "intelligence": "#2f7d32",
    "tr1_frcnn": "#ff6f00", "wp123": "#c2185b",
}
LAYER_LABELS = {
    "readings": "Text readings", "symbols": "Outline symbols", "linework": "Valves / lines",
    "catalogue": "Template matches", "text_links": "Tag links", "geometry": "Line contacts",
    "signals": "Signal strokes", "raster": "Raster valve glyphs", "examples": "Taught symbols", "search": "Search hits", "intelligence": "Library symbols",
    "tr1_frcnn": "Learned detector (proposed)", "wp123": "WP-01–03 proposals (unverified)",
}
MAX_RENDER_SIDE = 4200


class DrawingView(QGraphicsView):
    itemActivated = Signal(str, str)       # layer, item id
    pageStep = Signal(int)                 # -1 / +1 requested by keyboard
    zoomChanged = Signal(float)
    boxDrawn = Signal(dict)                # normalised box drawn in teach mode

    def __init__(self, parent=None):
        scene = QGraphicsScene()
        super().__init__(scene, parent)
        self._scene = scene  # keep a Python reference: PySide would otherwise free the scene
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#4b4f55")))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Drawing viewer")
        self._pdf = None
        self._pdf_key = None
        self._layers: dict[str, list[QGraphicsRectItem]] = {}
        self._visible: dict[str, bool] = {k: k != "geometry" for k in LAYER_COLOURS}
        self._highlight: QGraphicsRectItem | None = None
        self._press = QPointF()
        self._fit_on_resize = True
        self.page_size = (0, 0)
        self._teach = False
        self._last_rubber = None
        self.rubberBandChanged.connect(self._rubber_changed)
        self._page_frame = None

    # ------------------------------------------------------------ page
    def clear_page(self) -> None:
        self.scene().clear()
        self._layers = {}
        self._highlight = None
        self.page_size = (0, 0)
        self._page_frame = None

    def load_page(self, pdf_bytes: bytes | None, page: int) -> bool:
        """Render page ``page`` (1-based). Returns False if it cannot be shown."""
        self.clear_page()
        if not pdf_bytes:
            self.scene().addText("Original PDF bytes are not stored in this project.")
            return False
        try:
            import pypdfium2 as pdfium
            key = (len(pdf_bytes), hash(pdf_bytes[:4096]), hash(pdf_bytes[-4096:]))
            if key != self._pdf_key:
                self._pdf = pdfium.PdfDocument(pdf_bytes)
                self._pdf_key = key
            pg = self._pdf[page - 1]
            w, h = pg.get_size()
            scale = max(1.0, min(4.0, MAX_RENDER_SIDE / max(w, h)))
            img = pg.render(scale=scale).to_pil().convert("RGBA")
            # The viewer uses the CropBox while source proposals use the
            # pdfplumber MediaBox: map overlays back to the visible frame.
            from io import BytesIO
            import pdfplumber
            from ..formats.page_coordinates import frame_from_pdfplumber
            with pdfplumber.open(BytesIO(pdf_bytes)) as inspected:
                self._page_frame = frame_from_pdfplumber(inspected.pages[page - 1])
        except ImportError:
            self.scene().addText("PDF rendering needs the pypdfium2 package.")
            return False
        except Exception as exc:
            self.scene().addText(f"Page {page} cannot be rendered: {type(exc).__name__}")
            return False
        qimg = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format.Format_RGBA8888).copy()
        self.scene().addPixmap(QPixmap.fromImage(qimg)).setZValue(0)
        self.scene().setSceneRect(QRectF(0, 0, img.width, img.height))
        self.page_size = (img.width, img.height)
        self.fit()
        return True

    def _render_bbox(self, bbox: dict) -> dict | None:
        if self._page_frame is None:
            return bbox
        return self._page_frame.media_bbox_to_render_clipped(bbox)

    # ------------------------------------------------------------ overlays
    def set_overlay(self, layer: str, items: list[dict]) -> None:
        """items: [{id, bbox, tip}]. Replaces the layer's overlay."""
        for old in self._layers.pop(layer, []):
            self.scene().removeItem(old)
        w, h = self.page_size
        if not w:
            return
        colour = QColor(LAYER_COLOURS.get(layer, "#888888"))
        made = []
        for it in items:
            b = self._render_bbox(it.get("bbox")) if it.get("bbox") else None
            if not b:
                continue
            r = QGraphicsRectItem(QRectF(b["x0"] * w, b["y0"] * h, max(2.0, (b["x1"] - b["x0"]) * w),
                                         max(2.0, (b["y1"] - b["y0"]) * h)))
            pen = QPen(colour, 1.6)
            pen.setCosmetic(True)
            fill = QColor(colour)
            fill.setAlpha(40)
            r.setPen(pen)
            r.setBrush(QBrush(fill))
            r.setToolTip(it.get("tip", ""))
            r.setData(0, layer)
            r.setData(1, it["id"])
            r.setZValue(1)
            r.setVisible(self._visible.get(layer, True))
            self.scene().addItem(r)
            made.append(r)
        self._layers[layer] = made

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        self._visible[layer] = visible
        for item in self._layers.get(layer, []):
            item.setVisible(visible)

    def layer_visible(self, layer: str) -> bool:
        return self._visible.get(layer, True)

    def highlight(self, bbox: dict | None, *, zoom: bool = True) -> None:
        if self._highlight is not None:
            self.scene().removeItem(self._highlight)
            self._highlight = None
        w, h = self.page_size
        if not bbox or not w:
            return
        bbox = self._render_bbox(bbox)
        if not bbox:
            return
        rect = QRectF(bbox["x0"] * w, bbox["y0"] * h, max(3.0, (bbox["x1"] - bbox["x0"]) * w),
                      max(3.0, (bbox["y1"] - bbox["y0"]) * h))
        pen = QPen(QColor("#ff2d2d"), 3.0)
        pen.setCosmetic(True)
        self._highlight = self.scene().addRect(rect, pen, QBrush(Qt.BrushStyle.NoBrush))
        self._highlight.setZValue(5)
        if zoom:
            pad = max(60.0, 3 * max(rect.width(), rect.height()))
            self.fitInView(rect.adjusted(-pad, -pad, pad, pad), Qt.AspectRatioMode.KeepAspectRatio)
            self._fit_on_resize = False
            self.zoomChanged.emit(self.zoom_factor())

    # ------------------------------------------------------------ zoom / pan
    def zoom_factor(self) -> float:
        return self.transform().m11()

    def fit(self) -> None:
        if self.scene().sceneRect().isEmpty():
            return
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_on_resize = True
        self.zoomChanged.emit(self.zoom_factor())

    def zoom_by(self, factor: float) -> None:
        new = self.zoom_factor() * factor
        if 0.02 <= new <= 40:
            self.scale(factor, factor)
            self._fit_on_resize = False
            self.zoomChanged.emit(self.zoom_factor())

    def wheelEvent(self, event) -> None:
        self.zoom_by(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_on_resize:
            self.fit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.2)
        elif key == Qt.Key.Key_Minus:
            self.zoom_by(1 / 1.2)
        elif key == Qt.Key.Key_0:
            self.fit()
        elif key == Qt.Key.Key_1:
            self.resetTransform()
            self._fit_on_resize = False
            self.zoomChanged.emit(self.zoom_factor())
        elif key == Qt.Key.Key_PageDown:
            self.pageStep.emit(1)
        elif key == Qt.Key.Key_PageUp:
            self.pageStep.emit(-1)
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ picking
    def mousePressEvent(self, event) -> None:
        self._press = event.position()
        super().mousePressEvent(event)

    # ------------------------------------------------------------ teach mode (draw a box round one symbol)
    def set_teach_mode(self, on: bool) -> None:
        self._teach = on
        self._last_rubber = None
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if on else QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def _rubber_changed(self, rect, from_scene, to_scene) -> None:
        if not rect.isNull() and self._teach:
            self._last_rubber = (from_scene, to_scene)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._teach:
            pts, self._last_rubber = self._last_rubber, None
            w, h = self.page_size
            if pts and w and event.button() == Qt.MouseButton.LeftButton:
                (ax, ay), (bx, by) = (pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y())
                box = {"x0": max(0.0, min(ax, bx) / w), "y0": max(0.0, min(ay, by) / h),
                       "x1": min(1.0, max(ax, bx) / w), "y1": min(1.0, max(ay, by) / h)}
                if box["x1"] - box["x0"] > 0.002 and box["y1"] - box["y0"] > 0.002:
                    self.boxDrawn.emit(box)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if (event.position() - self._press).manhattanLength() > 4:
            return  # a pan, not a click
        best = None
        for item in self.items(event.position().toPoint()):
            if item.data(0) and item.isVisible():
                area = item.rect().width() * item.rect().height()
                if best is None or area < best[0]:
                    best = (area, item)
        if best:
            self.itemActivated.emit(best[1].data(0), best[1].data(1))
