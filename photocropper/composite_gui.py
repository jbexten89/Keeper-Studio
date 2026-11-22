"""The "Build Composite" screen: a dialog that collects the folders, title,
fonts and options, then builds one class composite off the UI thread.

Layout and cropping live in `composite.build_composite`; this only drives it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import imageio
from .composite import build_composite
from .config import Config

FONT_FILTER = "Fonts (*.ttf *.otf *.ttc)"
_FONT_DIR = "C:/Windows/Fonts"


class _CompositeWorker(QObject):
    done = Signal(object)   # output Path
    failed = Signal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            out = build_composite(**self._kwargs)
        except Exception as exc:  # surfaced in a dialog
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(out)


class _PathRow:
    """A label + read-only field + Browse button for one path input."""

    def __init__(self, grid: QGridLayout, row: int, label: str, *, pick_dir: bool,
                 pick_save: bool = False, filt: str = "", start: str = ""):
        self.pick_dir = pick_dir
        self.pick_save = pick_save
        self.filt = filt
        self.start = start
        self.value = ""
        grid.addWidget(QLabel(label), row, 0, Qt.AlignRight)
        self.field = QLineEdit()
        self.field.setReadOnly(not (pick_save or not pick_dir))
        grid.addWidget(self.field, row, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        grid.addWidget(btn, row, 2)

    def _browse(self) -> None:
        if self.pick_dir:
            got = QFileDialog.getExistingDirectory(None, "Choose folder", self.start)
        elif self.pick_save:
            got, _ = QFileDialog.getSaveFileName(None, "Save composite as",
                                                 self.start, "JPEG (*.jpg)")
        else:
            got, _ = QFileDialog.getOpenFileName(None, "Choose file", self.start, self.filt)
        if got:
            self.set(got)

    def set(self, path: str) -> None:
        self.value = path
        self.field.setText(path)

    def get(self) -> str:
        return self.field.text().strip() or self.value


class CompositeDialog(QDialog):
    """Collects inputs and builds a composite."""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._thread: QThread | None = None
        self.setWindowTitle("Build Composite")
        self.setMinimumWidth(640)
        c = dict(config.composite or {})

        outer = QVBoxLayout(self)
        intro = QLabel(
            "Build one 5×7 class composite. Pick a folder of student photos and a "
            "folder of teacher photos (file names become the names shown), the "
            "background template, and the title. Students are ordered by last name; "
            "teachers by a leading number in the file name (e.g. \"1 Mrs Miller\")."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        r = 0
        self._teachers = _PathRow(grid, r, "Teachers folder:", pick_dir=True); r += 1
        self._students = _PathRow(grid, r, "Students folder:", pick_dir=True); r += 1
        self._bg = _PathRow(grid, r, "Background template:", pick_dir=False,
                            filt="Images (*.jpg *.jpeg *.png)"); r += 1

        grid.addWidget(QLabel("School name:"), r, 0, Qt.AlignRight)
        self._school = QLineEdit(str(c.get("school_name", "")))
        grid.addWidget(self._school, r, 1, 1, 2); r += 1

        grid.addWidget(QLabel("Year:"), r, 0, Qt.AlignRight)
        self._year = QLineEdit()
        self._year.setPlaceholderText("e.g. 2025-2026")
        grid.addWidget(self._year, r, 1, 1, 2); r += 1

        # Options row: max per row + uppercase.
        grid.addWidget(QLabel("Max per row:"), r, 0, Qt.AlignRight)
        opt = QHBoxLayout()
        self._maxcols = QSpinBox()
        self._maxcols.setRange(1, 20)
        self._maxcols.setValue(int(c.get("max_per_row", 8)))
        self._maxcols.setToolTip(
            "Most students in one row. The class is split into as few rows as this "
            "allows (fuller rows at the bottom); the grid shrinks to fit."
        )
        opt.addWidget(self._maxcols)
        self._upper = QCheckBox("UPPERCASE student names (Stencil look)")
        self._upper.setChecked(bool(c.get("name_uppercase", True)))
        opt.addWidget(self._upper)
        opt.addStretch()
        grid.addLayout(opt, r, 1, 1, 2); r += 1

        # Optional: exact students per row, top to bottom. Overrides Max per row.
        grid.addWidget(QLabel("Students per row:"), r, 0, Qt.AlignRight)
        self._per_row = QLineEdit()
        self._per_row.setPlaceholderText("optional, e.g. 6, 6, 6  (top to bottom) — blank = auto")
        self._per_row.setToolTip(
            "Set the exact number in each row, top to bottom, separated by commas "
            "(e.g. 5, 6, 7). They must add up to the number of students. Leave blank "
            "to use Max per row instead."
        )
        grid.addWidget(self._per_row, r, 1, 1, 2); r += 1

        # Fonts.
        self._title_font = _PathRow(grid, r, "Title / teacher font:", pick_dir=False,
                                    pick_save=False, filt=FONT_FILTER, start=_FONT_DIR); r += 1
        self._teacher_font = _PathRow(grid, r, "Teacher-name font:", pick_dir=False,
                                      filt=FONT_FILTER, start=_FONT_DIR); r += 1
        self._name_font = _PathRow(grid, r, "Student-name font:", pick_dir=False,
                                   filt=FONT_FILTER, start=_FONT_DIR); r += 1
        self._title_font.set(str(c.get("title_font", "")))
        self._teacher_font.set(str(c.get("teacher_font", c.get("title_font", ""))))
        self._name_font.set(str(c.get("name_font", "")))

        self._out = _PathRow(grid, r, "Save as:", pick_dir=False, pick_save=True,
                             filt="JPEG (*.jpg)"); r += 1

        self._status = QLabel("")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._build_btn = QPushButton("Build")
        self._build_btn.setMinimumHeight(34)
        self._build_btn.clicked.connect(self._build)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        buttons.addWidget(self._build_btn)
        outer.addLayout(buttons)

        # Default the output next to the students folder once it is chosen.
        self._students.field.textChanged.connect(self._suggest_output)

    def _suggest_output(self) -> None:
        if self._out.get():
            return
        sdir = self._students.get()
        if sdir:
            name = (self._school.text().strip() or "composite")
            yr = self._year.text().strip()
            fn = f"{name} {yr}".strip() + " composite.jpg"
            self._out.set(str(Path(sdir).parent / fn))

    def _build(self) -> None:
        students_dir = self._students.get()
        teachers_dir = self._teachers.get()
        bg = self._bg.get()
        errors = []
        if not students_dir or not Path(students_dir).is_dir():
            errors.append("Choose a students folder.")
        if not bg or not Path(bg).is_file():
            errors.append("Choose a background template image.")
        for lbl, p in (("Title/teacher", self._title_font.get()),
                       ("Teacher-name", self._teacher_font.get()),
                       ("Student-name", self._name_font.get())):
            if not p or not Path(p).is_file():
                errors.append(f"{lbl} font file not found.")
        if not self._out.get():
            errors.append("Choose where to save the composite.")
        if errors:
            QMessageBox.warning(self, "Missing information", "\n".join(errors))
            return

        students = imageio.find_images(Path(students_dir))
        teachers = imageio.find_images(Path(teachers_dir)) if teachers_dir and Path(teachers_dir).is_dir() else []
        if not students:
            QMessageBox.warning(self, "No students", f"No images found in {students_dir}.")
            return

        # Optional exact per-row counts.
        row_counts = None
        raw = self._per_row.text().strip()
        if raw:
            try:
                row_counts = [int(p) for p in raw.replace(",", " ").split()]
            except ValueError:
                QMessageBox.warning(self, "Students per row",
                                    "Enter whole numbers separated by commas, e.g. 6, 6, 6.")
                return
            if sum(row_counts) != len(students):
                QMessageBox.warning(
                    self, "Students per row",
                    f"Your rows add up to {sum(row_counts)}, but there are "
                    f"{len(students)} student photo(s). Make them match.")
                return

        title_lines = [self._school.text().strip(), self._year.text().strip()]
        kwargs = dict(
            bg_path=Path(bg), out_path=Path(self._out.get()),
            title_lines=title_lines, teacher_files=teachers, student_files=students,
            title_font_path=self._title_font.get(),
            italic_font_path=self._teacher_font.get(),
            name_font_path=self._name_font.get(),
            config=self._config, max_cols=self._maxcols.value(),
            name_uppercase=self._upper.isChecked(),
            row_counts=row_counts,
        )
        self._build_btn.setEnabled(False)
        self._status.setText(f"Building composite from {len(students)} student(s) "
                             f"and {len(teachers)} teacher(s)…")

        self._thread = QThread(self)
        self._worker = _CompositeWorker(kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._build_btn.setEnabled(True)

    def _on_done(self, out: Path) -> None:
        self._cleanup()
        self._status.setText(f"Saved: {out}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def _on_failed(self, message: str) -> None:
        self._cleanup()
        self._status.setText("")
        QMessageBox.critical(self, "Composite failed", message)
