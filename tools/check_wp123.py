"""Validate the standalone WP123 JSON schema and canonical hash.

Usage: python tools/check_wp123.py output/wp123_result.json [--source original.pdf]
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import hashlib
import sys

def main():
    p=argparse.ArgumentParser();p.add_argument('result');p.add_argument('--source')
    a=p.parse_args()
    try:
        import jsonschema
        doc=json.loads(Path(a.result).read_text(encoding='utf-8'))
        schema=json.loads((Path(__file__).resolve().parents[1]/'contracts/standalone_wp123_result_v1.schema.json').read_text(encoding='utf-8'))
        jsonschema.validate(doc,schema)
        content={k:v for k,v in doc.items() if k!='result_sha256'}
        actual=hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
        if actual!=doc['result_sha256']:raise ValueError('Result SHA-256 mismatch')
        if a.source:
            pdf=Path(a.source).read_bytes()
            if hashlib.sha256(pdf).hexdigest()!=doc['source_sha256']:raise ValueError('PDF source SHA-256 mismatch')
        print('WP123 JSON structure/hash checks: PASS. Engineering accuracy NOT verified.')
        return 0
    except (ValueError,KeyError,OSError,ImportError,json.JSONDecodeError) as e:
        print('WP123 validation FAILED:',str(e)[:300],file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
