"""Score printed readings/metadata in a WP456 export using an approved reference.

No reference approval is implied. Draft references return NOT_RUN.
"""
from pathlib import Path
import argparse
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pid_reader.engineering.wp456.common import verify_seal
from pid_reader.engineering.wp456.metrics import score


def main():
    p=argparse.ArgumentParser();p.add_argument('result',type=Path);p.add_argument('reference',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=json.loads(args.result.read_text(encoding='utf8'));reference=json.loads(args.reference.read_text(encoding='utf8'))
    if not verify_seal(result):p.error('Result content hash invalid')
    predictions=[]
    for row in result['wp04']['readings']:
        predictions.append({'id':row['id'],'page':row['page'],'kind':row['kind'],'bbox':row['bbox'],'text':row['text_candidate']})
    for row in result['wp04']['document_fields']:
        predictions.append({'id':row['id'],'page':row['page'],'kind':row['field'],'bbox':row['bbox'],'text':row['value_candidate']})
    scored=score(reference,predictions,source_sha256=result['source_sha256'])
    args.output.write_text(json.dumps(scored,indent=2)+'\n',encoding='utf8');print(scored['status'])


if __name__=='__main__':main()
