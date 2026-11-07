from io import StringIO
from pid_reader.formats.dxf_source import read_dxf


def test_dxf_extracts_native_geometry_and_label():
    import ezdxf
    doc=ezdxf.new("R2010")
    space=doc.modelspace()
    space.add_line((0,0),(100,0),dxfattribs={"layer":"PROCESS"})
    space.add_text("PT-101",dxfattribs={"insert":(45,10),"layer":"INSTRUMENT"})
    space.add_circle((25,25),5)
    stream=StringIO();doc.write(stream)
    a=read_dxf(stream.getvalue().encode("utf-8"))
    b=read_dxf(stream.getvalue().encode("utf-8"))
    assert a==b
    assert a["format"]=="DXF"
    assert len(a["entities"])==3
    text=[x for x in a["entities"] if x["type"]=="TEXT"][0]
    assert text["data"]["candidate_class"]=="INSTRUMENT"
    assert text["data"]["text"]=="PT-101"
    assert a["source_units"]=="SOURCE_DRAWING_UNITS_UNINTERPRETED"


def test_dxf_refuses_nul():
    try:
        read_dxf(b"bad\x00dxf")
    except ValueError as e:
        assert "NUL" in str(e)
    else:
        assert False
