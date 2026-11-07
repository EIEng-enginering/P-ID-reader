from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from pid_reader.api import ReadParams, read_pid, RefusedInput, sha256_hex
from pid_reader.worker import atomic_publish
from pid_reader.release_assurance import check_import, check_r1, smoke_worker, preflight

ROOT=Path(__file__).resolve().parents[1]


def invoke_worker(tmp_path, content: bytes, params: object = None, *, existing: bool = False,
                  output_inside: bool = False):
    src=tmp_path/'input.pdf';src.write_bytes(content)
    cfg=tmp_path/'params.json';cfg.write_text(json.dumps({} if params is None else params))
    scratch=tmp_path/'scratch';scratch.mkdir()
    out=(scratch if output_inside else tmp_path)/'output.json'
    if existing:out.write_text('KEEP')
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')
    proc=subprocess.run([sys.executable,'-m','pid_reader.worker','run',
                         '--input',str(src),'--params',str(cfg),'--output',str(out),
                         '--workdir',str(scratch)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    return proc,out,scratch


def test_r1_zip_frozen_and_valid():
    assert check_r1(ROOT)['status']=='PASS'


def test_project_import_forced_to_current_checkout():
    assert check_import(ROOT)['status']=='PASS'


def test_worker_isolated_preflight():
    assert smoke_worker(ROOT)['status']=='PASS'


def test_preflight_is_truthful_about_unrun_gates():
    r=preflight(ROOT)
    assert r['passed']
    assert 'Real Worksheet host G4-G7' in r['not_run']
    assert 'Windows Python 3.12 / PySide6 6.12 UI' in r['not_run']


def test_worker_atomic_result_is_valid(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf)
    assert proc.returncode==0 and out.exists()
    assert not list(scratch.iterdir())
    assert json.loads(out.read_text())['document']['sha256']==sha256_hex(synthetic_pdf)


def test_worker_refuses_existing_result_without_overwrite(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,existing=True)
    assert proc.returncode==2
    assert out.read_text()=='KEEP' and not list(scratch.iterdir())


def test_worker_refuses_output_inside_scratch(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,output_inside=True)
    assert proc.returncode==2 and not out.exists() and not list(scratch.iterdir())


def test_worker_refuses_nonobject_params(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,params=[1,2,3])
    assert proc.returncode==2 and not out.exists() and not list(scratch.iterdir())


def test_worker_refuses_unknown_parameter(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,params={'external_ai':True})
    assert proc.returncode==2 and not out.exists()


def test_worker_refuses_bad_page_list(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,params={'pages':[True]})
    assert proc.returncode==2 and not out.exists()


def test_worker_handles_nonpdf_without_partial_result(tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,b'not a pdf')
    assert proc.returncode==2 and not out.exists() and not list(scratch.iterdir())


def test_worker_limit_exceeded_without_partial_result(synthetic_pdf,tmp_path):
    proc,out,scratch=invoke_worker(tmp_path,synthetic_pdf,params={'max_pdf_bytes':64})
    assert proc.returncode==3 and not out.exists() and not list(scratch.iterdir())


def test_atomic_publish_scratch_missing_refused(tmp_path):
    with pytest.raises(RefusedInput):atomic_publish({'hello':'world'},tmp_path/'output.json',tmp_path/'missing')
    assert not (tmp_path/'output.json').exists()


def test_atomic_publish_preserves_unicode_and_valid_json(tmp_path):
    scratch=tmp_path/'scratch';scratch.mkdir()
    result={'label':'ΔP','objects':[]}
    out=tmp_path/'result.json'
    atomic_publish(result,out,scratch)
    assert json.loads(out.read_text(encoding='utf-8'))==result
    assert not list(scratch.iterdir())


def test_atomic_publish_no_clobber(tmp_path):
    scratch=tmp_path/'scratch';scratch.mkdir()
    out=tmp_path/'result.json';out.write_text('KEEP')
    with pytest.raises(RefusedInput):atomic_publish({'a':1},out,scratch)
    assert out.read_text()=='KEEP' and not list(scratch.iterdir())


def test_core_import_no_ui_dependency():
    # Fresh interpreter: other tests (GUI) legitimately import PySide6 into this process.
    import subprocess, os
    from pathlib import Path
    src=str(Path(__file__).resolve().parents[1]/'src')
    code="import sys, pid_reader.release_assurance, pid_reader.engineering.pipeline, pid_reader.engineering.connectivity, pid_reader.engineering.findings; sys.exit(1 if 'PySide6' in sys.modules else 0)"
    done=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONPATH':src})
    assert done.returncode==0


def test_distribution_manifest_enumerates_noncache_files(tmp_path):
    import importlib.util
    spec=__import__('importlib.util',fromlist=['spec_from_file_location']).spec_from_file_location('release_build',ROOT/'tools'/'build_handoff.py')
    assert spec and spec.loader
    mod=__import__('importlib.util',fromlist=['module_from_spec']).module_from_spec(spec)
    spec.loader.exec_module(mod)
    p=tmp_path/'mock';p.mkdir();(p/'src').mkdir()
    (p/'src'/'example.py').write_text('a=1')
    (p/'__pycache__').mkdir();(p/'__pycache__'/'bad.pyc').write_bytes(b'bad')
    archive=tmp_path/'mock.zip'
    info=mod.build(p,archive)
    assert info['integrity']=='PASS' and info['files']==2
    assert b'example.py' in archive.read_bytes()


def test_distribution_archive_detects_content_tampering(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('release_build',ROOT/'tools'/'build_handoff.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    p=tmp_path/'mock';p.mkdir();(p/'data.txt').write_text('real')
    archive=tmp_path/'mock.zip';mod.build(p,archive)
    import zipfile
    tampered=tmp_path/'modified.zip'
    with zipfile.ZipFile(archive) as old,zipfile.ZipFile(tampered,'w') as new:
        for n in old.namelist():
            new.writestr(n, b'changed' if n.endswith('/data.txt') else old.read(n))
    with pytest.raises(AssertionError):mod.verify_archive(tampered,'mock')
