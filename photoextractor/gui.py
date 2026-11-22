"""Desktop front end for background removal.

Drop a folder of images, pick where the transparent PNGs go, press Start. All
work happens in core.run, off the UI thread so the window stays responsive.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import core


def _mute(label: QLabel) -> None:
    palette = label.palette()
    palette.setColor(label.foregroundRole(), palette.placeholderText().color())
    label.setPalette(palette)


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


class Worker(QObject):
    progressed = Signal(int, int, str, bool)  # done, total, filename, ok
    finished = Signal(int, int)  # ok_count, total
    failed = Signal(str)

    def __init__(self, images: list[Path], out_dir: Path):
        super().__init__()
        self._images = images
        self._out_dir = out_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            results = core.run(
                self._images,
                self._out_dir,
                on_progress=lambda done, total, r: self.progressed.emit(
                    done, total, r.path.name, r.ok
                ),
                should_cancel=lambda: self._cancelled,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(sum(1 for r in results if r.ok), len(results))


class DropZone(QFrame):
    folderChosen = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        self._active = False
        self._paint()
        layout = QVBoxLayout(self)
        self._label = QLabel("Drop a folder of images here\nor click to choose")
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

    def _paint(self) -> None:
        highlight = self.palette().highlight().color().name()
        muted = self.palette().mid().color().name()
        border = highlight if self._active else muted
        tint = "rgba(74,158,255,28)" if self._active else "transparent"
        self.setStyleSheet(
            f"QFrame {{ border: 2px dashed {border}; border-radius: 10px; "
            f"background: {tint}; }} QLabel {{ border: none; }}"
        )

    def _set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    @staticmethod
    def _folder_from(event) -> Path | None:
        for url in event.mimeData().urls():
            candidate = Path(url.toLocalFile())
            if candidate.is_dir():
                return candidate
        return None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._folder_from(event):
            self._set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        folder = self._folder_from(event)
        if folder:
            self.folderChosen.emit(folder)
            event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder of images")
        if chosen:
            self.folderChosen.emit(Path(chosen))

    def setText(self, text: str) -> None:
        self._label.setText(text)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._input: Path | None = None
        self._output: Path | None = None
        self._images: list[Path] = []
        self._output_explicit = False
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._started_at = 0.0
        self._ok = 0

        self.setWindowTitle("PhotoExtractor — Background Removal")
        self.resize(760, 460)
        self._build()
        self._refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        self._drop = DropZone()
        self._drop.folderChosen.connect(self._set_input)
        outer.addWidget(self._drop)

        self._input_label = QLabel("No folder selected")
        _mute(self._input_label)
        outer.addWidget(self._input_label)

        out_row = QHBoxLayout()
        self._output_label = QLabel("Output: —")
        _mute(self._output_label)
        self._output_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        change = QPushButton("Change…")
        change.clicked.connect(self._choose_output)
        self._reset_output = QPushButton("Use default")
        self._reset_output.clicked.connect(self._use_default_output)
        self._reset_output.setVisible(False)
        out_row.addWidget(self._output_label)
        out_row.addWidget(self._reset_output)
        out_row.addWidget(change)
        outer.addLayout(out_row)

        note = QLabel("Output: transparent PNGs (same filenames). Subject kept, background removed.")
        _mute(note)
        outer.addWidget(note)

        run_row = QHBoxLayout()
        self._start = QPushButton("Start")
        self._start.setMinimumHeight(38)
        self._start.clicked.connect(self._start_job)
        self._cancel = QPushButton("Cancel")
        self._cancel.setMinimumHeight(38)
        self._cancel.clicked.connect(self._cancel_job)
        self._cancel.setVisible(False)
        run_row.addWidget(self._start)
        run_row.addWidget(self._cancel)
        outer.addLayout(run_row)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setMinimumHeight(16)
        outer.addWidget(self._progress)

        self._status = QLabel("")
        font = QFont()
        font.setPointSize(11)
        self._status.setFont(font)
        outer.addWidget(self._status)

        outer.addStretch()
        actions = QHBoxLayout()
        self._open_out = QPushButton("Open output folder")
        self._open_out.clicked.connect(lambda: self._open(self._output))
        actions.addWidget(self._open_out)
        actions.addStretch()
        outer.addLayout(actions)

    def _set_input(self, folder: Path) -> None:
        self._input = folder
        self._images = core.find_images(folder)
        if not self._output_explicit:
            self._output = folder.parent / f"{folder.name}_extracted"
        self._drop.setText(folder.name)
        n = len(self._images)
        self._input_label.setText(f"{folder}  —  {n} image(s)")
        self._update_output_label()
        self._progress.setValue(0)
        self._status.setText("")
        self._refresh()

    def _choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose an output folder")
        if chosen:
            self._output = Path(chosen)
            self._output_explicit = True
            self._update_output_label()
            self._refresh()

    def _use_default_output(self) -> None:
        self._output_explicit = False
        if self._input is not None:
            self._output = self._input.parent / f"{self._input.name}_extracted"
        self._update_output_label()

    def _update_output_label(self) -> None:
        if self._output is None:
            self._output_label.setText("Output: —")
            self._reset_output.setVisible(False)
            return
        origin = "chosen" if self._output_explicit else "default, beside the input folder"
        self._output_label.setText(f"Output: {self._output}    ({origin})")
        self._reset_output.setVisible(self._output_explicit)

    def _refresh(self) -> None:
        running = self._thread is not None
        self._start.setEnabled(bool(self._images) and not running)
        self._drop.setEnabled(not running)
        self._open_out.setEnabled(self._output is not None and self._output.exists())

    def _start_job(self) -> None:
        if not self._images or self._output is None:
            return
        self._started_at = time.monotonic()
        self._ok = 0
        self._progress.setRange(0, 0)  # busy until first result; model loads first
        self._status.setText("Loading model…")

        self._thread = QThread(self)
        self._worker = Worker(self._images, self._output)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

        self._start.setVisible(False)
        self._cancel.setVisible(True)
        self._cancel.setEnabled(True)
        self._refresh()

    def _cancel_job(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._cancel.setEnabled(False)
            self._status.setText("Finishing current image, then stopping…")

    def _on_progress(self, done: int, total: int, filename: str, ok: bool) -> None:
        if self._progress.maximum() == 0:
            self._progress.setRange(0, total)
        if ok:
            self._ok += 1
        self._progress.setValue(done)
        elapsed = time.monotonic() - self._started_at
        remaining = (elapsed / done) * (total - done) if done else 0
        percent = round(100 * done / total) if total else 0
        self._status.setText(
            f"{done}/{total}  ({percent}%)   done {self._ok}   ~{_format_duration(remaining)} left"
        )

    def _on_finished(self, ok_count: int, total: int) -> None:
        self._teardown()
        elapsed = _format_duration(time.monotonic() - self._started_at)
        self._status.setText(f"Done in {elapsed}.   extracted {ok_count}/{total}")
        self._refresh()

    def _on_failed(self, message: str) -> None:
        self._teardown()
        self._status.setText("Failed.")
        QMessageBox.critical(self, "PhotoExtractor", f"The job could not run.\n\n{message}")
        self._refresh()

    def _teardown(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._start.setVisible(True)
        self._cancel.setVisible(False)

    @staticmethod
    def _open(target: Path | None) -> None:
        if target is not None and target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("PhotoExtractor")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
