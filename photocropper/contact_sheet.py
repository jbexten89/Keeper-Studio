"""Contact sheet generation for QC -- one PNG per ratio, filenames labelled."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit_label(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Middle-ellipsise a filename that will not fit the cell width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        head, tail = text[: (mid + 1) // 2], text[len(text) - mid // 2 :] if mid // 2 else ""
        if draw.textlength(head + ellipsis + tail, font=font) <= max_width:
            low = mid
        else:
            high = mid - 1
    head, tail = text[: (low + 1) // 2], text[len(text) - low // 2 :] if low // 2 else ""
    return head + ellipsis + tail


def build(
    entries: list[tuple[Path, str]],
    destination: Path,
    *,
    columns: int = 6,
    thumb_width: int = 320,
    padding: int = 14,
    label_height: int = 26,
    font_size: int = 15,
    background: tuple[int, int, int] = (32, 32, 34),
    text_colour: tuple[int, int, int] = (238, 238, 238),
) -> Path | None:
    """Render `entries` as a grid. Returns the written path, or None if empty."""
    if not entries:
        return None

    columns = max(1, int(columns))
    font = _load_font(font_size)

    # All crops in a sheet share a ratio, so one cell height fits every image.
    with Image.open(entries[0][0]) as probe:
        aspect = probe.height / probe.width
    thumb_height = max(1, round(thumb_width * aspect))

    cell_w = thumb_width + padding
    cell_h = thumb_height + padding + label_height
    rows = (len(entries) + columns - 1) // columns

    sheet = Image.new(
        "RGB",
        (columns * cell_w + padding, rows * cell_h + padding),
        background,
    )
    draw = ImageDraw.Draw(sheet)

    for index, (path, label) in enumerate(entries):
        row, column = divmod(index, columns)
        x = padding + column * cell_w
        y = padding + row * cell_h

        with Image.open(path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((thumb_width, thumb_height), Image.LANCZOS)
            sheet.paste(thumb, (x + (thumb_width - thumb.width) // 2, y))

        text = _fit_label(draw, label, font, thumb_width)
        text_width = draw.textlength(text, font=font)
        draw.text(
            (x + (thumb_width - text_width) / 2, y + thumb_height + 6),
            text,
            fill=text_colour,
            font=font,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG")
    return destination
