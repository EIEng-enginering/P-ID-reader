"""Small deterministic contracts shared by the three work packs."""
from __future__ import annotations
import hashlib
import json
import math
import re

STATE = 'PROPOSED_UNVERIFIED'
FRAME = 'MEDIA_NORMALIZED_TOP_LEFT'
MAX_ITEMS = 5000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def ident(prefix, *values):
    return prefix + '-' + digest(values)[:24]


def number(value, lo=0., hi=1.):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a coordinate or score')
    n = float(value)
    if not math.isfinite(n) or not lo <= n <= hi:
        raise ValueError('Non-finite or out-of-range number')
    return n


def box(b):
    out = {k: number(b[k]) for k in ('x0', 'y0', 'x1', 'y1')}
    if out['x0'] >= out['x1'] or out['y0'] >= out['y1']:
        raise ValueError('Empty or reversed box')
    return out


def page(value):
    if type(value) is not int or value < 1:
        raise ValueError('Page must be a positive integer')
    return value


def area(b):
    return (b['x1']-b['x0'])*(b['y1']-b['y0'])


def overlap(a, b):
    return max(0., min(a['x1'], b['x1'])-max(a['x0'], b['x0'])) * max(0., min(a['y1'], b['y1'])-max(a['y0'], b['y0']))


def iou(a, b):
    x = overlap(a, b)
    return x / max(1e-15, area(a)+area(b)-x)


def center(b):
    return ((b['x0']+b['x1'])/2, (b['y0']+b['y1'])/2)


def clean(text):
    # Typography only. Confusable letters and missing digits are not corrected.
    return re.sub(r'\s+', '', str(text).upper().strip()).translate(str.maketrans({'–':'-', '—':'-', '−':'-'}))


def collection(rows, limit=MAX_ITEMS):
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('Collection exceeds budget or is not a list')
    ids = set()
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get('id'), str) or not r['id'] or r['id'] in ids:
            raise ValueError('Missing or duplicate evidence id')
        ids.add(r['id'])
    return rows


def source_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected lower-case source SHA256')
    return value


def evidence_rows(rows):
    collection(rows)
    for r in rows:
        box(r['bbox']); page(r['page'])
    return rows


def seal(value):
    out = dict(value)
    out.pop('result_sha256', None)
    out['result_sha256'] = digest(out)
    return out


def verify_seal(value):
    data = dict(value)
    expected = data.pop('result_sha256', None)
    return expected == digest(data)
