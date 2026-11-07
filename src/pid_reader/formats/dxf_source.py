"""Standalone DXF *source observations* reader, not a host R1 adapter.

Preserves native DXF geometry, layers, text and block references. It does not
assert engineering meaning or infer physical connections from graphical contact.
No DWG conversion or external-reference resolution is attempted.
"""
from __future__ import annotations
import hashlib
from io import StringIO
import json
from math import isfinite
from .pdf_source import _parse_tag

SUPPORTED = {"LINE","LWPOLYLINE","POLYLINE","CIRCLE","ARC","INSERT","TEXT","MTEXT","POINT"}

def _point(value):
    return [round(float(value[0]),8),round(float(value[1]),8),round(float(value[2]) if len(value)>2 else 0.0,8)]


def read_dxf(data: bytes, *, max_bytes: int = 32 * 1024 * 1024, max_entities: int = 100000) -> dict:
    """Read a DXF file into source observation records with original coordinates.

    All entities are marked unreviewed. This output has its own standalone
    structure, never the Worksheet host's normalised PDF JSON schema.
    """
    if len(data) > max_bytes:
        raise ValueError("DXF exceeds configured file size budget")
    if b"AutoCAD Binary DXF" in data[:40]:
        raise ValueError("Binary DXF not supported by this development adapter")
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("Optional ezdxf package is not installed") from exc
    if b"\x00" in data:
        raise ValueError("NUL bytes refused in text DXF")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252",errors="strict")
    try:
        doc = ezdxf.read(StringIO(text))
    except Exception as exc:
        raise ValueError("DXF could not be parsed") from exc
    records=[]
    diag=[]
    for idx, entity in enumerate(doc.modelspace()):
        if idx>=max_entities:
            raise ValueError("DXF entity budget exceeded")
        etype = entity.dxftype()
        item={"source_handle":str(entity.dxf.handle),"type":etype,"layer":str(entity.dxf.layer),
              "review_state":"PROPOSED","data":{}}
        d=item["data"]
        try:
            if etype=="LINE":
                d.update(start=_point(entity.dxf.start),end=_point(entity.dxf.end))
            elif etype=="CIRCLE":
                d.update(center=_point(entity.dxf.center),radius=float(entity.dxf.radius))
            elif etype=="ARC":
                d.update(center=_point(entity.dxf.center),radius=float(entity.dxf.radius),
                         start_angle=float(entity.dxf.start_angle),end_angle=float(entity.dxf.end_angle))
            elif etype=="INSERT":
                d.update(block_name=str(entity.dxf.name),insert=_point(entity.dxf.insert),
                         scale=[float(entity.dxf.xscale),float(entity.dxf.yscale),float(entity.dxf.zscale)])
                d["attributes"]=[{"tag":a.dxf.tag,"text":a.dxf.text} for a in entity.attribs]
            elif etype=="TEXT":
                tag=str(entity.dxf.text)
                cls,parsed,score=_parse_tag(tag)
                d.update(text=tag,insert=_point(entity.dxf.insert),candidate_class=cls,tag_parse=parsed,reader_score=score)
            elif etype=="MTEXT":
                d.update(text=entity.text,insert=_point(entity.dxf.insert))
            elif etype=="LWPOLYLINE":
                d.update(points=[[float(x),float(y)] for x,y,*rest in entity.get_points()],closed=bool(entity.closed))
            elif etype=="POLYLINE":
                d.update(points=[_point(v.dxf.location) for v in entity.vertices],closed=bool(entity.is_closed))
            elif etype=="POINT":
                d.update(location=_point(entity.dxf.location))
            else:
                diag.append({"code":"UNSUPPORTED_ENTITY","entity_type":etype,"handle":str(entity.dxf.handle)})
                d["uninterpreted"]=True
        except (ValueError,KeyError,AttributeError,TypeError) as exc:
            diag.append({"code":"ENTITY_NOT_READ","entity_type":etype,"handle":str(entity.dxf.handle)})
            d.clear();d["uninterpreted"]=True
        records.append(item)
    records.sort(key=lambda x:(x["source_handle"],x["type"]))
    return {"format":"DXF","schema_version":1,"source_sha256":hashlib.sha256(data).hexdigest(),
            "source_units":"SOURCE_DRAWING_UNITS_UNINTERPRETED", "entities":records,
            "warnings":diag,
            "limitations":"Native geometry and text only. Blocks, units, layout coordinates and engineering connections need interpretation."}
