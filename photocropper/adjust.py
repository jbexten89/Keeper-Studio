"""Manual crop positioning window.

For the odd shot where face-anchored auto framing is wrong -- a raised arm, a
held prop, an unusual pose -- the user opens the image here, drags one crop box
to taste, and every full-length size is written from it. The box is locked to
the widest full-length aspect (4:5), so what is placed here is exactly the
widest crop; narrower sizes sit inside it and the square keeps its own tighter,
face-anchored framing (a raised arm never reaches a hip-high square anyway).

Only the vertical placement (top, height) and horizontal centre of the box
matter downstream; see pipeline.apply_manual_crop.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import imageio, pipeline
from .config import Config

# The widest full-length aspect (4:5 = 8x10). The placement box is locked to it,
# so narrower full-length sizes fit inside the same vertical framing.
REFERENCE_ASPECT = 4 / 5  # width / height
_HANDLE = 22  # px, corner grab region in widget space


def _pil_to_qimage(pil_image) -> QImage:
    """Convert an RGB PIL image to a QImage that owns its buffer."""
    arr = np.ascontiguousarray(np.asarray(pil_image.convert("RGB"), np.uint8))
    h, w, _ = arr.shape
    return QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class CropCanvas(QWidget):
    """Shows the image with a movable, resizable, aspect-locked crop box.

    The box is stored in IMAGE pixel coordinates; painting and hit-testing map
    through the fit-scale. Drag inside to move, drag the bottom-right corner or
    scroll to resize, always clamped inside the image.
    """

    boxChanged = Signal()

    def __init__(self, qimage: QImage):
        super().__init__()
        self._img = qimage
        self._pix = QPixmap.fromImage(qimage)
        self._iw = qimage.width()
        self._ih = qimage.height()
        self.setMinimumSize(480, 600)
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._box = self._default_box()
        self._drag_mode: str | None = None
        self._drag_start = QPointF(0, 0)
        self._box_start = QRectF(self._box)
        self.setMouseTracking(True)

    # ---- box helpers (image coordinates) --------------------------------

    def _default_box(self) -> QRectF:
        """A large centred box to shrink/position from."""
        height = self._ih * 0.95
        width = height * REFERENCE_ASPECT
        if width > self._iw:
            width = self._iw * 0.98
            height = width / REFERENCE_ASPECT
        left = (self._iw - width) / 2
        top = (self._ih - height) / 2
        return QRectF(left, top, width, height)

    def set_box_from_manual(self, manual: dict) -> None:
        height = float(manual["height"])
        width = height * REFERENCE_ASPECT
        left = float(manual["center_x"]) - width / 2
        top = float(manual["top"])
        self._box = self._clamped(QRectF(left, top, width, height))
        self.update()
        self.boxChanged.emit()

    def manual(self) -> dict:
        b = self._box
        return {
            "center_x": b.left() + b.width() / 2.0,
            "top": b.top(),
            "height": b.height(),
            "version": 1,
        }

    def crop_rect(self) -> QRectF:
        return QRectF(self._box)

    def _clamped(self, box: QRectF) -> QRectF:
        """Keep aspect, keep inside the image, keep a sane minimum size."""
        height = max(box.height(), self._ih * 0.1)
        width = height * REFERENCE_ASPECT
        if width > self._iw:
            width = self._iw
            height = width / REFERENCE_ASPECT
        if height > self._ih:
            height = self._ih
            width = height * REFERENCE_ASPECT
        left = min(max(box.left(), 0.0), self._iw - width)
        top = min(max(box.top(), 0.0), self._ih - height)
        return QRectF(left, top, width, height)

    # ---- coordinate mapping ---------------------------------------------

    def _recompute_scale(self) -> None:
        self._scale = min(self.width() / self._iw, self.height() / self._ih)
        dw = self._iw * self._scale
        dh = self._ih * self._scale
        self._offset = QPointF((self.width() - dw) / 2, (self.height() - dh) / 2)

    def _to_widget(self, rect: QRectF) -> QRectF:
        return QRectF(
            self._offset.x() + rect.left() * self._scale,
            self._offset.y() + rect.top() * self._scale,
            rect.width() * self._scale,
            rect.height() * self._scale,
        )

    def _to_image(self, pos) -> QPointF:
        return QPointF(
            (pos.x() - self._offset.x()) / self._scale,
            (pos.y() - self._offset.y()) / self._scale,
        )

    # ---- painting -------------------------------------------------------

    def paintEvent(self, event) -> None:
        self._recompute_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        target = QRectF(self._offset.x(), self._offset.y(), self._iw * self._scale, self._ih * self._scale)
        p.drawPixmap(target, self._pix, QRectF(self._pix.rect()))

        wb = self._to_widget(self._box)
        # Dim everything outside the crop box.
        shade = QColor(0, 0, 0, 120)
        p.setPen(Qt.NoPen)
        p.setBrush(shade)
        p.drawRect(QRectF(target.left(), target.top(), target.width(), wb.top() - target.top()))
        p.drawRect(QRectF(target.left(), wb.bottom(), target.width(), target.bottom() - wb.bottom()))
        p.drawRect(QRectF(target.left(), wb.top(), wb.left() - target.left(), wb.height()))
        p.drawRect(QRectF(wb.right(), wb.top(), target.right() - wb.right(), wb.height()))

        # Crop border + corner handle.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(74, 158, 255), 2))
        p.drawRect(wb)
        p.setBrush(QColor(74, 158, 255))
        p.setPen(Qt.NoPen)
        hs = 12
        p.drawRect(QRectF(wb.right() - hs, wb.bottom() - hs, hs, hs))
        p.end()

    # ---- interaction ----------------------------------------------------

    def _on_handle(self, pos) -> bool:
        wb = self._to_widget(self._box)
        return (
            abs(pos.x() - wb.right()) <= _HANDLE and abs(pos.y() - wb.bottom()) <= _HANDLE
        )

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._drag_start = pos
        self._box_start = QRectF(self._box)
        if self._on_handle(pos):
            self._drag_mode = "resize"
        elif self._to_widget(self._box).contains(pos):
            self._drag_mode = "move"
        else:
            self._drag_mode = None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._drag_mode is None:
            self.setCursor(
                Qt.SizeFDiagCursor if self._on_handle(pos)
                else (Qt.OpenHandCursor if self._to_widget(self._box).contains(pos) else Qt.ArrowCursor)
            )
            return
        d = self._to_image(pos) - self._to_image(self._drag_start)
        if self._drag_mode == "move":
            moved = QRectF(self._box_start)
            moved.translate(d.x(), d.y())
            self._box = self._clamped(moved)
        elif self._drag_mode == "resize":
            new_h = self._box_start.height() + d.y()  # anchor top-left
            new_box = QRectF(self._box_start.left(), self._box_start.top(), new_h * REFERENCE_ASPECT, new_h)
            self._box = self._clamped(new_box)
        self.update()
        self.boxChanged.emit()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = None

    def wheelEvent(self, event) -> None:
        factor = 1.0 - event.angleDelta().y() / 1200.0  # scroll up = zoom in
        center = QPointF(self._box.left() + self._box.width() / 2, self._box.top() + self._box.height() / 2)
        new_h = self._box.height() * factor
        new_w = new_h * REFERENCE_ASPECT
        box = QRectF(center.x() - new_w / 2, center.y() - new_h / 2, new_w, new_h)
        self._box = self._clamped(box)
        self.update()
        self.boxChanged.emit()


class AdjustDialog(QDialog):
    """Position one image's crop by hand, then write every size from it."""

    def __init__(self, path: Path, config: Config, out_dir: Path, enhance: bool | None, parent=None):
        super().__init__(parent)
        self._path = path
        self._config = config
        self._out_dir = out_dir
        self._enhance = enhance
        self.saved = False

        self.setWindowTitle(f"Adjust crop — {path.name}")
        self.resize(1040, 780)

        self._loaded = imageio.load(path)
        qimg = _pil_to_qimage(self._loaded.image)
        self._canvas = CropCanvas(qimg)

        existing = pipeline.load_manual_crop(out_dir, path.stem)
        if existing is not None:
            self._canvas.set_box_from_manual(existing)

        self._preview = QLabel()
        self._preview.setFixedWidth(300)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setStyleSheet("border:1px solid gray; border-radius:6px;")
        self._canvas.boxChanged.connect(self._update_preview)

        info = QLabel(
            "Drag inside the box to move it, drag the blue corner or scroll to resize. "
            "The box is the 8x10 crop; all full-length sizes follow it, and the square "
            "keeps its own tighter framing."
        )
        info.setWordWrap(True)

        save = QPushButton("Save crops for all sizes")
        save.setMinimumHeight(36)
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.setMinimumHeight(36)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        right = QVBoxLayout()
        right.addWidget(QLabel("Preview (8x10):"))
        right.addWidget(self._preview)
        right.addStretch()

        top = QHBoxLayout()
        top.addWidget(self._canvas, stretch=1)
        top.addLayout(right)

        outer = QVBoxLayout(self)
        outer.addWidget(info)
        outer.addLayout(top, stretch=1)
        outer.addLayout(buttons)

        self._update_preview()

    def _update_preview(self) -> None:
        r = self._canvas.crop_rect().toRect()
        crop = self._loaded.image.crop((r.left(), r.top(), r.right(), r.bottom()))
        qp = QPixmap.fromImage(_pil_to_qimage(crop))
        self._preview.setPixmap(
            qp.scaled(self._preview.width() - 6, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _save(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pipeline.apply_manual_crop(
                self._path, self._config, self._out_dir, self._canvas.manual(),
                enhance_override=self._enhance,
            )
            self.saved = True
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()
