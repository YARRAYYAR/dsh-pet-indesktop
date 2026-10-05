"""Process-level Qt/WebM ceiling acceptance through the public mouse seam."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_real_qt_manual_ceiling_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, 'scripts/verify_seeky7_interactions.py',
                             '--section', 'ceiling', '--label', 'pytest-ceiling',
                             '--output-dir', str(tmp_path)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=90)
    evidence = tmp_path / 'pytest-ceiling.json'
    assert evidence.is_file(), result.stderr
    record = json.loads(evidence.read_text())
    assert result.returncode == record['exit_status'] == 0, record['errors']
    assert record['evidence_valid']
    assert len(record['checks']) >= 10
