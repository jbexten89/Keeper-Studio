"""Class-composite builder: one 5x7 (landscape, 7:5) collage per class.

A composite is a title, the teachers in the top corners, and the students in
centred rows, all laid over a background template (the gray studio backdrop with
its white inset border already drawn). Each source is a raw frame that is
re-cropped here to a head-and-shoulders cell -- a tighter crop than the portrait
sizes the main pipeline produces, measured from the reference composite.

Nothing here touches the cropping pipeline; it only reuses the face detector and
the crop solver to frame each cell.

Ordering, by the photographer's choice:
  * students  -- alphabetical by LAST name (the last word of the file name);
  * teachers  -- by an optional leading number in the file name ("1 Ms Sheila"),
                 which also sets which slot they take, then stripped from the
                 label shown.

Teacher placement by count: 1 -> left; 2 -> one each side; 3 -> one left, two
stacked right; 4 -> two stacked each side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import detectors, imageio
from .config import Config
from .geometry import estimate_crown


class CompositeError(Exception):
    pass


@dataclass(frozen=True)
class CellStyle:
    """Head-crop framing + aspect for one kind of cell (student or teacher).

    The crop is anchored on HEAD HEIGHT (crown to chin): the head is cut to a
    fixed `head_fraction` of the cell height, so every head comes out the same
    size once the cells are the same size. `headroom` places the crown down from
    the top of the cell.
    """

    aspect_w: int
    aspect_h: int
    headroom: float        # crown position, as a fraction of cell height
    head_fraction: float   # head height (crown->chin) as a fraction of cell height


# Students are framed head-and-shoulders in a 4:5 cell; teachers (adults) a
# touch looser in a taller 2:3 cell. head_fraction fixes the head size so all
# heads match; the values reproduce the reference framing.
STUDENT_CELL = CellStyle(4, 5, headroom=0.20, head_fraction=0.43)
TEACHER_CELL = CellStyle(2, 3, headroom=0.11, head_fraction=0.39)


@dataclass(frozen=True)
class Layout:
    """All positions/sizes as fractions of the background canvas.

    Defaults are measured from the 2000x1429 reference composite, so a canvas of
    any size with the same 7:5 proportions reproduces that layout.
    """

    student_cell_w: float = 202 / 2000
    student_cell_h: float = 257 / 1429
    teacher_cell_w: float = 202 / 2000
    teacher_cell_h: float = 303 / 1429
    pitch_x: float = 224 / 2000
    # Student rows live in this vertical band (first photo top .. last photo
    # bottom); the block is centred in it and photos are made as large as the
    # band and the bottom-row width allow.
    band_top: float = 512 / 1429
    band_bottom: float = 1255 / 1429
    row_gap: float = 16 / 1429     # name bottom -> next row's photo top (kept tight)
    border_inset: float = 0.045    # white border, as a fraction of width
    teacher_top: float = 166 / 1429
    teacher_left_cx: float = 292 / 2000
    teacher_right_cx: float = 1714 / 2000
    teacher_pair_gap: float = 24 / 2000  # gap between two teachers on one side
    name_gap: float = 9 / 1429  # photo bottom -> name top (names sit close)
    title_cx: float = 0.5
    title_y1: float = 312 / 1429
    title_y2: float = 404 / 1429
    title_size: float = 62 / 1429
    name_size: float = 25 / 1429
    teacher_name_size: float = 26 / 1429
    # Per-cell finish.
    keyline_px: float = 2 / 2000      # thin white edge around each photo
    shadow_offset: float = 7 / 2000   # drop-shadow offset (down-right)
    shadow_blur: float = 9 / 2000
    shadow_alpha: int = 130
    text_color: tuple = (255, 255, 255)


_NUM_PREFIX = re.compile(r"^\s*(\d+)[\s._\-]*")


def _label_and_order(stem: str) -> tuple[int | None, str]:
    """Split an optional leading number (order) from the label to display."""
    m = _NUM_PREFIX.match(stem)
    if m:
        return int(m.group(1)), stem[m.end():].strip()
    return None, stem.strip()


def _last_name_key(path: Path) -> tuple[str, str]:
    """Sort key: last word of the file name, then the whole name."""
    stem = path.stem.strip()
    words = stem.split()
    last = words[-1].lower() if words else stem.lower()
    return (last, stem.lower())


def _teacher_key(path: Path) -> tuple[int, str]:
    order, _ = _label_and_order(path.stem)
    # Teachers without a number sort after numbered ones, then alphabetically.
    return (order if order is not None else 10_000, path.stem.lower())


def _head_crop(source, face, cell: CellStyle, mult: float) -> Image.Image:
    """Crop one raw so the head is a fixed fraction of the cell.

    The crop height is set from the head height (crown to chin), not the eye
    line, so every subject's head ends up the same size once the cells are the
    same size. The crown sits `headroom` down from the top, and the frame is
    centred horizontally on the eyes. Shrinks to fit if the ideal box would run
    off the source.
    """
    iw, ih = source.size
    aspect = cell.aspect_w / cell.aspect_h
    eye_x, _ = face.eye_mid
    crown_x, crown_y = estimate_crown(face, mult)
    head = face.chin[1] - crown_y
    if head <= 1:
        return _center_crop(source.image, cell)
    height = head / cell.head_fraction
    width = aspect * height
    if height > ih or width > iw:  # too big for the source: shrink, keep aspect
        scale = min(ih / height, iw / width)
        height *= scale
        width *= scale
    top = crown_y - cell.headroom * height
    left = eye_x - width / 2.0
    # Keep the box inside the image (shifts, never distorts).
    left = max(0.0, min(left, iw - width))
    top = max(0.0, min(top, ih - height))
    box = (int(round(left)), int(round(top)),
           int(round(left + width)), int(round(top + height)))
    return source.image.crop(box)


def _center_crop(img: Image.Image, cell: CellStyle) -> Image.Image:
    """Fallback when no face is found: centre-crop to the cell aspect."""
    w, h = img.size
    aspect = cell.aspect_w / cell.aspect_h
    if w / h > aspect:
        nw = int(round(h * aspect)); x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(round(w / aspect)); y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def _make_tile(path: Path, cell: CellStyle, cell_px: tuple[int, int], detector, mult: float,
               keyline: int) -> Image.Image:
    source = imageio.load(path)
    faces = detector.detect(source.as_rgb_array())
    if faces:
        face = max(faces, key=lambda f: f.interocular)
        crop = _head_crop(source, face, cell, mult)
    else:
        crop = _center_crop(source.image, cell)
    tile = crop.resize(cell_px, Image.LANCZOS).convert("RGB")
    if keyline > 0:
        tile = ImageOps.expand(tile, border=keyline, fill=(245, 245, 245))
    return tile


def _paste_with_shadow(canvas: Image.Image, tile: Image.Image, x: int, y: int,
                       dx: int, dy: int, blur: int, alpha: int) -> None:
    w, h = tile.size
    pad = blur * 2 + max(dx, dy) + 2
    sh = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([pad, pad, pad + w, pad + h], fill=(0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh, (x - pad + dx, y - pad + dy))
    canvas.alpha_composite(tile.convert("RGBA"), (x, y))


def _distribute(n: int, max_cols: int) -> list[int]:
    """Rows top->bottom: the BOTTOM row holds max_cols, the upper row(s) share
    the rest (balanced, fuller rows lower). So max_cols sets the bottom row and
    the class fills upward -- a smaller max_cols makes bigger photos."""
    if n <= 0:
        return []
    if n <= max_cols:
        return [n]
    remaining = n - max_cols
    upper_rows = -(-remaining // max_cols)  # ceil
    base, rem = divmod(remaining, upper_rows)
    upper = [base] * (upper_rows - rem) + [base + 1] * rem  # fuller rows lower
    return upper + [max_cols]


def _fit_font_size(path: str, labels: list[str], base_px: int, max_w: float,
                   floor: int = 8) -> int:
    """Largest size <= base_px at which every label's width is <= max_w.

    Keeps the name font uniform across the row (like the reference) instead of
    shrinking only the long names, and stops a long name running into its
    neighbour.
    """
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = max(floor, base_px)
    while size > floor:
        f = ImageFont.truetype(path, size)
        if all(probe.textlength(t, font=f) <= max_w for t in labels):
            break
        size -= 1
    return size


def _teacher_slots(n: int) -> list[tuple[str, int]]:
    """Return (side, index_within_side) per teacher slot, in file order.

    side is 'L' or 'R'; index 0 is the only/top one on that side.
    """
    if n <= 1:
        return [("L", 0)]
    if n == 2:
        return [("L", 0), ("R", 0)]
    if n == 3:
        return [("L", 0), ("R", 0), ("R", 1)]
    return [("L", 0), ("L", 1), ("R", 0), ("R", 1)]  # 4 (extra teachers ignored)


def build_composite(
    bg_path: Path,
    out_path: Path,
    *,
    title_lines: list[str],
    teacher_files: list[Path],
    student_files: list[Path],
    title_font_path: str,
    italic_font_path: str,
    name_font_path: str,
    config: Config,
    layout: Layout = Layout(),
    max_cols: int = 8,
    name_uppercase: bool = True,
    row_counts: list[int] | None = None,
) -> Path:
    """Build one composite and save it as a JPEG. Returns the output path.

    `row_counts`, when given, sets the exact number of students in each row, top
    to bottom (e.g. [6, 6, 6]); they must add up to the number of students.
    Otherwise `max_cols` caps how many go in a row and the class is split into as
    few rows as that allows (the fuller rows at the bottom). `name_uppercase`
    upper-cases student names (the Stencil look); turn it off for a Title-case
    serif look. The grid auto-shrinks to fit the canvas, so any class size and
    row count stays inside the border.
    """
    if row_counts is not None:
        if any(c <= 0 for c in row_counts):
            raise CompositeError("each row count must be a positive number.")
        total = sum(row_counts)
        if total != len(student_files):
            raise CompositeError(
                f"the per-row counts add up to {total}, but there are "
                f"{len(student_files)} student photo(s); make them match."
            )
    bg = Image.open(bg_path).convert("RGBA")
    W, H = bg.size
    canvas = bg

    def px_w(f): return int(round(f * W))
    def px_h(f): return int(round(f * H))

    detector = detectors.build(config.detector["name"], config.detector)
    mult = config.eye_to_chin_multiplier
    try:
        key = int(round(layout.keyline_px * W))
        dx = dy = int(round(layout.shadow_offset * W))
        blur = max(1, int(round(layout.shadow_blur * W)))
        alpha = layout.shadow_alpha
        draw = ImageDraw.Draw(canvas)

        def font(path, frac):
            return ImageFont.truetype(path, px_h(frac))

        title_font = font(title_font_path, layout.title_size)

        # ---- Title (centred, two lines) -----------------------------------
        for text, yf in zip(title_lines, (layout.title_y1, layout.title_y2)):
            if text:
                draw.text((px_w(layout.title_cx), px_h(yf)), text, font=title_font,
                          fill=layout.text_color, anchor="mm")

        def place(path: Path, label: str, cell: CellStyle, cw: int, ch: int,
                  cx: int, cy: int, fnt, upper: bool) -> None:
            tile = _make_tile(path, cell, (cw, ch), detector, mult, key)
            tw, th = tile.size
            x, y = cx - tw // 2, cy - th // 2
            _paste_with_shadow(canvas, tile, x, y, dx, dy, blur, alpha)
            text = label.upper() if upper else label
            # Anchor the name by its TOP, a small fixed gap under the photo, so
            # the label sits close to the picture regardless of cell size.
            draw.text((cx, y + th + px_h(layout.name_gap)), text, font=fnt,
                      fill=layout.text_color, anchor="ma")

        # ---- Teachers (top corners) ---------------------------------------
        # 1-2 teachers: full cell, one per side, in the corners. 3-4 teachers sit
        # SIDE BY SIDE (up to two per side), each side's group centred in the
        # clear space between the title and the border. The cells are made as
        # large as that space allows (up to the full size), so they stay big.
        teachers = sorted(teacher_files, key=_teacher_key)
        n_t = len(teachers)
        slots = _teacher_slots(n_t)
        pair_gap = px_w(layout.teacher_pair_gap)
        tcw_full = px_w(layout.teacher_cell_w)
        side_count = {"L": sum(1 for s, _ in slots if s == "L"),
                      "R": sum(1 for s, _ in slots if s == "R")}
        if n_t <= 2:
            tcw = tcw_full
            side_x = {"L": px_w(layout.teacher_left_cx), "R": px_w(layout.teacher_right_cx)}
        else:
            title_w = max((draw.textlength(t, font=title_font) for t in title_lines if t),
                          default=0.0)
            title_left = W / 2 - title_w / 2
            title_right = W / 2 + title_w / 2
            border_l = W * layout.border_inset
            border_r = W * (1 - layout.border_inset)
            side_x = {"L": int(round((border_l + title_left) / 2)),
                      "R": int(round((title_right + border_r) / 2))}
            side_gap = {"L": title_left - border_l, "R": border_r - title_right}
            pad = px_w(0.012)
            # Cap the width so a pair fits any side that holds two teachers.
            tcw = float(tcw_full)
            for side, cnt in side_count.items():
                if cnt == 2:
                    tcw = min(tcw, (side_gap[side] - 2 * pad - pair_gap) / 2.0)
            tcw = int(round(max(px_w(0.06), tcw)))
        tch = int(round(tcw * TEACHER_CELL.aspect_h / TEACHER_CELL.aspect_w))
        teacher_labels = [_label_and_order(p.stem)[1] for p in teachers]
        name_maxw = tcw * 1.7 if n_t <= 2 else (tcw + pair_gap)
        italic_font = ImageFont.truetype(
            italic_font_path,
            _fit_font_size(italic_font_path, teacher_labels or [""],
                           px_h(layout.teacher_name_size), name_maxw),
        )
        cy = px_h(layout.teacher_top) + tch // 2
        for path, (side, idx) in zip(teachers, slots):
            _, label = _label_and_order(path.stem)
            n_side = side_count[side]
            cx = side_x[side] + int(round((idx - (n_side - 1) / 2.0) * (tcw + pair_gap)))
            place(path, label, TEACHER_CELL, tcw, tch, cx, cy, italic_font, upper=False)

        # ---- Students (centred rows, by last name) ------------------------
        students = sorted(student_files, key=_last_name_key)
        rows = list(row_counts) if row_counts is not None else _distribute(len(students), max_cols)
        nrows = len(rows)
        maxk = max(rows) if rows else 0

        # Make the photos as large as possible: a cell is capped only by the
        # bottom-row width and by the band height with rows packed tight (just a
        # name and a small gap between rows). The row block is then centred in
        # the band. Fewer-per-row and fewer rows => bigger photos.
        s_aspect = STUDENT_CELL.aspect_w / STUDENT_CELL.aspect_h  # width/height
        cw0 = px_w(layout.student_cell_w)
        gap_ratio = layout.pitch_x / layout.student_cell_w - 1.0  # pitch = cw*(1+gap)

        avail_w = W * 0.89
        band_top = px_h(layout.band_top)
        band_bottom = px_h(layout.band_bottom)
        band = band_bottom - band_top
        # Space each row needs below its photo (name + gap to the next photo).
        row_extra = px_h(layout.name_gap) + px_h(layout.name_size) + px_h(layout.row_gap)

        cw = float(cw0)
        if maxk:
            cw = min(cw, avail_w / (maxk + (maxk - 1) * gap_ratio))  # fit width
        ch = cw / s_aspect
        if nrows:
            ch_v = (band - (nrows - 1) * row_extra) / nrows  # fit height, tight rows
            if ch > ch_v:
                ch = ch_v
                cw = ch * s_aspect
        cw, ch = int(round(cw)), int(round(ch))
        gap_px = int(round(gap_ratio * cw))
        pitchpx = cw + gap_px
        pitch_row = ch + row_extra
        ch0 = cw0 / s_aspect
        name_px = max(10, int(round(px_h(layout.name_size) * ch / ch0)))
        # One name size for the whole class: the largest that keeps every name
        # inside its column.
        labels = [(st.stem.upper() if name_uppercase else st.stem) for st in students]
        name_font = ImageFont.truetype(
            name_font_path,
            _fit_font_size(name_font_path, labels or [""], name_px, pitchpx * 0.96),
        )
        # Centre the whole block of rows in the band.
        block_h = nrows * ch + (nrows - 1) * row_extra if nrows else 0
        block_top = band_top + (band - block_h) / 2.0
        it = iter(students)
        for r, k in enumerate(rows):
            cy = int(round(block_top + r * pitch_row)) + ch // 2
            startx = W // 2 - ((k - 1) * pitchpx) // 2
            for i in range(k):
                path = next(it)
                place(path, path.stem, STUDENT_CELL, cw, ch, startx + i * pitchpx, cy,
                      name_font, upper=name_uppercase)
    finally:
        detector.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=95)
    return out_path
