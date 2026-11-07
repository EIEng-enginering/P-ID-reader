"""Rights-controlled benchmark metadata, not a source for client drawings.

A benchmark candidate is never treated as a tested engineering truth merely
because it is registered.  In particular, an independently verified, licensed,
real-world drawing must be used before the untouched final split is assigned.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from ..api import canonical_json, sha256_hex

SCHEMA = 'pid-reader-benchmark-registry-v1'
RIGHTS = frozenset({'UNVERIFIED', 'CLEARED', 'RESTRICTED', 'EXPIRED'})
KINDS = frozenset({'SYNTHETIC', 'PUBLIC_THIRD_PARTY', 'CLIENT_AUTHORISED', 'OWNED'})
SPLITS = frozenset({'CANDIDATE', 'DEVELOPMENT', 'RESERVED_FINAL'})
LABELS = frozenset({'UNLABELLED', 'IN_PROGRESS', 'INDEPENDENTLY_VERIFIED'})
HASH = re.compile(r'^[0-9a-f]{64}$')


def _stamp(registry: dict) -> dict:
    body = {k: v for k, v in registry.items() if k != 'registry_sha256'}
    registry['registry_sha256'] = sha256_hex(canonical_json(body).encode('utf-8'))
    return registry


def new_registry() -> dict:
    return _stamp({'schema': SCHEMA, 'candidates': [],
                   'independent_accuracy_status': 'NOT_RUN',
                   'rules': 'Never use reserved-final sheets for tuning or training; no drawing bytes in this registry.'})


def validate_registry(registry: dict) -> list[str]:
    errors=[]
    if not isinstance(registry, dict):
        return ['Registry must be an object']
    if registry.get('schema') != SCHEMA:
        errors.append('Unsupported registry schema')
    body={k:v for k,v in registry.items() if k!='registry_sha256'}
    try:
        if registry.get('registry_sha256') != sha256_hex(canonical_json(body).encode('utf-8')):
            errors.append('Registry content hash mismatch')
    except (TypeError, ValueError):
        errors.append('Invalid JSON registry')
    candidates=registry.get('candidates')
    if not isinstance(candidates, list):
        return errors+['Candidates must be a list']
    seen=set()
    for idx, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f'Candidate {idx}: not an object'); continue
        doc_hash=candidate.get('source_sha256')
        if not isinstance(doc_hash,str) or HASH.fullmatch(doc_hash) is None:
            errors.append(f'Candidate {idx}: invalid source SHA-256')
        if doc_hash in seen:
            errors.append(f'Candidate {idx}: duplicate source SHA-256')
        seen.add(doc_hash)
        if candidate.get('rights') not in RIGHTS or candidate.get('kind') not in KINDS:
            errors.append(f'Candidate {idx}: invalid rights or drawing category')
        if candidate.get('split') not in SPLITS or candidate.get('labels') not in LABELS:
            errors.append(f'Candidate {idx}: invalid split or annotation state')
        if candidate.get('split') != 'CANDIDATE' and candidate.get('rights') != 'CLEARED':
            errors.append(f'Candidate {idx}: uncleared drawing cannot be a benchmark')
        if candidate.get('split') == 'RESERVED_FINAL' and candidate.get('labels') != 'INDEPENDENTLY_VERIFIED':
            errors.append(f'Candidate {idx}: final evaluation requires independent labels')
        if candidate.get('split') == 'RESERVED_FINAL' and candidate.get('kind') == 'SYNTHETIC':
            errors.append(f'Candidate {idx}: synthetic drawing is not independent industrial validation')
        if not isinstance(candidate.get('reference'),str) or not candidate.get('reference', '').strip():
            errors.append(f'Candidate {idx}: source reference missing')
        if not isinstance(candidate.get('rights_evidence'),str):
            errors.append(f'Candidate {idx}: rights evidence missing')
        if candidate.get('rights') == 'CLEARED' and not candidate.get('rights_evidence', '').strip():
            errors.append(f'Candidate {idx}: cleared rights require evidence')
        reviewers=candidate.get('reviewers')
        if not isinstance(reviewers,list) or any(not isinstance(r,str) or not r.strip() for r in reviewers):
            errors.append(f'Candidate {idx}: invalid reviewer list')
        if candidate.get('labels') == 'INDEPENDENTLY_VERIFIED' and len(set(reviewers or [])) < 2:
            errors.append(f'Candidate {idx}: at least two named distinct reviewers required')
    if registry.get('independent_accuracy_status') not in ('NOT_RUN','BLOCKED','IN_PROGRESS','COMPLETE_WITH_EVIDENCE'):
        errors.append('Invalid independent accuracy status')
    return errors


def add_candidate(registry: dict, *, source_sha256: str, reference: str, kind: str,
                  rights: str='UNVERIFIED', rights_evidence: str='') -> dict:
    if validate_registry(registry):
        raise ValueError('Input benchmark registry is invalid')
    candidate={'source_sha256':source_sha256, 'reference':reference.strip(),
               'kind':kind, 'rights':rights, 'rights_evidence':rights_evidence.strip(),
               'labels':'UNLABELLED', 'reviewers':[], 'split':'CANDIDATE'}
    result=deepcopy(registry)
    result['candidates'].append(candidate)
    _stamp(result)
    errors=validate_registry(result)
    if errors: raise ValueError('; '.join(errors))
    return result


def advance_candidate(registry:dict, *, source_sha256:str, rights:str|None=None,
                      rights_evidence:str|None=None, labels:str|None=None,
                      reviewers:list[str]|None=None, split:str|None=None) -> dict:
    if validate_registry(registry):raise ValueError('Input benchmark registry is invalid')
    result=deepcopy(registry)
    matches=[c for c in result['candidates'] if c['source_sha256']==source_sha256]
    if len(matches)!=1:raise ValueError('Exactly one existing candidate required')
    c=matches[0]
    if c['split']=='RESERVED_FINAL' and (split not in (None,'RESERVED_FINAL') or labels not in (None,'INDEPENDENTLY_VERIFIED')):
        raise ValueError('Reserved-final status cannot be downgraded')
    if rights is not None:c['rights']=rights
    if rights_evidence is not None:c['rights_evidence']=rights_evidence.strip()
    if labels is not None:c['labels']=labels
    if reviewers is not None:c['reviewers']=list(reviewers)
    if split is not None:c['split']=split
    _stamp(result)
    errors=validate_registry(result)
    if errors:raise ValueError('; '.join(errors))
    return result


def summary(registry: dict) -> dict:
    if validate_registry(registry):raise ValueError('Invalid benchmark registry')
    return {'total_candidates':len(registry['candidates']),
            'cleared':sum(c['rights']=='CLEARED' for c in registry['candidates']),
            'development':sum(c['split']=='DEVELOPMENT' for c in registry['candidates']),
            'reserved_final':sum(c['split']=='RESERVED_FINAL' for c in registry['candidates']),
            'independent_accuracy_status':registry['independent_accuracy_status']}


def read_registry(path: str|Path) -> dict:
    with Path(path).open(encoding='utf-8') as file: data=json.load(file)
    errors=validate_registry(data)
    if errors:raise ValueError('; '.join(errors))
    return data


def write_registry(path: str|Path, registry: dict, *, overwrite:bool=False) -> None:
    errors=validate_registry(registry)
    if errors:raise ValueError('; '.join(errors))
    dest=Path(path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and not overwrite:raise FileExistsError(dest)
    if dest.exists() and overwrite:
        current=read_registry(dest)
        old={c['source_sha256']:c for c in current['candidates'] if c['split']=='RESERVED_FINAL'}
        new={c['source_sha256']:c for c in registry['candidates']}
        if any(doc not in new or new[doc]!=item for doc,item in old.items()):
            raise ValueError('Cannot change reserved-final metadata in place')
    fd,name=tempfile.mkstemp(prefix='.benchmark-',suffix='.json.tmp',dir=dest.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as file:
            file.write(canonical_json(registry)+'\n')
            file.flush();os.fsync(file.fileno())
        os.replace(name,dest)
    finally:
        if os.path.exists(name):os.unlink(name)
