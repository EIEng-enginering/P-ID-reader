#!/usr/bin/env python3
"""Integrity verification of CLAUDE HANDOFF ONLY; NOT app tests or engineering validation."""
from pathlib import Path
import hashlib, zipfile, json, csv, sys
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'baseline/Rev_X_INPUT_ARCHIVE_UNMODIFIED.zip'
EXPECTED_ARCHIVE='61ca7b4acdf8fa24282e4c02de50c027175802b8b197e18cd926885bf1805636'
EXPECTED_FROZEN='09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2'
INNER='PID_Reader_Update_Pack_For_ChatGPT_Rev_X/source_snapshot/contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip'

def hashfile(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def main():
 problems=[]
 if not SRC.exists():problems.append('missing original Rev X archive')
 else:
  h=hashfile(SRC)
  if h!=EXPECTED_ARCHIVE:problems.append('Rev X archive HASH MISMATCH: '+h)
  with zipfile.ZipFile(SRC) as z:
   bad=z.testzip()
   if bad:problems.append('corrupt inner zip member: '+bad)
   names=z.namelist()
   if len(names)!=274:problems.append('expected 274 original entries, got %s'%len(names))
   if any(n.startswith('/') or '..' in Path(n).parts for n in names):problems.append('unsafe path in source archive')
   if INNER not in names:problems.append('missing frozen Worksheet R1 archive')
   elif hashlib.sha256(z.read(INNER)).hexdigest()!=EXPECTED_FROZEN:problems.append('frozen Worksheet R1 HASH MISMATCH')
 approvals=ROOT/'requirements/APPROVED_REQUIREMENTS_Q1_Q100.csv'
 if approvals.exists():
  with approvals.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
  ids=[r['question_id'] for r in rows]
  if len(rows)!=100 or len(set(ids))!=100 or set(ids)!={f'Q{i:03}' for i in range(1,101)}:problems.append('not exactly Q001-Q100')
  if any(r['approved_option']!='A' or r['status']!='APPROVED' for r in rows):problems.append('approved option mismatch')
 else:problems.append('missing approval register')
 trace=ROOT/'requirements/IMPLEMENTATION_TRACEABILITY.csv'
 if trace.exists():
  with trace.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
  if len(rows)!=20 or len({r['wp_id'] for r in rows})!=20:problems.append('expected 20 unique work packages')
 else:problems.append('missing implementation traceability')
 manifest=ROOT/'manifests/FILE_SHA256.tsv'
 if not manifest.exists():problems.append('missing SHA256 file manifest')
 else:
  for lineno,line in enumerate(manifest.read_text(encoding='utf-8').splitlines(),1):
   if not line.strip():continue
   try:expected,rel=line.split('\t',1)
   except ValueError:problems.append('invalid manifest line '+str(lineno));continue
   p=(ROOT/rel).resolve()
   if not p.is_relative_to(ROOT.resolve()):problems.append('unsafe manifest path '+rel);continue
   if not p.is_file() or hashfile(p)!=expected:problems.append('missing/corrupt manifest item: '+rel)
 try:
  import jsonschema
 except ImportError:
  print('NOTE: jsonschema not installed; optional schema validation NOT_RUN')
 else:
  try:
   schema=json.loads((ROOT/'schemas/engineering_intelligence_v1.schema.json').read_text(encoding='utf-8'))
   jsonschema.Draft202012Validator.check_schema(schema)
   v=jsonschema.Draft202012Validator(schema)
   for p in sorted((ROOT/'examples').glob('SYNTHETIC*.json')):
    obj=json.loads(p.read_text(encoding='utf-8'))
    v.validate(obj)
    evid={e['id'] for e in obj['evidence']};ents={e['id'] for e in obj['entities']}
    for ent in obj['entities']:
     if not set(ent['source_evidence_ids']).issubset(evid):problems.append('entity has broken evidence ref: '+ent['id'])
    for rel in obj['relationships']:
     if rel['from_entity_id'] not in ents or rel['to_entity_id'] not in ents:problems.append('relation has missing endpoint '+rel['id'])
     if not set(rel['source_evidence_ids']).issubset(evid):problems.append('relation broken evidence '+rel['id'])
    print('VALID synthetic example:',p.name)
  except Exception as e:problems.append('schema/sample failure: '+repr(e))
 if problems:
  for p in problems:print('ERROR',p,file=sys.stderr)
  print('HANDOFF INTEGRITY: FAIL')
  return 1
 print('HANDOFF INTEGRITY: PASS (does NOT test implementation, Windows, R1 checker, or engineering accuracy)')
 return 0
if __name__=='__main__':sys.exit(main())
