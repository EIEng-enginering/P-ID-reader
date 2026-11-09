"""Rev N tests: source-derived templates, negative controls and standalone DB."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest

from pid_reader.api import ReadParams, read_pid, canonical_json, sha256_hex
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals
from pid_reader.engineering.linework import build_linework_proposals
from pid_reader.engineering.symbol_catalog import (
    example_catalog, validate_catalog, build_catalog_analysis,
    validate_catalog_analysis, _circle_on_stem,
)
from pid_reader.engineering.project import ProjectStore
from pid_reader.cli import main

SOURCE=Path(__file__).resolve().parents[1]/'fixtures'/'synthetic_catalog_symbols.pdf'

@pytest.fixture(scope='module')
def inputs():
    source=SOURCE.read_bytes()
    e=read_pid(source,ReadParams(),filename=SOURCE.name)
    g=analyze_pdf_topology(source)
    s=build_symbol_proposals(e,g)
    l=build_linework_proposals(e,g,s)
    return source,e,g,s,l


def test_starter_catalogue_safe_and_limited():
    example=example_catalog()
    assert validate_catalog(example)==[]
    assert len(example['templates'])==11
    assert all(t['feature'] in {'TAGGED_OUTLINE','BOWTIE_VALVE','BOWTIE_STEM_CIRCLE'} for t in example['templates'])
    assert len(canonical_json(example))<12000


def test_catalogue_detection_positive_and_negative(inputs):
    _,e,g,s,l=inputs
    r=build_catalog_analysis(e,g,s,l,example_catalog())
    classes=[c['candidate_class'] for c in r['candidates']]
    assert len(classes)==6
    assert classes.count('GENERIC_BOWTIE_VALVE_STYLE')==2
    assert classes.count('VALVE_WITH_STEM_CIRCLE_STYLE')==1
    assert 'VESSEL_RECTANGULAR_OUTLINE_STYLE' in classes
    assert 'PUMP_CIRCULAR_OUTLINE_STYLE' in classes
    assert 'INSTRUMENT_BUBBLE_STYLE' in classes
    assert validate_catalog_analysis(r,e,g,s,l,example_catalog())==[]
    assert build_catalog_analysis(e,g,s,l,example_catalog())==r
    assert all(c['state']=='PROPOSED_UNVERIFIED' for c in r['candidates'])
    assert 'plant' in r['limitations'] or 'SIL' in r['limitations']


def test_template_project_override_without_training(inputs):
    _,e,g,s,l=inputs
    cat=example_catalog();cat['catalogue_name']='Project original symbols';cat['revision']='2'
    cat['templates']=[{'template_id':'proj-pump-circular','feature':'TAGGED_OUTLINE',
        'candidate_class':'PROJECT_PUMP_STYLE','outline_shape':'CLOSED_NEAR_CIRCULAR_OUTLINE',
        'source_classes':['PUMP']}]
    assert validate_catalog(cat)==[]
    r=build_catalog_analysis(e,g,s,l,cat)
    assert len(r['candidates'])==1
    assert r['candidates'][0]['candidate_class']=='PROJECT_PUMP_STYLE'
    assert r['catalogue_revision']=='2'


@pytest.mark.parametrize('change',[
    lambda c:c.update({'python':'exec()'}),
    lambda c:c['templates'][0].update({'regex':'.*'}),
    lambda c:c['templates'][0].update({'source_classes':['PUMP','not-r1']}),
    lambda c:c['templates'][0].update({'template_id':'Invalid $ class'}),
    lambda c:c['templates'].append(deepcopy(c['templates'][0])),
    lambda c:c['templates'][0].update({'candidate_class':'../../SECRETS'}),
    lambda c:c['templates'][0].update({'source_classes':[{}]}),
])
def test_rejects_invalid_or_executable_catalogue(change):
    catalogue=example_catalog();change(catalogue)
    assert validate_catalog(catalogue)


def test_rehashed_catalogue_proposal_is_not_accepted(inputs):
    _,e,g,s,l=inputs
    r=build_catalog_analysis(e,g,s,l,example_catalog())
    tampered=deepcopy(r)
    tampered['candidates'][0]['candidate_class']='APPROVED_SIL4'
    tampered['result_sha256']=sha256_hex(canonical_json({k:v for k,v in tampered.items() if k!='result_sha256'}).encode())
    assert validate_catalog_analysis(tampered,e,g,s,l,example_catalog())
    wrong_catalogue=example_catalog();wrong_catalogue['revision']='changed'
    assert validate_catalog_analysis(r,e,g,s,l,wrong_catalogue)


def test_source_hash_enforced(inputs):
    _,e,g,s,l=inputs
    bad=deepcopy(e);bad['document']['sha256']='0'*64
    with pytest.raises(ValueError,match='hash'):
        build_catalog_analysis(bad,g,s,l,example_catalog())
    altered=deepcopy(g);altered['segments'][0]['style']='INVENTED'
    with pytest.raises(ValueError,match='evidence'):
        build_catalog_analysis(e,altered,s,l,example_catalog())


def test_stem_circle_needs_real_stroke(inputs):
    _,_,g,_,l=inputs
    shapes=[x for x in g['shape_candidates'] if x['shape']=='CLOSED_NEAR_CIRCULAR_OUTLINE']
    valve=min(l['valve_candidates'],key=lambda v:abs(v['centre'][0]-.72))
    other=min(l['valve_candidates'],key=lambda v:abs(v['centre'][0]-.33))
    matches=[(sh['id'],seg['id']) for sh in shapes for seg in g['segments'] if _circle_on_stem(valve,sh,seg)]
    assert len(matches)==1
    assert not [(sh['id'],seg['id']) for sh in shapes for seg in g['segments'] if _circle_on_stem(other,sh,seg)]
    seg=next(x for x in g['segments'] if x['id']==matches[0][1])
    dashed=deepcopy(seg);dashed['style']='DASHED_OR_DOTTED'
    assert not _circle_on_stem(valve,next(x for x in shapes if x['id']==matches[0][0]),dashed)


def test_sqlite_migration_catalogue_audit_and_backup(inputs,tmp_path):
    raw,e,g,s,l=inputs
    path=tmp_path/'project.sqlite'
    with ProjectStore(path) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        eid=db.add_extraction(e,raw)
        gid=db.add_geometry_analysis(eid,g)
        sid=db.add_symbol_analysis(eid,gid,s)
        lid=db.add_linework_analysis(eid,gid,sid,l)
        cid=db.register_symbol_catalogue(example_catalog())
        assert db.register_symbol_catalogue(example_catalog())==cid
        assert db.get_symbol_catalogue(cid)==example_catalog()
        aid,result=db.analyze_symbol_catalogue(eid,gid,sid,lid,cid)
        assert db.analyze_symbol_catalogue(eid,gid,sid,lid,cid)[0]==aid
        assert db.get_symbol_catalogue_analysis(aid)==result
        assert len(db.list_catalogue_candidates(aid))==6
        assert len(db.list_catalogue_candidates(aid,candidate_class='VALVE_WITH_STEM_CIRCLE_STYLE'))==1
        candidate=db.list_catalogue_candidates(aid)[0]['candidate_id']
        with pytest.raises(ValueError,match='reviewer'):
            db.review_catalogue_candidate(candidate,actor='',decision='ACCEPTED_AS_READING',reason='Valid reviewer observation')
        with pytest.raises(ValueError,match='reason'):
            db.review_catalogue_candidate(candidate,actor='Engineer',decision='ACCEPTED_AS_READING',reason='bad')
        with pytest.raises(ValueError):
            db.review_catalogue_candidate(candidate,actor='Engineer',decision='APPROVED_PLANT',reason='This is not permitted')
        decision=db.review_catalogue_candidate(candidate,actor='Engineer',decision='UNRESOLVED',reason='Drawing legend needed')
        assert db.latest_catalogue_review(candidate)['decision']=='UNRESOLVED'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            db.db.execute('DELETE FROM symbol_catalogue WHERE catalogue_id=?',(cid,))
        with pytest.raises(sqlite3.DatabaseError):
            db.db.execute('DELETE FROM catalog_decision WHERE decision_id=?',(decision,))
        db.db.rollback()  # clear the expected trigger errors before online backup
        backup=db.backup(tmp_path/'copy.sqlite')
    with ProjectStore(backup) as restored:
        assert restored.get_symbol_catalogue_analysis(aid)==result
        assert restored.latest_catalogue_review(candidate)['actor']=='Engineer'
        assert restored.verify_audit_chain()


def test_migrate_old_v7_database_preserves_records(tmp_path):
    old=tmp_path/'previous.sqlite'
    with ProjectStore(old) as db:
        with db.db:
            db.db.execute('INSERT OR REPLACE INTO project_meta VALUES(?,?)',('test_marker','untouched'))
        assert db.verify_audit_chain()
    with sqlite3.connect(old) as conn:
        conn.execute("UPDATE project_meta SET value='7' WHERE key='standalone_schema'")
    with ProjectStore(old) as newer:
        assert newer.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert newer.db.execute("SELECT value FROM project_meta WHERE key='test_marker'").fetchone()[0]=='untouched'
        assert newer.migration_backup is not None
        assert newer.verify_audit_chain()
    with sqlite3.connect(next(tmp_path.glob('previous.sqlite.pre-v12-*.sqlite'))) as previous:
        assert previous.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='7'


def test_cli_symbol_catalogue_roundtrip(inputs,tmp_path,capsys):
    raw,_,_,_,_=inputs
    path=str(tmp_path/'project.sqlite'); drawing=tmp_path/'drawing.pdf'; drawing.write_bytes(raw)
    assert main(['import-pdf',path,str(drawing)])==0
    with ProjectStore(path) as db:
        eid=db.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-topology',path,eid])==0
    with ProjectStore(path) as db:
        gid=db.db.execute('SELECT analysis_id FROM geometry_analysis').fetchone()[0]
    assert main(['analyze-symbols',path,eid,gid])==0
    with ProjectStore(path) as db:
        sid=db.db.execute('SELECT analysis_id FROM symbol_analysis').fetchone()[0]
    assert main(['analyze-linework',path,eid,gid,sid])==0
    with ProjectStore(path) as db:
        lid=db.db.execute('SELECT analysis_id FROM linework_analysis').fetchone()[0]
    assert main(['register-symbol-catalogue',path])==0
    with ProjectStore(path) as db:
        cid=db.db.execute('SELECT catalogue_id FROM symbol_catalogue').fetchone()[0]
    assert main(['analyze-symbol-catalogue',path,eid,gid,sid,lid,cid])==0
    with ProjectStore(path) as db:
        aid=db.db.execute('SELECT analysis_id FROM catalog_analysis').fetchone()[0]
        candidate=db.list_catalogue_candidates(aid)[0]['candidate_id']
    assert main(['catalogue-candidates',path,aid])==0
    assert 'GENERIC_BOWTIE_VALVE_STYLE' in capsys.readouterr().out
    assert main(['review-catalogue',path,candidate,'--actor','Engineer',
                 '--decision','UNRESOLVED','--reason','Check drawing legend'])==0
    with ProjectStore(path) as db:
        assert db.latest_catalogue_review(candidate)['decision']=='UNRESOLVED'
        assert db.verify_audit_chain()


def test_catalogue_and_result_schemas(inputs):
    import jsonschema
    _,e,g,sy,l=inputs
    base=Path(__file__).resolve().parents[1]
    catalogue=example_catalog()
    result=build_catalog_analysis(e,g,sy,l,catalogue)
    jsonschema.validate(catalogue,json.loads((base/'contracts/standalone_symbol_catalog_v1.schema.json').read_text()))
    jsonschema.validate(result,json.loads((base/'contracts/standalone_catalog_analysis_v1.schema.json').read_text()))
