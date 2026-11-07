"""Interactive proposed-connectivity graph drawn at the items' real page positions."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

KIND_COLOURS = {"SYMBOL": "#9c27b0", "VALVE_GLYPH": "#e67e22", "LINE_NETWORK": "#607d8b"}
SCALE = 1600.0


class GraphView(QGraphicsView):
    nodeClicked = Signal(str)   # node id

    def __init__(self, parent=None):
        scene = QGraphicsScene()
        super().__init__(scene, parent)
        self._scene = scene  # keep a Python reference: PySide would otherwise free the scene
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAccessibleName("Proposed connectivity graph")
        self._nodes: dict[str, object] = {}
        self._press = QPointF()
        self.graph: dict = {}

    def set_graph(self, graph: dict, page: int | None = None) -> None:
        self.scene().clear()
        self._nodes = {}
        self.graph = graph
        nodes = [n for n in graph.get("nodes", []) if page is None or n["page"] == page]
        keep = {n["id"] for n in nodes}
        centres: dict[str, QPointF] = {}
        for n in nodes:
            b = n["bbox"]
            centres[n["id"]] = QPointF((b["x0"] + b["x1"]) / 2 * SCALE, (b["y0"] + b["y1"]) / 2 * SCALE)
        pen_edge = QPen(QColor("#78909c"), 1.4)
        pen_edge.setCosmetic(True)
        pen_tee = QPen(QColor("#d84315"), 1.4, Qt.PenStyle.DashLine)
        pen_tee.setCosmetic(True)
        for e in graph.get("edges", []):
            if e["from"] in keep and e["to"] in keep:
                line = self.scene().addLine(centres[e["from"]].x(), centres[e["from"]].y(),
                                            centres[e["to"]].x(), centres[e["to"]].y(), pen_tee if e["via_tee"] else pen_edge)
                line.setZValue(0)
                line.setToolTip(f"{e['relation'].replace('_', ' ').title()}"
                                + (" (through a tee junction)" if e["via_tee"] else ""))
        font = QFont()
        font.setPointSize(16)
        for n in nodes:
            c = centres[n["id"]]
            colour = QColor(KIND_COLOURS.get(n["kind"], "#444444"))
            pen = QPen(QColor("#222222"), 1.2)
            pen.setCosmetic(True)
            if n["kind"] == "LINE_NETWORK":
                item = QGraphicsEllipseItem(QRectF(c.x() - 7, c.y() - 7, 14, 14))
                item.setBrush(QBrush(colour))
            elif n["kind"] == "VALVE_GLYPH":
                item = QGraphicsPolygonItem(QPolygonF([QPointF(c.x() - 22, c.y()), QPointF(c.x(), c.y() - 15),
                                                       QPointF(c.x() + 22, c.y()), QPointF(c.x(), c.y() + 15)]))
                item.setBrush(QBrush(colour))
            else:
                item = QGraphicsRectItem(QRectF(c.x() - 34, c.y() - 18, 68, 36))
                item.setBrush(QBrush(colour.lighter(165)))
            item.setPen(pen)
            item.setZValue(2)
            item.setData(0, n["id"])
            item.setToolTip(f"{n['label']}\n{n['kind'].replace('_', ' ').title()} • proposed, unverified")
            self.scene().addItem(item)
            self._nodes[n["id"]] = item
            if n["kind"] != "LINE_NETWORK":
                text = self.scene().addSimpleText(n["label"][:24], font)
                text.setPos(c.x() - text.boundingRect().width() / 2, c.y() + 20)
                text.setZValue(3)
        if nodes:
            self.fitInView(self.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)

    def select_node(self, node_id: str) -> None:
        item = self._nodes.get(node_id)
        if item:
            self.centerOn(item)
            pen = QPen(QColor("#ff2d2d"), 3)
            pen.setCosmetic(True)
            item.setPen(pen)

    def wheelEvent(self, event) -> None:
        f = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def mousePressEvent(self, event) -> None:
        self._press = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and (event.position() - self._press).manhattanLength() <= 4:
            for item in self.items(event.position().toPoint()):
                if item.data(0):
                    self.nodeClicked.emit(item.data(0))
                    return
