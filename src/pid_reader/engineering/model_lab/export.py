"""Portable source-linked comparison export with spreadsheet-safe CSV."""
import csv
import json
from pathlib import Path
from ..wp456.common import verify_seal

def export(result,directory):
    if result.get('schema')!='pid-reader-model-lab-v2' or not verify_seal(result):raise ValueError('Invalid model comparison seal')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    (root/'model_comparison.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
    def safe(value):
        s='' if value is None else str(value)
        return "'"+s if s.lstrip().startswith(('=','+','-','@')) or s.startswith(('\t','\r','\n')) else s
    with (root/'model_proposals.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);keys=['id','page','kind','text','class_name','raw_score','engine','model_revision','review_state']
        writer.writerow(keys)
        for row in result['model_result']['records']:writer.writerow([safe(row.get(k)) for k in keys])
    if result.get('derived_wp456'):
        from ..wp456.pipeline import export as export456
        export456(result['derived_wp456'],root/'derived_wp456')
