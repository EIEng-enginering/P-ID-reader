"""python -m pid_reader.engineering.wp456 build|score|audit (additive CLI)."""
import argparse
import json
from pathlib import Path
from .pipeline import build,export
from .metrics import score
from .store import Store


def read(path):
    p=Path(path)
    if p.stat().st_size>32*1024*1024: raise ValueError('Input JSON exceeds 32 MiB budget')
    return json.loads(p.read_text(encoding='utf8'))


def main(argv=None):
    p=argparse.ArgumentParser(description='WP04–06 development proposal tools; frozen Worksheet R1 unchanged')
    sub=p.add_subparsers(dest='cmd',required=True)
    b=sub.add_parser('build'); b.add_argument('--wp123',required=True); b.add_argument('--words',required=True)
    b.add_argument('--page-sizes',required=True); b.add_argument('--geometry'); b.add_argument('--output',required=True)
    b.add_argument('--store')
    s=sub.add_parser('score'); s.add_argument('--reference',required=True); s.add_argument('--predictions',required=True)
    s.add_argument('--source-sha256',required=True); s.add_argument('--output',required=True)
    a=sub.add_parser('audit'); a.add_argument('database')
    args=p.parse_args(argv)
    try:
        if args.cmd=='build':
            geometry=read(args.geometry) if args.geometry else {}
            upstream=read(args.wp123)
            if geometry and geometry.get('source_sha256')!=upstream['source_sha256']:
                raise ValueError('Geometry source hash mismatch')
            if geometry and geometry.get('frame')!='MEDIA_NORMALIZED_TOP_LEFT':
                raise ValueError('Geometry coordinate frame mismatch')
            result=build(upstream,read(args.words),page_sizes={int(k):v for k,v in read(args.page_sizes).items()},
                         segments=geometry.get('segments'),ports=geometry.get('ports'),junctions=geometry.get('junctions'),symbol_evidence=geometry.get('symbol_evidence'))
            export(result,args.output)
            if args.store:
                st=Store(args.store)
                try: st.add(result)
                finally: st.close()
            print(json.dumps({'status':'PROPOSED_UNVERIFIED','result_sha256':result['result_sha256']}))
        elif args.cmd=='score':
            result=score(read(args.reference),read(args.predictions),source_sha256=args.source_sha256)
            Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
            print(json.dumps({'status':result['status']}))
        else:
            if not Path(args.database).is_file(): raise ValueError('Audit database does not exist')
            st=Store(args.database)
            try: errors=st.verify()
            finally: st.close()
            print(json.dumps({'errors':errors})); return 1 if errors else 0
    except (ValueError,KeyError,TypeError,OSError) as exc:
        p.exit(2,type(exc).__name__+': '+str(exc)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
