"""Counterbalanced real QWidget mask application and paint cost."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

root = Path.cwd()
sys.path[:0] = [str(root), str(root / 'scripts')]
from compare_seeky_quality import first_frame
from pet.frame_edges import coverage_region

spec = importlib.util.spec_from_file_location('frozen_before', Path(__file__).with_name('frame_edges_before.py'))
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)
app = QApplication([])
assert app.platformName() == 'cocoa'
source = first_frame(root / 'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm')
source = source.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(832, 468, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
canvases = []
for offset in (0, 1):
    canvas = QImage(834, 470, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage(offset, 1, source)
    painter.end()
    assert (frozen.coverage_region(canvas) ^ coverage_region(canvas)).isEmpty()
    canvases.append(canvas)

class Panel(QWidget):
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.canvas)

panel = Panel()
panel.setAttribute(Qt.WA_TranslucentBackground)
panel.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
panel.resize(834, 470)
panel.canvas = canvases[0]
panel.show()
app.processEvents()
timings = {'before': [], 'after': []}
for index in range(100):
    ordered = [('before', frozen.coverage_region), ('after', coverage_region)]
    if index % 2:
        ordered.reverse()
    for position, (label, function) in enumerate(ordered):
        canvas = canvases[position]
        started = time.perf_counter()
        panel.canvas = canvas
        panel.setMask(function(canvas))
        panel.update()
        app.processEvents()
        timings[label].append(1000 * (time.perf_counter() - started))
panel.close()
app.processEvents()
record = {'command': [sys.executable, str(Path(__file__).resolve())], 'cwd': str(root),
          'setup': 'Cocoa native QWidget; frozen published seeky.6 versus current source, 100 counterbalanced rounds',
          'inputs': 'Same real HQ first frame, two 1px shifted canvases; mask changes every operation',
          'assertions': 'Coverage XOR empty; time includes computation/setMask/paint/event dispatch',
          'checks': {label: {'median_ms': statistics.median(values), 'p95_ms': sorted(values)[94], 'samples': values} for label, values in timings.items()},
          'canvas_sha256': [hashlib.sha256(bytes(c.constBits())).hexdigest() for c in canvases],
          'exit_status': 0, 'reset': 'Generator closed and temporary native panel closed; user config unchanged'}
Path(__file__).with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n')
print({label: values['median_ms'] for label, values in record['checks'].items()})
