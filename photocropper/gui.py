"""Desktop front end.

Drag a folder in, watch it run, triage whatever could not be cropped. All
cropping happens in `pipeline.run_job`; this module only drives it and shows
results, so the GUI and the CLI cannot disagree about what a crop is.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import imageio, pipeline
from .adjust import AdjustDialog
from .cli import DEFAULT_CONFIG
from .config import Config, ConfigError, load as load_config


def _mute(label: QLabel) -> None:
    """Render a label as secondary text using the palette, not a fixed colour."""
    palette = label.palette()
    palette.setColor(label.foregroundRole(), palette.placeholderText().color())
    label.setPalette(palette)


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


class JobWorker(QObject):
    """Runs a job off the UI thread so the window stays responsive."""

    progressed = Signal(int, int, str, str)  # done, total, filename, status
    finished = Signal(object)  # JobSummary
    failed = Signal(str)

    def __init__(
        self, images: list[Path], out_dir: Path, config: Config,
        enhance: bool | None = None, balance: bool | None = None, sheets: bool | None = None,
        enhance_when: str | None = None, bottom_margin: float | None = None,
        preschool: bool | None = None,
    ):
        super().__init__()
        self._images = images
        self._out_dir = out_dir
        self._config = config
        self._enhance = enhance
        self._balance = balance
        self._sheets = sheets
        self._enhance_when = enhance_when
        self._bottom_margin = bottom_margin
        self._preschool = preschool
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            summary = pipeline.run_job(
                self._images,
                self._out_dir,
                self._config,
                on_progress=lambda done, total, result: self.progressed.emit(
                    done, total, result.path.name, result.status
                ),
                should_cancel=lambda: self._cancelled,
                enhance_override=self._enhance,
                enhance_when_override=self._enhance_when,
                balance_override=self._balance,
                bottom_margin_override=self._bottom_margin,
                preschool_override=self._preschool,
                build_sheets=self._sheets,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(summary)


class DropZone(QFrame):
    """Folder drop target. Also clickable, since drag is not everyone's habit."""

    folderChosen = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setCursor(Qt.PointingHandCursor)
        self._active = False
        self._paint()

        layout = QVBoxLayout(self)
        self._label = QLabel("Drop a folder of photos here\nor click to choose")
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

    def _paint(self) -> None:
        # Colours come from the palette rather than fixed hex, so the window
        # reads correctly under both light and dark system themes.
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
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder of photos")
        if chosen:
            self.folderChosen.emit(Path(chosen))

    def setText(self, text: str) -> None:
        self._label.setText(text)


