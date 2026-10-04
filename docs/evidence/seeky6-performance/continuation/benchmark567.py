"""Rejected or candidate conversion paths, isolated from product source."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

root = Path.cwd()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'scripts'))
from compare_seeky_quality import first_frame
spec = importlib.util.spec_from_file_location('frozen_before', Path(__file__).with_name('frame_edges_before.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
coverage_region = module.coverage_region

functions = {'current': coverage_region}
for name in ('mask_candidate_5', 'mask_candidate_6', 'mask_candidate_7'):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    functions[name] = module.coverage_region
app = QApplication([])
assert app.platformName() == 'cocoa'
img = first_frame(root / 'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm')
rows = []
for size in (832, 1664, 2304):
    canvas = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
        size, round(size * 9 / 16), Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    row = {'width': size}
    reference = coverage_region(canvas)
    before = hashlib.sha256(bytes(canvas.constBits())).hexdigest()
    for name, function in functions.items():
        times = []
        for _ in range(100):
            started = time.perf_counter()
            result = function(canvas)
            times.append(1000 * (time.perf_counter() - started))
            assert (result ^ reference).isEmpty(), name
        row[name + '_median_ms'] = statistics.median(times)
    assert before == hashlib.sha256(bytes(canvas.constBits())).hexdigest()
    rows.append(row)
output = {'command': [sys.executable, str(Path(__file__).resolve())], 'cwd': str(root),
          'setup': 'Cocoa isolated Qt; real HQ premultiplied idle frame',
          'inputs': '832/1664/2304 canvas width, 100 calls per candidate',
          'assertions': 'Every native region equals current product; display bytes untouched',
          'checks': rows, 'exit_status': 0, 'reset': 'Generator closed; no product source changed'}
Path(__file__).with_name('result567.json').write_text(json.dumps(output, indent=2) + '\n')
print(rows)
