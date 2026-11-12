"""Run new tests inside the merged repository with core+Qt environment."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+str(ROOT/'tests')
env['QT_QPA_PLATFORM']='offscreen'
raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q','tests/wp07','tests/wp456',
                                 'tests/test_wp456_frames.py','tests/test_wp456_gui.py'],cwd=ROOT,env=env))
