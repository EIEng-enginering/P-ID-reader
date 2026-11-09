"""Source-backed standalone symbol proposals, NOT equipment or plant verification."""
import io
import json
import sqlite3

import pytest
from reportlab.pdfgen import canvas

from pid_reader.api import ReadParams, read_pid, canonical_json, sha256_hex
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals, validate_symbol_proposals
from pid_reader.engineering.project import ProjectStore


def symbol_pdf():
    buf=io.BytesIO()
    c=canvas.Canvas(buf,pagesize=(600,650),pageCompression=0)
    c.setFont('Helvetica',8)
    # Text centre inside a circular instrument outline.
    c.circle(140,500,23)
    c.drawCentredString(140,497,'PT-101')
    # Equipment rectangle and a single observed line touching the boundary.
    c.rect(300,440,100,60)
    c.drawCentredString(350,468,'V-101')
    c.line(400,470,470,470)
    # Multiple tag centres; never resolve to a unique instrument.
    c.circle(180,350,30)
    c.drawCentredString(180,357,'PT-201')
    c.drawCentredString(180,340,'PT-202')
    # Empty circle -> UNKNOWN outline.
    c.circle(350,340,15)
    # Dashed signal-like line ending at the bubble outline: do not emit a physical port.
    c.setDash(4,2)
    c.line(140,523,140,550)
    c.setDash()
    c.save()
    return buf.getvalue()


def analyze():
    source=symbol_pdf()
    extraction=read_pid(source,ReadParams())
    topo=analyze_pdf_topology(source)
    return source,extraction,topo,build_symbol_proposals(extraction,topo)


def test_instrument_and_equipment_candidates_proposed():
    _,extraction,topology,symbols=analyze()
    assert len(topology['shape_candidates'])>=4
    types={x['candidate_class'] for x in symbols['symbol_candidates']}
    assert 'INSTRUMENT_BUBBLE_CANDIDATE' in types
    assert 'EQUIPMENT_OUTLINE_CANDIDATE' in types
    assert 'AMBIGUOUS_OUTLINE' in types
    assert 'UNCLASSIFIED_OUTLINE' in types
    assert symbols['port_candidates']
    assert all(x['status']=='PROPOSED_UNVERIFIED' for x in symbols['symbol_candidates'])
    assert all(x['status']=='PROPOSED_UNVERIFIED' for x in symbols['port_candidates'])
    assert validate_symbol_proposals(symbols,extraction,topology)==[]


def test_geometric_port_is_always_only_a_hypothesis():
    _,extraction,topology,symbols=analyze()
    seg_by_id={s['id']:s for s in topology['segments']}
    sym_by_id={s['id']:s for s in symbols['symbol_candidates']}
    ports=[p for p in symbols['port_candidates'] if sym_by_id[p['symbol_id']]['candidate_class']=='EQUIPMENT_OUTLINE_CANDIDATE']
    assert ports
    assert all('not established' in p['limitations'] for p in ports)
    assert all(seg_by_id[p['segment_id']]['style']=='SOLID_OR_UNKNOWN' for p in ports)


def test_repeat_is_bitwise_deterministic_and_does_not_touch_r1():
    pdf,extraction,topology,result=analyze()
    assert result==build_symbol_proposals(extraction,topology)
    unchanged=read_pid(pdf,ReadParams())
    assert unchanged['provenance']['result_sha256']==extraction['provenance']['result_sha256']
    assert 'symbol_candidates' not in unchanged


def test_forged_missing_shape_rejected_even_if_rehashed():
    _,e,g,s=analyze()
    s['symbol_candidates'][0]['shape_id']='shape-fake'
    s['result_sha256']=sha256_hex(canonical_json({k:v for k,v in s.items() if k!='result_sha256'}).encode())
    assert 'Symbol lacks source shape' in validate_symbol_proposals(s,e,g)


def test_source_mismatch_rejected():
    _,e,g,_=analyze()
    g['source_sha256']='0'*64
    with pytest.raises(Exception):build_symbol_proposals(e,g)


