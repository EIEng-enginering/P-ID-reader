"""Qt-free integration of the Rev S raster evidence into existing findings and page-coordinate APIs."""
from __future__ import annotations
from pathlib import Path
import json
from io import BytesIO

import pytest
import jsonschema
import pytest
pytest.importorskip("cv2")
pytest.importorskip("numpy")
pytest.importorskip("pypdfium2")
from pypdf import PdfReader, PdfWriter

from pid_reader.api import ReadParams, read_pid
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.raster_geometry import analyze_raster_geometry
from pid_reader.engineering import findings
from pid_reader.formats.page_coordinates import PageFrame, frame_from_pdfplumber

HERE=Path(__file__).resolve().parents[1]


def test_schema_validates_real_fixture():
    pdf=(HERE/'fixtures/synthetic_raster_filled_valves.pdf').read_bytes()
    result=analyze_raster_geometry(pdf)
    schema=json.loads((HERE/'contracts/standalone_raster_geometry_v2.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(result,schema)


def test_findings_review_source_and_audit(tmp_path):
    pdf=(HERE/'fixtures/synthetic_raster_filled_valves.pdf').read_bytes()
    with ProjectStore(tmp_path/'findings.sqlite') as db:
        eid=db.add_extraction(read_pid(pdf,ReadParams(),filename='findings.pdf'),source_pdf_bytes=pdf)
        ra=analyze_raster_geometry(pdf)
        db.add_raster_analysis(eid,ra)
        assert 'raster' in findings.LAYERS
        got=findings.list_findings(db,eid,'raster')
        assert len(got)==2
        assert all(row['state']=='PROPOSED' and row['bbox'] for row in got)
        assert findings.latest_analysis_ids(db,eid)['raster']
        id=got[0]['id']
        findings.review_finding(db,'raster',id,actor='Reviewer A',
                                decision='UNRESOLVED',reason='Confirm against legend')
        now=findings.list_findings(db,eid,'raster')
        assert next(r for r in now if r['id']==id)['state']=='UNRESOLVED'
        assert db.verify_audit_chain()


def test_media_to_render_clips_and_refuses_outside():
    frame=PageFrame(1000.,1000.,100.,200.,600.,500.,0)
    original={'x0':.05,'y0':.1,'x1':.3,'y1':.35}
    clipped=frame.media_bbox_to_render_clipped(original)
    assert clipped['x0']==0 and clipped['y0']==0
    assert clipped['x1']>0 and clipped['y1']>0
    assert frame.media_bbox_to_render_clipped({'x0':.01,'y0':.01,'x1':.02,'y1':.02}) is None
    with pytest.raises(ValueError):
        frame.media_bbox_to_render_clipped({'x0':.7,'y0':.2,'x1':.3,'y1':.4})


def test_page_crop_rotation_round_trip():
    pdf=(HERE/'fixtures/synthetic_raster_filled_valves.pdf').read_bytes()
    src=PdfReader(BytesIO(pdf))
    page=src.pages[0]
    page.cropbox.lower_left=(20,20)
    page.cropbox.upper_right=(480,350)
    page.rotate(270)
    writer=PdfWriter();writer.add_page(page)
    buf=BytesIO();writer.write(buf)
    import pdfplumber
    with pdfplumber.open(BytesIO(buf.getvalue())) as pages:
        frame=frame_from_pdfplumber(pages.pages[0])
    px,py=frame.render_to_media(.2,.4)
    transformed=frame.media_bbox_to_render_clipped({'x0':px,'y0':py,'x1':min(.999,px+.001),
                                                    'y1':min(.999,py+.001)})
    assert transformed is not None
    assert abs(transformed['x0']-.2)<1e-5 and abs(transformed['y0']-.4)<1e-5
