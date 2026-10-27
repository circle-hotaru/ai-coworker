"""Run the bridge from this checkout, without global paths or duplicate instances."""
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
server = ROOT / '.build/bridge/main/xiaozhi-server'
if not (server / 'data/.config.yaml').is_file():
    raise SystemExit('Configure data/.config.yaml first; see docs/SETUP.md')
# The upstream loads providers relative to its working directory.
raise SystemExit(subprocess.call([sys.executable, 'app.py'], cwd=server, env=os.environ.copy()))
