"""Build a reproducible source ZIP for isolated/frozen Python workers."""
from pathlib import Path
import zipfile

def build(root):
    root=Path(root);src=root/'src';dest=root/'packaging/model_lab_worker.zip';dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        def add(name,data):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o644<<16
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED)
        for name in ('pid_reader/__init__.py','pid_reader/engineering/__init__.py','pid_reader/engineering/wp456/__init__.py'):
            add(name,(src/name).read_bytes() if (src/name).is_file() else b'')
        add('pid_reader/engineering/wp456/common.py',(src/'pid_reader/engineering/wp456/common.py').read_bytes())
        for path in sorted((src/'pid_reader/engineering/model_lab').glob('*.py')):add(str(path.relative_to(src)).replace('\\','/'),path.read_bytes())
    return dest

if __name__=='__main__':print(build(Path(__file__).resolve().parents[2]))
