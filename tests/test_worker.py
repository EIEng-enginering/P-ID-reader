import json, subprocess,sys
from pathlib import Path


def test_worker_output_and_scratch_cleanup(synthetic_pdf,tmp_path):
    src=tmp_path/"input.pdf";src.write_bytes(synthetic_pdf)
    par=tmp_path/"params.json";par.write_text("{}")
    dst=tmp_path/"result.json"
    scratch=tmp_path/"scratch";scratch.mkdir()
    r=subprocess.run([sys.executable,"-m","pid_reader.worker","run","--input",str(src),"--params",str(par),"--output",str(dst),"--workdir",str(scratch)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    assert scratch.exists() and not list(scratch.iterdir())
    assert dst.exists()
    obj=json.loads(dst.read_text())
    assert obj["summary"]["object_count"]>=4
    assert "V-101" not in r.stderr
