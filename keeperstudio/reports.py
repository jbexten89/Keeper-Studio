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


# ---------------------------------------------------------------- summary --
def _money(c: int) -> str:
    from .orders import money
    return money(c)


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def shoot_summary(orders: list[dict], catalog, shoot: dict) -> list[dict]:
    """The whole shoot on a few pages: totals, teams, payments, what sold, prints, who owes.

    `orders` carry their `summary` (order_routes adds the lab estimate to it).
    Returns sections, each {"heading", "head", "rows", "align"} like table().
    """
    from .orders import calculate, expand, print_columns

    live = [o for o in orders if o.get("lines")]
    S = lambda o, k: int(o["summary"].get(k) or 0)
    sales, paid = sum(S(o, "total_cents") for o in orders), sum(S(o, "paid_cents") for o in orders)
    lab, ship = sum(S(o, "lab_cents") for o in orders), int(shoot.get("shipping_cents") or 0)
    keep = sales - lab - ship
    row = lambda *c: {"kind": "row", "cells": [str(x) for x in c]}
    tot = lambda *c: {"kind": "total", "cells": [str(x) for x in c]}
    sections = []

    owed = [o for o in orders if S(o, "due_cents") > 0]
    sections.append({"heading": "Totals", "head": ["", "Amount"], "align": ["text", "money"], "rows": [
        row("Envelopes", len(orders)), row("Sales", _money(sales)), row("Collected", _money(paid)),
        row(f"Still due ({len(owed)} envelope{'s' if len(owed) != 1 else ''})", _money(sales - paid)),
        row("Lab cost (Meridian list prices, estimated)", _money(lab)), row("Shipping", _money(ship)),
        tot("You keep", _money(keep)), row("Profit", _pct(keep, sales)),
        row("Average sale per envelope", _money(sales // len(live)) if live else "—")]})

    teams: dict[str, list[dict]] = {}
    for o in orders:
        teams.setdefault(o.get("team") or "No team", []).append(o)
    trows = []
    for name in sorted(teams, key=str.lower):
        os_ = teams[name]
        t_s, t_p, t_l = (sum(S(o, k) for o in os_) for k in ("total_cents", "paid_cents", "lab_cents"))
        trows.append(row(name, len(os_), _money(t_s), _money(t_p), _money(t_s - t_p), _money(t_l), _money(t_s - t_l),
                         _pct(t_s - t_l, t_s)))
    trows.append(tot("TOTAL", len(orders), _money(sales), _money(paid), _money(sales - paid), _money(lab),
                     _money(sales - lab), _pct(sales - lab, sales)))
    sections.append({"heading": "By team (profit before shipping)",
                     "head": ["Team", "Envelopes", "Sales", "Collected", "Due", "Lab", "Profit", "Profit %"],
                     "align": ["text", "num", "money", "money", "money", "money", "money", "money"], "rows": trows})

    methods: dict[str, list[int]] = {}
    for o in orders:
        m = (o.get("paid_method") or "").title() or "Not paid"
        methods.setdefault(m, [0, 0])
        methods[m][0] += 1
        methods[m][1] += S(o, "paid_cents")
    order_m = ["Cash", "Check", "Card", "Other", "Not paid"]
    mrows = [row(m, methods[m][0], _money(methods[m][1])) for m in sorted(methods, key=lambda m: order_m.index(m) if m in order_m else 9)]
    mrows.append(tot("TOTAL", len(orders), _money(paid)))
    sections.append({"heading": "Payments", "head": ["Paid by", "Envelopes", "Collected"],
                     "align": ["text", "num", "money"], "rows": mrows})

    sold: dict[str, list] = {}
    for o in live:
        for l in calculate(o["lines"], catalog)["lines"]:
            p = catalog.by_id.get(l["product_id"])
            name = (p.label if p else l["label"])
            sold.setdefault(l["product_id"], [name, l["type"], 0, 0])
            sold[l["product_id"]][2] += l["qty"]
            sold[l["product_id"]][3] += l["line_cents"]
    kinds = {"package": "Package", "alacarte": "A la carte", "misc": "Keepsake"}
    srows = []
    for pid in [p.id for p in catalog.products if p.id in sold]:
        name, typ, q, c = sold[pid]
        srows.append(row(name, kinds.get(typ, typ), q, _money(c), _pct(c, sales)))
    srows.append(tot("TOTAL", "", sum(v[2] for v in sold.values()), _money(sum(v[3] for v in sold.values())), ""))
    sections.append({"heading": "What sold", "head": ["Item", "Kind", "Qty", "Sales", "Share"],
                     "align": ["text", "text", "num", "money", "money"], "rows": srows})

    prints: dict[str, int] = {}
    misc: dict[str, int] = {}
    mates = 0
    for o in live:
        e = expand(o, catalog)
        for k, n in e["prints"].items():
            prints[k] = prints.get(k, 0) + n
        for k, n in e["misc"].items():
            misc[k] = misc.get(k, 0) + n
        mates += e["mates"]
    prow = [row(label, prints[k]) for k, label in print_columns(catalog) if prints.get(k)]
    prow += [row(p.label, misc[p.id]) for p in catalog.products if misc.get(p.id)]
    if mates:
        prow.append(row("Memory Mates to make", mates))
    sections.append({"heading": "Prints and keepsakes to order", "head": ["Item", "Qty"], "align": ["text", "num"],
                     "rows": prow or [row("Nothing ordered yet", "")]})

    if owed:
        orows = [row(o.get("envelope") or "", o.get("athlete") or "(no name)", o.get("team") or "",
                     _money(S(o, "total_cents")), _money(S(o, "paid_cents")), _money(S(o, "due_cents")),
                     o.get("parent") or "", o.get("phone") or "")
                 for o in sorted(owed, key=lambda o: ((o.get("team") or "").lower(), (o.get("athlete") or "").lower()))]
        orows.append(tot("TOTAL", f"{len(owed)} envelope{'s' if len(owed) != 1 else ''}", "", "", "",
                         _money(sum(S(o, 'due_cents') for o in owed)), "", ""))
        head = ["Env", "Athlete", "Team", "Total", "Paid", "Due", "Parent", "Phone"]
        align = ["num", "text", "text", "money", "money", "money", "text", "text"]
        keep_cols = [i for i in range(len(head)) if i < 6 or any(r["cells"][i] for r in orows)]  # no blank contact columns
        sections.append({"heading": "Still owed", "head": [head[i] for i in keep_cols], "align": [align[i] for i in keep_cols],
                         "rows": [{**r, "cells": [r["cells"][i] for i in keep_cols]} for r in orows]})

    nophoto = [o for o in live if not (o.get("image") or o.get("edited"))]
    if nophoto:
        sections.append({"heading": "Envelopes still needing a photo", "head": ["Env", "Athlete", "Team"],
                         "align": ["num", "text", "text"],
                         "rows": [row(o.get("envelope") or "", o.get("athlete") or "(no name)", o.get("team") or "") for o in nophoto]})
    return sections


def pdf_sections(sections: list[dict], path: Path, title: str, subtitle: str) -> Path:
    """Several headed tables in one portrait Letter PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from xml.sax.saxutils import escape

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    page, margin = letter, 0.55 * inch
    width = page[0] - 2 * margin
    al = {"money": TA_RIGHT, "num": TA_CENTER, "text": TA_LEFT}
    story = [Paragraph(escape(title), ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=20)),
             Paragraph(escape(subtitle), ParagraphStyle("s", fontName="Helvetica", fontSize=10, leading=13,
                                                        textColor=colors.HexColor("#555B66"))),
             Spacer(1, 10)]
    hstyle = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=6, spaceAfter=4)
    for sec in sections:
        t = {"head": sec["head"], "rows": sec["rows"], "align": sec["align"]}
        size, widths = _fit_columns(t, width)
        if len(t["head"]) <= 3:  # short tables don't need the whole page width
            widths = [w * 0.6 for w in widths]
        base = ParagraphStyle("c", fontName="Helvetica", fontSize=size, leading=size * 1.25)
        styles = [ParagraphStyle(f"c{a}", parent=base, alignment=al[a]) for a in t["align"]]
        bold = [ParagraphStyle(f"b{a}", parent=s, fontName="Helvetica-Bold") for a, s in zip(t["align"], styles)]
        data = [[Paragraph(escape(h), bold[i]) for i, h in enumerate(t["head"])]]
        ts = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E8EC")),
              ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#555B66")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        for r in t["rows"]:
            y = len(data)
            b = r["kind"] == "total"
            data.append([Paragraph(escape(c), bold[i] if b else styles[i]) for i, c in enumerate(r["cells"])])
            if b:
                ts += [("LINEABOVE", (0, y), (-1, y), 1, colors.black), ("BACKGROUND", (0, y), (-1, y), colors.HexColor("#E6E8EC"))]
            else:
                ts.append(("LINEBELOW", (0, y), (-1, y), 0.25, colors.HexColor("#D5D8DE")))
        tbl = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        tbl.setStyle(TableStyle(ts))
        block = [Paragraph(escape(sec["heading"]), hstyle), tbl, Spacer(1, 12)]
        story.append(KeepTogether(block) if len(data) < 25 else block[0])
        if len(data) >= 25:
            story += block[1:]

    made = dt.datetime.now().strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")

    def furniture(canvas, doc):
        from reportlab.lib import colors as c
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(c.HexColor("#555B66"))
        canvas.drawString(margin, 0.3 * inch, f"{title} · {subtitle}")
        canvas.drawRightString(page[0] - margin, 0.3 * inch, f"Page {doc.page} · made {made}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=margin,
                            bottomMargin=0.6 * inch, title=f"{title} - {subtitle}", author="Keeper Studio")
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return path
