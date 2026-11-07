"""Create/verify a content-hashed, offline, single-ZIP Claude handoff.

No dependencies beyond the standard library. Reject symlinks and exclude build
caches. This is a distribution integrity manifest, not a code-signing signature.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv", "node_modules"}
EXCLUDE_FILES = {"FILE_SHA256.txt", ".DS_Store"}


def files_for_release(root: Path) -> list[Path]:
    found = []
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(x in EXCLUDE_PARTS for x in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink prohibited in handoff: {relative}")
        if path.is_file() and path.name not in EXCLUDE_FILES and path.suffix not in ('.pyc', '.pyo'):
            found.append(relative)
    return sorted(found, key=lambda p: p.as_posix())


def manifest_for(root: Path) -> str:
    return ''.join(f"{sha256((root / p).read_bytes()).hexdigest()}  {p.as_posix()}\n"
                   for p in files_for_release(root))


def verify_archive(archive: Path, root_name: str) -> dict:
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None, "Archive integrity failed"
        names = set(z.namelist())
        assert f'{root_name}/FILE_SHA256.txt' in names, 'Manifest is absent'
        manifest = z.read(f'{root_name}/FILE_SHA256.txt').decode('utf-8')
        seen = set()
        for line in manifest.splitlines():
            expected, rel = line.split('  ', 1)
            assert rel and not rel.startswith('/') and '..' not in Path(rel).parts
            assert rel not in seen, 'Duplicate manifest entry'
            seen.add(rel)
            assert sha256(z.read(f'{root_name}/{rel}')).hexdigest() == expected, f'Content hash differs: {rel}'
        expected_names = {f'{root_name}/{n}' for n in seen} | {f'{root_name}/FILE_SHA256.txt'}
        assert names == expected_names, 'Unmanifested files or missing file in archive'
        return {'sha256': sha256(archive.read_bytes()).hexdigest(),
                'files': len(seen) + 1, 'manifest_entries': len(seen), 'integrity': 'PASS'}


def build(root: Path, destination: Path) -> dict:
    root = root.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite: {destination}')
    manifest = manifest_for(root)
    root_name = root.name
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files_for_release(root):
            arc = f'{root_name}/{path.as_posix()}'
            info = zipfile.ZipInfo(arc, date_time=(2026,11,7,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (root / path).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        info = zipfile.ZipInfo(f'{root_name}/FILE_SHA256.txt', date_time=(2026,11,7,0,0,0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, manifest.encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return verify_archive(destination, root_name)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('output', type=Path)
    args=p.parse_args(argv)
    print(build(ROOT,args.output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
