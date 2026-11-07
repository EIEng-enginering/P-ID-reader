"""Drawing viewer: PDF page + layered, selectable recognition overlays."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

LAYER_COLOURS = {
    "readings": "#1f77d4", "symbols": "#9c27b0", "linework": "#e67e22", "catalogue": "#009688",
    "text_links": "#2e9e5b", "geometry": "#d32f2f", "signals": "#e91e8c", "search": "#f2c200",
}
LAYER_LABELS = {
    "readings": "Text readings", "symbols": "Outline symbols", "linework": "Valves / lines",
    "catalogue": "Template matches", "text_links": "Tag links", "geometry": "Line contacts",
    "signals": "Signal strokes", "search": "Search hits",
}
MAX_RENDER_SIDE = 4200


class DrawingView(QGraphicsView):
    itemActivated = Signal(str, str)       # layer, item id
    pageStep = Signal(int)                 # -1 / +1 requested by keyboard
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(QGraphicsScene(), parent)
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

    # ------------------------------------------------------------ page
    def clear_page(self) -> None:
        self.scene().clear()
        self._layers = {}
        self._highlight = None
        self.page_size = (0, 0)

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
            b = it.get("bbox")
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

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
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
