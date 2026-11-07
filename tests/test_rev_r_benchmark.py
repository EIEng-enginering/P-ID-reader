"""Benchmarks require clear drawing rights and independent human reference labels."""
from __future__ import annotations
import pytest
from pid_reader.engineering.benchmark_registry import (
    add_candidate, advance_candidate, new_registry, summary, validate_registry,
    write_registry, read_registry,
)
SHA='a'*64
SHA2='b'*64


def candidate():
    return add_candidate(new_registry(),source_sha256=SHA,reference='PUBLIC-TEST-A',kind='PUBLIC_THIRD_PARTY')


def test_empty_registry_does_not_claim_accuracy():
    s=summary(new_registry());assert s['total_candidates']==0
    assert s['independent_accuracy_status']=='NOT_RUN'


def test_uncleared_candidate_cannot_be_benchmark():
    with pytest.raises(ValueError,match='uncleared'):
        advance_candidate(candidate(),source_sha256=SHA,split='DEVELOPMENT')


def test_restricted_rights_cannot_be_implicitly_cleared():
    with pytest.raises(ValueError,match='evidence'):
        advance_candidate(candidate(),source_sha256=SHA,rights='CLEARED')


def test_cleared_candidate_can_join_development():
    c=advance_candidate(candidate(),source_sha256=SHA,rights='CLEARED',rights_evidence='Licence dated 2026-11-07',split='DEVELOPMENT')
    assert summary(c)['development']==1


def test_holdout_requires_independent_annotation():
    c=advance_candidate(candidate(),source_sha256=SHA,rights='CLEARED',rights_evidence='Public licence')
    with pytest.raises(ValueError,match='independent labels'):
        advance_candidate(c,source_sha256=SHA,split='RESERVED_FINAL')


def test_synthetic_gold_cannot_pose_as_real_independent_holdout():
    c=add_candidate(new_registry(),source_sha256=SHA,reference='SYNTHETIC-A',kind='SYNTHETIC',rights='CLEARED',rights_evidence='Own drawing')
    with pytest.raises(ValueError,match='synthetic'):
        advance_candidate(c,source_sha256=SHA,labels='INDEPENDENTLY_VERIFIED',reviewers=['A','B'],split='RESERVED_FINAL')


def test_duplicate_sha_rejected():
    with pytest.raises(ValueError,match='duplicate'):
        add_candidate(candidate(),source_sha256=SHA,reference='copy',kind='PUBLIC_THIRD_PARTY')


def test_valid_independent_holdout_is_frozen(tmp_path):
    c=advance_candidate(candidate(),source_sha256=SHA,rights='CLEARED',rights_evidence='Rights verification',labels='INDEPENDENTLY_VERIFIED',reviewers=['Reviewer One','Reviewer Two'],split='RESERVED_FINAL')
    out=tmp_path/'registry.json';write_registry(out,c)
    assert read_registry(out)==c
    with pytest.raises(ValueError,match='downgraded'):
        advance_candidate(c,source_sha256=SHA,split='DEVELOPMENT')
    old=read_registry(out)
    altered=new_registry()
    with pytest.raises(ValueError,match='reserved-final'):
        write_registry(out,altered,overwrite=True)
    assert read_registry(out)==old


def test_hash_tampering_rejected():
    c=candidate();c['candidates'][0]['rights']='CLEARED'
    assert validate_registry(c)


def test_atomic_write_rejects_implicit_overwrite(tmp_path):
    out=tmp_path/'registry.json';write_registry(out,new_registry())
    with pytest.raises(FileExistsError):write_registry(out,new_registry())


def test_invalid_reviewer_identity_rejected():
    c=advance_candidate(candidate(),source_sha256=SHA,rights='CLEARED',rights_evidence='licence')
    with pytest.raises(ValueError,match='two named'):
        advance_candidate(c,source_sha256=SHA,labels='INDEPENDENTLY_VERIFIED',reviewers=['Engineer','Engineer'])
