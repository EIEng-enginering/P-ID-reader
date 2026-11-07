"""Pre-handoff adversarial tests for local worker integrity and process isolation."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import sys

import pytest

from pid_reader.api import ReadParams, RefusedInput, LimitExceeded, canonical_json, read_pid, result_sha256, sha256_hex
from pid_reader.worker import atomic_publish
from pid_reader.engineering import isolation


def test_publish_is_atomic_and_does_not_clobber(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    output = tmp_path / 'result.json'
    atomic_publish({'reading': 'PROPOSED_UNVERIFIED'}, output, scratch)
    assert json.loads(output.read_text()) == {'reading': 'PROPOSED_UNVERIFIED'}
    assert list(scratch.iterdir()) == []


def test_publish_concurrent_destination_race_is_refused(tmp_path, monkeypatch):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    output = tmp_path / 'result.json'

    def adversarial_link(staged, dest):
        Path(dest).write_text('OTHER WRITER', encoding='utf-8')
        raise FileExistsError(errno.EEXIST, 'File exists', str(dest))

    monkeypatch.setattr('pid_reader.worker.os.link', adversarial_link)
    with pytest.raises(RefusedInput):
        atomic_publish({'candidate': True}, output, scratch)
    assert output.read_text() == 'OTHER WRITER'
    assert not list(scratch.iterdir())


def test_publish_cross_volume_or_link_not_supported_is_refused(tmp_path, monkeypatch):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    out = tmp_path / 'result.json'

    def no_link(src, dst):
        raise OSError(errno.EXDEV, 'Cross-device link')

    monkeypatch.setattr('pid_reader.worker.os.link', no_link)
    with pytest.raises(RefusedInput, match='hard links'):
        atomic_publish({'a': 1}, out, scratch)
    assert not out.exists() and not list(scratch.iterdir())


def test_publish_enforces_r1_eight_megabyte_budget(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    with pytest.raises(LimitExceeded) as err:
        atomic_publish({'payload': 'x' * (8 * 1024 * 1024)}, tmp_path / 'result.json', scratch)
    assert err.value.code == 'PID_LIMIT_RESULT'
    assert not (tmp_path / 'result.json').exists()
    assert not list(scratch.iterdir())


@pytest.mark.parametrize('kw', [
    {'max_pdf_bytes': '100'}, {'max_pdf_bytes': 0}, {'max_pages': -1},
    {'max_render_pixels': 1.5}, {'max_render_pixels': True},
    {'bulk_accept_min_confidence': '0.8'}, {'bulk_accept_min_confidence': float('nan')},
    {'pages': (0,)}, {'pages': (True,)}, {'pages': ('1',)},
    {'extras': ['unexpected']},
])
def test_r1_parameters_refuse_invalid_types_without_internal_error(kw):
    with pytest.raises(RefusedInput):
        ReadParams(**kw).validate()


def test_worker_no_stderr_pipe_deadlock(tmp_path):
    """A child producing many diagnostics must not hang the parent waiting for EOF."""
    code = "import sys;sys.stderr.write('A'*400000);sys.stderr.flush()"
    rc, diagnostic, reason = isolation.run_limited(
        [sys.executable, '-c', code], env=os.environ.copy(), cwd=str(tmp_path),
        timeout_s=10, memory_mb=512)
    assert rc == 0 and reason == ''
    assert diagnostic and len(diagnostic) <= 65536


def _worker_spoof(tmp_path, monkeypatch, source, params, result):
    """Simulate an isolated worker exiting OK with a crafted result file."""
    def fake_run(cmd, *, env, cwd, timeout_s, memory_mb, should_cancel):
        output = Path(cmd[cmd.index('--output') + 1])
        output.write_bytes(canonical_json(result).encode('utf-8'))
        return isolation.EXIT_OK, '', ''
    monkeypatch.setattr(isolation, 'run_limited', fake_run)
    return isolation.read_pid_isolated(source, params, scratch_root=tmp_path)


def test_isolated_worker_rejects_forged_source_hash(synthetic_pdf, tmp_path, monkeypatch):
    params = ReadParams()
    result = read_pid(synthetic_pdf, params)
    result['document']['sha256'] = '0' * 64
    result['provenance']['input_sha256'] = '0' * 64
    result['provenance']['result_sha256'] = result_sha256(result)
    with pytest.raises(RefusedInput) as exc:
        _worker_spoof(tmp_path, monkeypatch, synthetic_pdf, params, result)
    assert exc.value.code == 'PID_SHA_MISMATCH'


def test_isolated_worker_rejects_forged_result_hash(synthetic_pdf, tmp_path, monkeypatch):
    params = ReadParams()
    result = read_pid(synthetic_pdf, params)
    result['provenance']['result_sha256'] = '0' * 64
    with pytest.raises(RefusedInput) as exc:
        _worker_spoof(tmp_path, monkeypatch, synthetic_pdf, params, result)
    assert exc.value.code == 'PID_MALFORMED'


def test_isolated_worker_rejects_forged_parameter_identity(synthetic_pdf, tmp_path, monkeypatch):
    params = ReadParams()
    result = read_pid(synthetic_pdf, params)
    result['provenance']['params_sha256'] = sha256_hex(b'{}')
    result['provenance']['result_sha256'] = result_sha256(result)
    with pytest.raises(RefusedInput) as exc:
        _worker_spoof(tmp_path, monkeypatch, synthetic_pdf, params, result)
    assert exc.value.code == 'PID_MALFORMED'


def test_isolated_worker_rejects_broken_summary(synthetic_pdf, tmp_path, monkeypatch):
    params = ReadParams()
    result = read_pid(synthetic_pdf, params)
    result['summary']['object_count'] = 999
    result['provenance']['result_sha256'] = result_sha256(result)
    with pytest.raises(RefusedInput):
        _worker_spoof(tmp_path, monkeypatch, synthetic_pdf, params, result)


def test_isolated_worker_rejects_oversized_result_without_unbounded_read(synthetic_pdf, tmp_path, monkeypatch):
    def fake_run(cmd, *, env, cwd, timeout_s, memory_mb, should_cancel):
        out = Path(cmd[cmd.index('--output') + 1])
        out.write_bytes(b'{' + b'A' * (8*1024*1024 + 1))
        return isolation.EXIT_OK, '', ''
    monkeypatch.setattr(isolation, 'run_limited', fake_run)
    with pytest.raises(LimitExceeded) as exc:
        isolation.read_pid_isolated(synthetic_pdf, ReadParams(), scratch_root=tmp_path)
    assert exc.value.code == 'PID_LIMIT_RESULT'


def test_isolated_worker_normal_result_passes_integrity(synthetic_pdf, tmp_path):
    result = isolation.read_pid_isolated(synthetic_pdf, ReadParams(), scratch_root=tmp_path)
    assert result['document']['sha256'] == sha256_hex(synthetic_pdf)
    assert result['provenance']['result_sha256'] == result_sha256(result)


def test_isolated_rejects_oversized_input_before_spawn(synthetic_pdf, tmp_path, monkeypatch):
    def must_not_spawn(*args, **kwargs):
        pytest.fail('Worker must not be spawned for refused input')
    monkeypatch.setattr(isolation, 'run_limited', must_not_spawn)
    with pytest.raises(LimitExceeded) as exc:
        isolation.read_pid_isolated(synthetic_pdf, ReadParams(max_pdf_bytes=128), scratch_root=tmp_path)
    assert exc.value.code == 'PID_LIMIT_BYTES'


def test_isolated_refuses_wrong_expected_source_before_spawn(synthetic_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, 'run_limited', lambda *a, **k: pytest.fail('Unexpected worker spawn'))
    with pytest.raises(RefusedInput) as exc:
        isolation.read_pid_isolated(synthetic_pdf, ReadParams(), expected_sha256='0'*64, scratch_root=tmp_path)
    assert exc.value.code == 'PID_SHA_MISMATCH'


def test_isolated_cancelled_before_spawn(synthetic_pdf, tmp_path, monkeypatch):
    from pid_reader.api import Cancelled
    monkeypatch.setattr(isolation, 'run_limited', lambda *a, **k: pytest.fail('Unexpected worker spawn'))
    with pytest.raises(Cancelled):
        isolation.read_pid_isolated(synthetic_pdf, ReadParams(), scratch_root=tmp_path, should_cancel=lambda: True)