def test_standalone_persistence_review_and_migration(tmp_path):
    pdf,e,g,s=analyze()
    src=tmp_path/'symbols.sqlite'
    with ProjectStore(src) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        eid=db.add_extraction(e,source_pdf_bytes=pdf)
        gid=db.add_geometry_analysis(eid,g)
        aid=db.add_symbol_analysis(eid,gid,s)
        assert db.add_symbol_analysis(eid,gid,s)==aid
        assert db.get_symbol_analysis(aid)==s
        candidates=db.list_symbol_candidates(aid)
        assert len(candidates)==len(s['symbol_candidates'])
        cid=candidates[0]['candidate_id']
        with pytest.raises(ValueError):db.review_symbol(cid,actor='Reviewer',decision='ACCEPTED_AS_READING',reason='')
        rid=db.review_symbol(cid,actor='Reviewer',decision='UNRESOLVED',reason='Needs legend')
        assert rid.startswith('sdec-')
        assert db.latest_symbol_review(cid)['decision']=='UNRESOLVED'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM symbol_decision WHERE decision_id=?',(rid,))
        copied=db.backup(tmp_path/'backup.sqlite')
    with ProjectStore(copied) as db:
        assert db.latest_symbol_review(cid)['actor']=='Reviewer'
        assert db.verify_audit_chain()
        assert db.get_symbol_analysis(aid)==s


def test_migration_from_existing_v2(tmp_path):
    from pid_reader.engineering.migrations import MIGRATION_2
    from pid_reader.engineering.project import DDL
    p=tmp_path/'old.sqlite'
    with sqlite3.connect(p) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO project_meta VALUES('standalone_schema','1')")
        db.commit()
        db.executescript(MIGRATION_2)
    with ProjectStore(p) as db:
        assert db.migration_backup and db.migration_backup.exists()
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert db.db.execute("SELECT name FROM sqlite_master WHERE name='symbol_analysis'").fetchone()
    with sqlite3.connect(next(tmp_path.glob('old.sqlite.pre-v13-*.sqlite'))) as backup:
        assert backup.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='2'


def test_cli_symbol_analysis_roundtrip(tmp_path):
    from pid_reader.cli import main
    pdf,e,g,s=analyze()
    db=tmp_path/'db.sqlite';source=tmp_path/'input.pdf';source.write_bytes(pdf)
    out=tmp_path/'symbols.json'
    assert main(['import-pdf',str(db),str(source)])==0
    with ProjectStore(db) as store:
        eid=store.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-topology',str(db),eid])==0
    with ProjectStore(db) as store:
        gid=store.db.execute('SELECT analysis_id FROM geometry_analysis').fetchone()[0]
    assert main(['analyze-symbols',str(db),eid,gid,'--output-json',str(out)])==0
    with ProjectStore(db) as store:
        persisted_extraction=store.export_extraction(eid)
        persisted_topology=store.get_geometry_analysis(gid)
    assert json.loads(out.read_text())==build_symbol_proposals(persisted_extraction,persisted_topology)
    with ProjectStore(db) as store:
        aid=store.db.execute('SELECT analysis_id FROM symbol_analysis').fetchone()[0]
    assert main(['symbol-candidates',str(db),aid])==0


def test_standalone_symbol_result_conforms_to_json_schema():
    from pathlib import Path
    from jsonschema import Draft202012Validator
    root=Path(__file__).resolve().parents[1]
    schema=json.loads((root/'contracts/standalone_symbols_v1.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    _,_,_,symbols=analyze()
    assert list(Draft202012Validator(schema).iter_errors(symbols))==[]


def test_forged_symbol_class_rejected_after_rehash():
    _,e,g,result=analyze()
    original=result['symbol_candidates'][0]['candidate_class']
    result['symbol_candidates'][0]['candidate_class']=('AMBIGUOUS_OUTLINE' if original!='AMBIGUOUS_OUTLINE' else 'UNCLASSIFIED_OUTLINE')
    result['result_sha256']=sha256_hex(canonical_json({k:v for k,v in result.items() if k!='result_sha256'}).encode())
    assert 'Symbol or port hypotheses differ from source-derived algorithm output' in validate_symbol_proposals(result,e,g)