class MainWindow(QWidget):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._input: Path | None = None
        self._output: Path | None = None
        self._images: list[Path] = []
        self._output_explicit = False
        """True once a destination has been chosen by hand. A chosen folder
        must survive loading a different input folder -- silently reverting to
        a default beside the new input would export to the wrong place."""
        self._summary: pipeline.JobSummary | None = None
        self._thread: QThread | None = None
        self._worker: JobWorker | None = None
        self._started_at = 0.0
        self._counts = {"ok": 0, "review": 0}

        self.setWindowTitle("PhotoCropper")
        self.resize(940, 720)
        self._build()
        self._refresh_controls()

    # ---------------------------------------------------------------- layout

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

        ratios = ", ".join(r.name for r in self._config.ratios)
        sizes_text = f"Sizes: {ratios}"
        if self._config.landscape_enabled and self._config.landscape_ratios:
            land = ", ".join(r.name for r in self._config.landscape_ratios)
            sizes_text += f"   |   Landscape group shots → {land}"
        sizes_text += "   (edit config.yaml to change)"
        sizes = QLabel(sizes_text)
        sizes.setWordWrap(True)
        _mute(sizes)
        outer.addWidget(sizes)

        # Enhancement toggle, set before each run. Defaults to the config value;
        # disabled when no preset LUT is configured so it cannot be turned on
        # only to fail at run time.
        enhance_row = QHBoxLayout()
        self._enhance_check = QCheckBox("Enhance photos (apply colour preset)")
        has_lut = self._config.enhance_lut_path is not None
        self._enhance_check.setChecked(self._config.enhance_enabled and has_lut)
        self._enhance_check.setEnabled(has_lut)
        if not has_lut:
            self._enhance_check.setText(
                "Enhance photos — no preset configured (set enhance.lut_path in config.yaml)"
            )
        self._enhance_when = QComboBox()
        self._enhance_when.addItem("before cropping", "before")
        self._enhance_when.addItem("after cropping", "after")
        self._enhance_when.setCurrentIndex(0 if self._config.enhance_when == "before" else 1)
        self._enhance_check.toggled.connect(self._refresh_controls)
        enhance_row.addWidget(self._enhance_check)
        enhance_row.addWidget(self._enhance_when)
        enhance_row.addStretch()
        outer.addLayout(enhance_row)

        # Feet-balanced framing toggle. Disabled when no pose model is configured.
        balance_row = QHBoxLayout()
        self._balance_check = QCheckBox(
            "Balance feet on full-body sizes (equal top/bottom margins)"
        )
        has_pose = self._config.pose_model_path is not None
        self._balance_check.setChecked(self._config.balance_feet and has_pose)
        self._balance_check.setEnabled(has_pose)
        if not has_pose:
            self._balance_check.setText(
                "Balance feet — no pose model configured (set pose.model_path in config.yaml)"
            )
        self._balance_check.toggled.connect(self._refresh_controls)
        self._bottom_margin = QDoubleSpinBox()
        self._bottom_margin.setRange(5.0, 45.0)
        self._bottom_margin.setSingleStep(1.0)
        self._bottom_margin.setSuffix("% bottom")
        self._bottom_margin.setToolTip(
            "Bottom (feet) margin. Raise it to leave room below a prop the feet "
            "rest on, e.g. a soccer ball (~22%)."
        )
        self._bottom_margin.setValue(round(self._config.bottom_margin_fraction * 100, 1))
        balance_row.addWidget(self._balance_check)
        balance_row.addWidget(self._bottom_margin)
        balance_row.addStretch()
        outer.addLayout(balance_row)

        # Preschool (seated) framing: a tighter 3/4 crop with the bottom at the
        # lap, for seated preschool portraits. Replaces the full-length framing
        # on every size; feet-balancing does not apply, so it greys out when on.
        self._preschool_check = QCheckBox("Preschool photos (seated 3/4 crop)")
        self._preschool_check.setChecked(self._config.preschool)
        self._preschool_check.setToolTip(
            "Seated preschool framing: eyes high in the frame, bottom cut at the "
            "lap. Use for seated preschool portraits instead of the full-length look."
        )
        self._preschool_check.toggled.connect(self._refresh_controls)
        outer.addWidget(self._preschool_check)

        # Contact sheets are a QC preview only; let them be skipped for speed.
        self._sheets_check = QCheckBox("Make contact sheets (QC preview)")
        self._sheets_check.setChecked(bool(self._config.contact_sheet.get("enabled", True)))
        outer.addWidget(self._sheets_check)

        # Composite builder -- a separate task from cropping, so it is its own
        # button that opens the Build Composite screen.
        self._composite_btn = QPushButton("Build Composite…")
        self._composite_btn.setToolTip(
            "Build a 5×7 class composite (teachers + students on the backdrop)."
        )
        self._composite_btn.clicked.connect(self._open_composite)
        outer.addWidget(self._composite_btn)

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

        self._review_header = QLabel("Needs review")
        header_font = QFont()
        header_font.setBold(True)
        self._review_header.setFont(header_font)
        outer.addWidget(self._review_header)

        splitter = QSplitter(Qt.Horizontal)
        review_side = QWidget()
        review_layout = QVBoxLayout(review_side)
        review_layout.setContentsMargins(0, 0, 0, 0)
        self._review_list = QListWidget()
        self._review_list.setMinimumWidth(300)
        self._review_list.currentItemChanged.connect(self._show_review_detail)
        # Double-click a flagged photo to open it straight in the crop editor.
        self._review_list.itemDoubleClicked.connect(self._adjust_review_item)
        self._adjust_selected = QPushButton("Adjust selected photo")
        self._adjust_selected.setToolTip(
            "Open the selected photo in the crop editor and write every size from "
            "your placement."
        )
        self._adjust_selected.setEnabled(False)
        self._adjust_selected.clicked.connect(self._adjust_selected_photo)
        review_layout.addWidget(self._review_list)
        review_layout.addWidget(self._adjust_selected)
        splitter.addWidget(review_side)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self._thumb = QLabel("Select an image to see why it was skipped")
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setMinimumHeight(240)
        self._thumb.setStyleSheet(
            f"border: 1px solid {self.palette().mid().color().name()}; border-radius: 6px;"
        )
        self._reason = QTextEdit()
        self._reason.setReadOnly(True)
        self._reason.setMinimumHeight(150)
        detail_layout.addWidget(self._thumb)
        detail_layout.addWidget(self._reason)
        splitter.addWidget(detail)
        splitter.setSizes([320, 620])
        outer.addWidget(splitter, stretch=1)

        actions = QHBoxLayout()
        self._adjust = QPushButton("Adjust a photo…")
        self._adjust.setToolTip(
            "Hand-position the crop for one photo (e.g. a raised-arm pose) and "
            "write every size from it."
        )
        self._adjust.clicked.connect(self._adjust_photo)
        self._open_out = QPushButton("Open output folder")
        self._open_out.clicked.connect(lambda: self._open(self._output))
        self._open_sheet = QPushButton("Open contact sheet")
        self._open_sheet.clicked.connect(self._open_contact_sheet)
        actions.addWidget(self._adjust)
        actions.addWidget(self._open_out)
        actions.addWidget(self._open_sheet)
        actions.addStretch()
        outer.addLayout(actions)

    # ------------------------------------------------------------- selection

    def _set_input(self, folder: Path) -> None:
        self._input = folder
        self._images = imageio.find_images(folder)
        if not self._output_explicit:
            self._output = folder.parent / f"{folder.name}_out"
        self._drop.setText(folder.name)
        if self._images:
            self._input_label.setText(f"{folder}  —  {len(self._images)} JPEG(s)")
        else:
            self._input_label.setText(f"{folder}  —  no JPEGs found in this folder")
        self._update_output_label()
        self._reset_results()
        self._refresh_controls()

    def _choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose an output folder")
        if chosen:
            self._output = Path(chosen)
            self._output_explicit = True
            self._update_output_label()

    def _use_default_output(self) -> None:
        self._output_explicit = False
        if self._input is not None:
            self._output = self._input.parent / f"{self._input.name}_out"
        self._update_output_label()

    def _update_output_label(self) -> None:
        if self._output is None:
            self._output_label.setText("Output: —")
            self._reset_output.setVisible(False)
            return
        origin = "chosen" if self._output_explicit else "default, beside the input folder"
        self._output_label.setText(f"Output: {self._output}    ({origin})")
        self._reset_output.setVisible(self._output_explicit)

    def _refresh_controls(self) -> None:
        running = self._thread is not None
        self._start.setEnabled(bool(self._images) and not running)
        self._drop.setEnabled(not running)
        can_enhance = not running and self._config.enhance_lut_path is not None
        self._enhance_check.setEnabled(can_enhance)
        self._enhance_when.setEnabled(can_enhance and self._enhance_check.isChecked())
        self._preschool_check.setEnabled(not running)
        # Preschool is a seated mode, so feet-balancing does not apply; grey it
        # out while preschool is on to make the two mutually exclusive.
        preschool_on = self._preschool_check.isChecked()
        can_balance = not running and self._config.pose_model_path is not None and not preschool_on
        self._balance_check.setEnabled(can_balance)
        self._bottom_margin.setEnabled(can_balance and self._balance_check.isChecked())
        self._sheets_check.setEnabled(not running)
        has_output = self._output is not None and self._output.exists()
        self._open_out.setEnabled(has_output)
        self._open_sheet.setEnabled(bool(self._summary and self._summary.sheets))
        self._adjust.setEnabled(self._output is not None and not running)

    def _open_composite(self) -> None:
        from .composite_gui import CompositeDialog

        CompositeDialog(self._config, self).exec()

    def _reset_results(self) -> None:
        self._summary = None
        self._counts = {"ok": 0, "review": 0}
        self._review_list.clear()
        self._reason.clear()
        self._thumb.setText("Select an image to see why it was skipped")
        self._thumb.setPixmap(QPixmap())
        self._review_header.setText("Needs review")
        self._adjust_selected.setEnabled(False)
        self._progress.setValue(0)
        self._status.setText("")

    # ------------------------------------------------------------------- run

    def _start_job(self) -> None:
        if not self._images or self._output is None:
            return
        self._reset_results()
        self._started_at = time.monotonic()
        # Busy-mode until the first image lands. Loading the detector model
        # takes a few seconds, and an empty bar with no text reads as frozen.
        self._progress.setRange(0, 0)
        self._status.setText("Loading face detector…")

        self._thread = QThread(self)
        self._worker = JobWorker(
            self._images, self._output, self._config,
            enhance=self._enhance_check.isChecked(),
            balance=self._balance_check.isChecked(),
            sheets=self._sheets_check.isChecked(),
            enhance_when=self._enhance_when.currentData(),
            bottom_margin=self._bottom_margin.value() / 100.0,
            preschool=self._preschool_check.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

        self._start.setVisible(False)
        self._cancel.setVisible(True)
        self._cancel.setEnabled(True)
        self._refresh_controls()

    def _cancel_job(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._cancel.setEnabled(False)
            self._status.setText("Finishing current image, then stopping…")

    def _on_progress(self, done: int, total: int, filename: str, status: str) -> None:
        if self._progress.maximum() == 0:  # leaving busy-mode on the first result
            self._progress.setRange(0, total)
        if status == pipeline.OK:
            self._counts["ok"] += 1
        else:
            self._counts["review"] += 1

        self._progress.setValue(done)
        elapsed = time.monotonic() - self._started_at
        remaining = (elapsed / done) * (total - done) if done else 0
        percent = round(100 * done / total) if total else 0
        self._status.setText(
            f"{done}/{total}  ({percent}%)   cropped {self._counts['ok']}   "
            f"review {self._counts['review']}   ~{_format_duration(remaining)} left"
        )

    def _on_finished(self, summary: pipeline.JobSummary) -> None:
        self._summary = summary
        self._teardown_thread()

        for result in summary.review:
            item = QListWidgetItem(
                f"{result.path.name}\n    {pipeline.STATUS_LABELS.get(result.status, result.status)}"
            )
            item.setData(Qt.UserRole, str(result.path))
            item.setData(Qt.UserRole + 1, result.reason or "")
            self._review_list.addItem(item)

        elapsed = _format_duration(time.monotonic() - self._started_at)
        note = "Cancelled" if summary.cancelled else "Done"
        parts = [
            f"{note} in {elapsed}.",
            f"cropped {summary.count(pipeline.OK)}",
        ]
        if summary.adjusted:
            # Good crops, but framed tighter than configured. Saying so keeps
            # the shortening from being a silent change.
            parts.append(f"{len(summary.adjusted)} shortened to fit")
        parts.append(f"needs review {len(summary.review)}")
        medians = summary.framing_medians()
        if medians:
            # Bottom edge is a result of eye line and headroom, not a setting,
            # so surfacing it is how framing gets calibrated.
            parts.append(f"bottom edge {medians[1]:.2f} head-heights below crown")
        self._status.setText("   ".join(parts))
        self._review_header.setText(f"Needs review ({len(summary.review)})")
        self._refresh_controls()

    def _on_failed(self, message: str) -> None:
        self._teardown_thread()
        self._status.setText("Failed.")
        QMessageBox.critical(self, "PhotoCropper", f"The job could not run.\n\n{message}")
        self._refresh_controls()

    def _teardown_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._start.setVisible(True)
        self._cancel.setVisible(False)

    # ---------------------------------------------------------------- review

    def _show_review_detail(self, current: QListWidgetItem | None, _previous=None) -> None:
        self._adjust_selected.setEnabled(current is not None)
        if current is None:
            return
        self._reason.setPlainText(current.data(Qt.UserRole + 1))
        source = Path(current.data(Qt.UserRole))
        pixmap = QPixmap(str(source))
        if pixmap.isNull():
            self._thumb.setText("Preview unavailable")
            return
        self._thumb.setPixmap(
            pixmap.scaled(
                QSize(self._thumb.width() - 12, self._thumb.height() - 12),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def _adjust_selected_photo(self) -> None:
        self._adjust_review_item(self._review_list.currentItem())

    def _adjust_review_item(self, item: QListWidgetItem | None) -> None:
        if item is not None:
            self._open_adjust(Path(item.data(Qt.UserRole)), item)

    def _adjust_photo(self) -> None:
        start_dir = str(self._input) if self._input else ""
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose a photo to position by hand", start_dir,
            "JPEG images (*.jpg *.jpeg *.JPG *.JPEG)",
        )
        if chosen:
            self._open_adjust(Path(chosen))

    def _open_adjust(self, path: Path, item: QListWidgetItem | None = None) -> None:
        """Open one photo in the crop editor; on save, write all sizes.

        When `item` is a review-list entry, drop it from the list once it has
        been positioned, since it is no longer waiting on a manual crop.
        """
        if self._output is None:
            QMessageBox.information(
                self, "PhotoCropper", "Load an input folder first so there is an output to write to."
            )
            return
        enhance = self._enhance_check.isChecked() if self._enhance_check.isEnabled() else None
        dialog = AdjustDialog(path, self._config, self._output, enhance, self)
        dialog.exec()
        if dialog.saved:
            if item is not None:
                row = self._review_list.row(item)
                if row >= 0:
                    self._review_list.takeItem(row)
                    self._review_header.setText(f"Needs review ({self._review_list.count()})")
            self._status.setText(
                f"Saved a hand-positioned crop for {path.name} across all sizes."
            )
            self._refresh_controls()

    def _open_contact_sheet(self) -> None:
        if self._summary and self._summary.sheets:
            self._open(self._summary.sheets[0])

    @staticmethod
    def _open(target: Path | None) -> None:
        if target is not None and target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("PhotoCropper")

    try:
        config = load_config(DEFAULT_CONFIG)
    except ConfigError as exc:
        QMessageBox.critical(None, "PhotoCropper", f"Configuration problem:\n\n{exc}")
        return 2

    window = MainWindow(config)
    window.show()

    if config.warnings:
        QMessageBox.warning(None, "PhotoCropper", "\n\n".join(config.warnings))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
