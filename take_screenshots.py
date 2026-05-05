#!/usr/bin/env python3
"""Auto-capture screenshots of each editor tab. Run with the editor's venv Python."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap
from fe9_editor import MainWindow

GCM = '/Volumes/RayCue/Dolphin/NGC-火焰之纹章～苍炎之轨迹--中文版.gcm'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs/screenshots')
os.makedirs(OUT, exist_ok=True)

app = QApplication(['screenshot'])
win = MainWindow(GCM)
win.resize(1500, 900)
win.show()
for _ in range(8):
    app.processEvents()

names = ['1-jobs', '2-persons', '3-items', '4-reliance', '5-kizna', '6-divine']
for i in range(min(win.tabs.count(), len(names))):
    win.tabs.setCurrentIndex(i)
    for _ in range(8):
        app.processEvents()
    pixmap = win.grab()
    path = os.path.join(OUT, f'{names[i]}.png')
    pixmap.save(path)
    print(f'Saved {path}  ({pixmap.size().width()}x{pixmap.size().height()})')
print('Done.')
