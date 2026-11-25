"""Formatted versions of the Orders exports: a table to preview, and a PDF.

The CSV each export writes is the source: the preview and the PDF are built
from the same rows, so all three always agree. Columns that are blank on
every row are left out of the formatted versions (a printed pull sheet shows
only the sizes this shoot sold); the CSV keeps every column.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path

TITLES = {"pull": "Pull sheet", "crop": "Crop list", "roes": "ROES import file", "items": "Orders"}
MONEY = re.compile(r"^-?\$[\d,]+\.\d\d$")
INT = re.compile(r"^\d+$")
GROUP_BY_TEAM = {"pull", "crop", "items"}


def table(csv_text: str, kind: str) -> dict:
    """The CSV as a table: head, typed rows (row / group / total) and column alignment."""
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if not rows:
        return {"head": [], "rows": [], "align": []}
    head, body = rows[0], [r + [""] * (len(rows[0]) - len(r)) for r in rows[1:]]
    data = [r for r in body if r and r[0] != "TOTAL"]
    total = next((r for r in body if r and r[0] == "TOTAL"), None)
    keep = [i for i in range(len(head)) if any(r[i].strip() for r in data)]
    align = []
    for i in keep:
        vals = [r[i] for r in data if r[i].strip()]
        align.append("money" if vals and all(MONEY.match(v) for v in vals)
                     else "num" if vals and all(INT.match(v) for v in vals) else "text")
    team_col = head.index("Team") if "Team" in head and kind in GROUP_BY_TEAM else None
    out, last = [], object()
    for r in data:
        if team_col is not None and r[team_col] != last:
            last = r[team_col]
            n = sum(1 for x in data if x[team_col] == last)
            out.append({"kind": "group", "label": f"{last or 'No team'}  ·  {n} {'row' if n == 1 else 'rows'}"
                        if kind != "pull" else f"{last or 'No team'}  ·  {n} athlete{'' if n == 1 else 's'}"})
        out.append({"kind": "row", "cells": [r[i] for i in keep]})
    if total:
        out.append({"kind": "total", "cells": [total[i] for i in keep]})
    return {"head": [head[i] for i in keep], "rows": out, "align": align}


def _fit_columns(t: dict, width: float) -> tuple[float, list[float]]:
    """Font size and column widths so numbers and short values never wrap.

    Each column gets at least its longest word (header) and its longest short
    value; long text (names, notes) may wrap. The rest of the page width is
    shared out by how much text each column holds.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    cells = [[r["cells"][i] for r in t["rows"] if r["kind"] != "group"] for i in range(len(t["head"]))]
    pad = 7
    for size in (8.5, 8, 7.5, 7, 6.5, 6):
        sw = lambda s, bold=False: stringWidth(s, "Helvetica-Bold" if bold else "Helvetica", size)
        mins, nats = [], []
        for h, col in zip(t["head"], cells):
            words = [sw(w, True) for w in h.split()] or [0]
            short = [sw(c, True) for c in col if c and (len(c) <= 14 or " " not in c)]
            longw = [sw(w) for c in col for w in c.split()]
            mins.append(max(words + short + longw + [8]) + pad)
            nats.append(min(max([sw(h, True)] + [sw(c) for c in col] + [8]) + pad, 170))
        if sum(mins) <= width or size == 6:
            break
    if not t["head"]:
        return size, [width]
    if sum(nats) <= width:
        return size, [n * width / sum(nats) for n in nats]
    room, extra = width - sum(mins), sum(n - m for n, m in zip(nats, mins)) or 1
    return size, [m + max(room, 0) * (n - m) / extra for m, n in zip(mins, nats)]


def pdf(t: dict, path: Path, title: str, subtitle: str) -> Path:
    """Write the table as a landscape Letter PDF, header row repeated on every page."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from xml.sax.saxutils import escape

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    page = landscape(letter)
    margin = 0.4 * inch
    width = page[0] - 2 * margin
    ncols = max(1, len(t["head"]))
    size, widths = _fit_columns(t, width)
    base = ParagraphStyle("c", fontName="Helvetica", fontSize=size, leading=size * 1.2)
    al = {"money": TA_RIGHT, "num": TA_CENTER, "text": TA_LEFT}
    styles = [ParagraphStyle(f"c{a}", parent=base, alignment=al[a]) for a in t["align"]]
    hstyles = [ParagraphStyle(f"h{a}", parent=s, fontName="Helvetica-Bold") for a, s in zip(t["align"], styles)]

    P = lambda text, st: Paragraph(escape(text), st)
    data = [[P(h, hstyles[i]) for i, h in enumerate(t["head"])]]
    ts = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E8EC")),
          ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#555B66")),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    stripe = 0
    for r in t["rows"]:
        y = len(data)
        if r["kind"] == "group":
            data.append([P(r["label"], ParagraphStyle("g", parent=base, fontName="Helvetica-Bold"))] + [""] * (ncols - 1))
            ts += [("SPAN", (0, y), (-1, y)), ("BACKGROUND", (0, y), (-1, y), colors.HexColor("#F1F3F6")),
                   ("LINEABOVE", (0, y), (-1, y), 0.6, colors.HexColor("#9AA0AA"))]
            stripe = 0
            continue
        bold = r["kind"] == "total"
        data.append([P(c, hstyles[i] if bold else styles[i]) for i, c in enumerate(r["cells"])])
        if bold:
            ts += [("LINEABOVE", (0, y), (-1, y), 1, colors.black), ("BACKGROUND", (0, y), (-1, y), colors.HexColor("#E6E8EC"))]
        else:
            stripe += 1
            if stripe % 2 == 0:
                ts.append(("BACKGROUND", (0, y), (-1, y), colors.HexColor("#FAFAFB")))
            ts.append(("LINEBELOW", (0, y), (-1, y), 0.25, colors.HexColor("#D5D8DE")))

    made = dt.datetime.now().strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#555B66"))
        canvas.drawString(margin, 0.25 * inch, f"{title} · {subtitle}")
        canvas.drawRightString(page[0] - margin, 0.25 * inch, f"Page {doc.page} · made {made}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=0.5 * inch, title=f"{title} - {subtitle}",
                            author="Keeper Studio")
    head = [Paragraph(escape(title), ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=18)),
            Paragraph(escape(subtitle), ParagraphStyle("s", fontName="Helvetica", fontSize=9.5, leading=12,
                                                       textColor=colors.HexColor("#555B66"))),
            Spacer(1, 8)]
    tbl = LongTable(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(TableStyle(ts))
    doc.build(head + [tbl], onFirstPage=furniture, onLaterPages=furniture)
    return path
