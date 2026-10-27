"""Create disposable source workspaces from pinned public upstreams and overlays."""
import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]

def materialize(name, source=None):
    info = json.loads((ROOT / 'upstreams.json').read_text())[name]
    target = ROOT / '.build' / name
    if target.exists():
        raise ValueError(f'{target} already exists; choose a fresh workspace')
    target.parent.mkdir(parents=True, exist_ok=True)
    if source:
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', info['commit']], text=True).strip()
        if actual != info['commit']:
            raise ValueError('Source does not contain the pinned commit')
        archive = subprocess.check_output(['git', '-C', str(source), 'archive', info['commit']])
        # Extract only regular files/directories. Public workspaces contain no symlinks.
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            members = bundle.getmembers()
            if any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute() or '..' in Path(m.name).parts for m in members):
                raise ValueError('Unsafe upstream archive member')
            target.mkdir()
            for member in members:
                dest = target / member.name
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as stream:
                        dest.write_bytes(stream.read())
                    dest.chmod(member.mode & 0o777)
    else:
        subprocess.run(['git','init','-q',str(target)], check=True)
        subprocess.run(['git','-C',str(target),'fetch','--depth=1',info['url'],info['commit']], check=True)
        actual = subprocess.check_output(['git','-C',str(target),'rev-parse','FETCH_HEAD'], text=True).strip()
        if actual != info['commit']:
            raise ValueError('Unexpected upstream commit')
        subprocess.run(['git','-C',str(target),'checkout','--detach','FETCH_HEAD'], check=True)
    overlay = ROOT / 'overlays' / name
    for p in overlay.rglob('*'):
        if p.is_symlink(): raise ValueError('Overlay symlink rejected')
        if p.is_file():
            dest = target / p.relative_to(overlay)
            if dest.is_symlink() or any(x.is_symlink() for x in dest.parents):
                raise ValueError('Destination symlink rejected')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
    print(f'{name}: pinned sources and overlay ready')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['firmware','bridge'])
    parser.add_argument('--source', type=Path, help='Optional local public upstream Git repository; only its pinned tree is exported')
    args = parser.parse_args()
    materialize(args.component, args.source)
