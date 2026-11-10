"""PID2Graph graphml reader (stdlib). Nodes -> boxes with labels; edges -> (u, v, edge_label). Used for TR1 R&D training/eval."""
import xml.etree.ElementTree as ET
NS = "{http://graphml.graphdrawing.org/xmlns}"
NON_SYMBOL = {"connector", "crossing", "border_node", "border", "arrow"}   # graph helper nodes, not symbols (arrow kept separately)


def read(path):
    root = ET.parse(path).getroot()
    keys = {k.get("id"): k.get("attr.name") for k in root.iter(NS + "key")}
    nodes, edges = [], []
    for n in root.iter(NS + "node"):
        d = {keys[x.get("key")]: x.text for x in n.findall(NS + "data")}
        try:
            box = [float(d["xmin"]), float(d["ymin"]), float(d["xmax"]), float(d["ymax"])]
        except (KeyError, TypeError, ValueError):
            box = None
        nodes.append({"id": n.get("id"), "label": d.get("label"), "box": box})
    for e in root.iter(NS + "edge"):
        d = {keys[x.get("key")]: x.text for x in e.findall(NS + "data")}
        edges.append((e.get("source"), e.get("target"), d.get("edge_label")))
    return nodes, edges
