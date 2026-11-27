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


def shoot_summary(orders: list[dict], catalog, shoot: dict, extras: list[dict] | None = None) -> list[dict]:
    """The whole shoot on a few pages: totals, teams, payments, what sold, prints, who owes.

    `orders` carry their `summary` (order_routes adds the lab estimate to it).
    Returns sections, each {"heading", "head", "rows", "align"} like table().
    """
    from .orders import calculate, expand, print_columns

    live = [o for o in orders if o.get("lines")]
    S = lambda o, k: int(o["summary"].get(k) or 0)
    sales, paid = sum(S(o, "total_cents") for o in orders), sum(S(o, "paid_cents") for o in orders)
    lab, ship = sum(S(o, "lab_cents") for o in orders), int(shoot.get("shipping_cents") or 0)
    extras = extras or []
    X = lambda k: sum(int(e["summary"].get(k) or 0) for e in extras)
    fam_sales = sales
    sales, paid, lab = sales + X("sales_cents"), paid + X("paid_cents"), lab + X("lab_cents")
    keep = sales - lab - ship
    row = lambda *c: {"kind": "row", "cells": [str(x) for x in c]}
    tot = lambda *c: {"kind": "total", "cells": [str(x) for x in c]}
    sections = []

    owed = [o for o in orders if S(o, "due_cents") > 0]
    ex_owed = [e for e in extras if e["summary"]["due_cents"] > 0]
    owe_n = len(owed) + len(ex_owed)
    sales_rows = [row("Sales", _money(sales))]
    if extras:
        sales_rows += [row("    Families", _money(fam_sales)), row(f"    School & other orders ({len(extras)})", _money(X("sales_cents")))]
    sections.append({"heading": "Totals", "head": ["", "Amount"], "align": ["text", "money"], "rows": [
        row("Envelopes", len(orders)), *sales_rows, row("Collected", _money(paid)),
        row(f"Still due ({owe_n} {'order' if extras else 'envelope'}{'s' if owe_n != 1 else ''})", _money(sales - paid)),
        *([row(f"Accepted short ({sum(1 for o in orders if S(o, 'short_cents'))} envelopes, not in sales)", _money(S_short))] if (S_short := sum(S(o, "short_cents") for o in orders)) else []),
        *([row(f"Change still to give back ({sum(1 for o in orders if S(o, 'change_cents'))})", _money(S_change))] if (S_change := sum(S(o, "change_cents") for o in orders)) else []),
        row("Lab cost (Meridian list prices, estimated)", _money(lab)), row("Shipping", _money(ship)),
        tot("You keep", _money(keep)), row("Profit", _pct(keep, sales)),
        row("Average sale per envelope", _money(fam_sales // len(live)) if live else "—")]})

    if extras:
        erows = []
        for e in extras:
            su = e["summary"]
            what = "; ".join(_extra_item_text(it) for it in e.get("items") or [])
            erows.append(row(e["who"], what, su["prints"], "Free" if su["free"] else _money(su["sales_cents"]),
                             _money(su["paid_cents"]), _money(su["due_cents"]) if su["due_cents"] else "",
                             _money(su["lab_cents"])))
        erows.append(tot("TOTAL", "", X("prints"), _money(X("sales_cents")), _money(X("paid_cents")),
                         _money(X("due_cents")), _money(X("lab_cents"))))
        sections.append({"heading": "School & other orders", "head": ["For", "What", "Prints", "Sales", "Paid", "Due", "Lab"],
                         "align": ["text", "text", "num", "money", "money", "money", "money"], "rows": erows})

    teams: dict[str, list[dict]] = {}
    for o in orders:
        teams.setdefault(o.get("team") or "No team", []).append(o)
    trows = []
    from .orders import by_team_order
    for name in by_team_order(teams, orders):
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
        from .orders import paid_label
        m = paid_label(o)
        methods.setdefault(m, [0, 0])
        methods[m][0] += 1
        methods[m][1] += S(o, "paid_cents")
    order_m = ["Picture day", "Cash", "Check", "Venmo", "Card", "Other", "Not paid"]
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
                 for o in sorted(owed, key=lambda o: (int(o.get("team_rank", 10_000)), (o.get("team") or "").lower(), (o.get("athlete") or "").lower()))]
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


def _extra_item_text(it: dict, with_qty: bool = True) -> str:
    from .extras import SHORT
    prod = SHORT.get(it.get("product") or "", "Print")
    what = f"{it.get('size', '')} {prod.lower()}"
    if it.get("src") == "teams":
        c = {t: int(n or 0) for t, n in (it.get("counts") or {}).items() if int(n or 0) > 0}
        each = set(c.values())
        if len(each) == 1:
            n = next(iter(each))
            return f"{what} of each team photo{f' x {n}' if n > 1 and with_qty else ''} ({', '.join(c)})"
        return f"{what}: " + ", ".join(f"{t} x {n}" for t, n in c.items())
    src = f"{it.get('team')} team photo" if it.get("src") == "team" else (it.get("label") or it.get("image") or "photo")
    q = int(it.get("qty") or 0)
    return f"{what} of {src}{f' x {q}' if q > 1 and with_qty else ''}"


def invoice_pdf(order: dict, summary: dict, shoot: dict, path: Path) -> Path:
    """A one-page invoice for a school or other order."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from .extras import item_qty

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    P = lambda t, **k: Paragraph(escape(str(t)), ParagraphStyle("x", fontName=k.get("f", "Helvetica"),
                                                                 fontSize=k.get("s", 10), leading=k.get("s", 10) * 1.3,
                                                                 alignment=k.get("a", 0),
                                                                 textColor=colors.HexColor(k.get("c", "#111111"))))
    today = dt.date.today().strftime("%B %d, %Y").replace(" 0", " ")
    day = shoot.get("date") or ""
    try:
        day = dt.date.fromisoformat(day).strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        pass
    shoot_bits = " · ".join(b for b in [shoot.get("name") or "", day] if b)
    story = [Table([[P("Jamie Bexten Photography", f="Helvetica-Bold", s=15), P("INVOICE", f="Helvetica-Bold", s=18, a=TA_RIGHT)],
                    [P("Bryan, Ohio", c="#555B66"), P(f"No. {shoot.get('id', 0)}-{order['id']}   ·   {today}", a=TA_RIGHT, c="#555B66")]],
                   colWidths=[3.9 * inch, 3.4 * inch]),
             Spacer(1, 18), P("Bill to", f="Helvetica-Bold", s=9, c="#555B66"),
             P(order.get("customer") or order.get("kind") or ""),
             *([P(order["contact"], c="#333333")] if order.get("contact") else []),
             Spacer(1, 6), P(f"Picture day: {shoot_bits}", c="#333333"), Spacer(1, 14)]
    rows = [[P(h, f="Helvetica-Bold", s=9.5, a=TA_RIGHT if i else 0) for i, h in enumerate(["Item", "Qty", "Each", "Amount"])]]
    for it in order.get("items") or []:
        q = item_qty(it)
        if q <= 0:
            continue
        price = int(it.get("price_cents") or 0)
        txt = _extra_item_text(it, with_qty=False)
        rows.append([P(txt[:1].upper() + txt[1:], s=9.5), P(q, s=9.5, a=TA_RIGHT),
                     P("No charge" if not price else _money(price), s=9.5, a=TA_RIGHT),
                     P("—" if not price else _money(price * q), s=9.5, a=TA_RIGHT)])
    n = len(rows)
    rows += [["", "", P("Total", f="Helvetica-Bold", a=TA_RIGHT), P(_money(summary["sales_cents"]), f="Helvetica-Bold", a=TA_RIGHT)],
             ["", "", P("Paid", a=TA_RIGHT), P(_money(summary["paid_cents"]), a=TA_RIGHT)],
             ["", "", P("Balance due", f="Helvetica-Bold", a=TA_RIGHT), P(_money(summary["due_cents"]), f="Helvetica-Bold", a=TA_RIGHT)]]
    t = Table(rows, colWidths=[4.4 * inch, 0.6 * inch, 1.1 * inch, 1.2 * inch], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#555B66")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E8EC")),
                           ("LINEBELOW", (0, 1), (-1, n - 1), 0.25, colors.HexColor("#D5D8DE")),
                           ("LINEABOVE", (2, n), (-1, n), 1, colors.black),
                           ("LINEABOVE", (2, n + 2), (-1, n + 2), 0.6, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 20)]
    if summary["paid_cents"]:
        how = (order.get("paid_method") or "").title() + (f" #{order['check_no']}" if order.get("check_no") else "")
        story.append(P(f"Received {_money(summary['paid_cents'])}{' by ' + how if how else ''}. Thank you!", c="#333333"))
    if summary["due_cents"]:
        story.append(P(f"Balance due: {_money(summary['due_cents'])}. Please make checks payable to Jamie Bexten Photography.",
                       c="#333333"))
    if order.get("notes"):
        story += [Spacer(1, 8), P(order["notes"], c="#333333")]
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch, title="Invoice", author="Jamie Bexten Photography")
    doc.build(story)
    return path


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


# ---------------------------------------------------------- matching sheets --
def envelope_contents(order: dict, catalog) -> str:
    """What goes in one envelope, as prints: '1× 8x10 · 2× 5x7 · 2 wallet sheets · 1× team 5x7 · Keychain'."""
    from .orders import MEMORY_MATE, PRINT_SIZES, expand
    e = expand(order, catalog)
    bits = []
    for key in sorted(e["prints"], key=lambda k: (":team" in k, -PRINT_SIZES.get(k.split(":")[0], {}).get("w", 0) * PRINT_SIZES.get(k.split(":")[0], {}).get("h", 0))):
        n = e["prints"][key]
        size, _, team = key.partition(":")
        if not n or size == MEMORY_MATE:
            continue
        sz = PRINT_SIZES.get(size, {"label": size})
        if sz.get("sheet"):
            bits.append(f"{n} {sz['label'].lower()} sheet{'s' if n != 1 else ''}" + (" (team)" if team else ""))
        else:
            bits.append(f"{n}× {'team ' if team else ''}{sz['label']}")
    if e["mates"]:
        bits.append(f"{e['mates']} memory mate{'s' if e['mates'] != 1 else ''} to assemble")
    for pid, packs in e["misc"].items():
        p = catalog.get(pid)
        bits.append(f"{packs}× {p.label}" if packs > 1 else p.label)
    return " · ".join(bits)


def matching_pdf(shoot: dict, orders: list[dict], catalog, extras: list[dict], team_photos: dict,
                 find_photo, path: Path, business: str = "Jamie Bexten Photography") -> Path:
    """One page per team: each envelope's photo, number and contents, in stuffing order,
    so prints that come back from the lab without numbers can be matched by eye.

    find_photo(stem) gives the photo's path on this computer, or None.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from .library import thumbnail
    from .orders import _env_num, expand, order_summary, paid_label

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    P = lambda t, **k: Paragraph(t if k.get("raw") else escape(str(t)), ParagraphStyle(
        "x", fontName=k.get("f", "Helvetica"), fontSize=k.get("s", 10), leading=k.get("s", 10) * 1.25,
        alignment=k.get("a", 0), textColor=colors.HexColor(k.get("c", "#111111"))))

    def pic(stem, w, h):
        p = find_photo(stem) if stem else None
        if not p:
            return P("—", c="#999999", a=1)
        try:
            img = Image(io.BytesIO(thumbnail(str(p), 300)))
            iw, ih = img.imageWidth, img.imageHeight
            r = min(w / iw, h / ih)
            img.drawWidth, img.drawHeight = iw * r, ih * r
            return img
        except Exception:  # noqa: BLE001 - a missing thumbnail never stops the sheet
            return P("—", c="#999999", a=1)

    day = shoot.get("date") or ""
    try:
        day = dt.date.fromisoformat(day).strftime("%b %d, %Y").replace(" 0", " ")
    except ValueError:
        pass
    teams: dict[str, list] = {}
    for o in sorted((o for o in orders if o.get("lines")), key=lambda o: (int(o.get("team_rank", 10_000)), str(o.get("team") or "").lower(), _env_num(o.get("envelope")))):
        teams.setdefault(o.get("team") or "No team", []).append(o)
    story = []
    W = 7.5 * inch
    for team, rows in teams.items():
        sums = [order_summary(o, catalog) for o in rows]
        team_envs = [str(o.get("envelope") or "?") for o in rows if any(":" in k for k in expand(o, catalog)["prints"])]
        owe = [(o, s) for o, s in zip(rows, sums) if s.get("due_cents", 0) > 0]
        envs = [str(o.get("envelope") or "") for o in rows]
        coach = next((o.get("coach") for o in rows if o.get("coach")), "")
        head_left = [P(team, f="Helvetica-Bold", s=20),
                     P(" · ".join(x for x in [shoot.get("name") or "", f"Picture day {day}" if day else "", f"Coach {coach}" if coach else ""] if x), c="#555555", s=10),
                     Spacer(1, 6),
                     P(f"<b>{len(rows)} envelope{'s' if len(rows) != 1 else ''}</b> · #{escape(', #'.join(e for e in envs if e))}", raw=True, s=11),
                     P(("Team photo prints in envelopes " + ", ".join(team_envs)) if team_envs else "No team photo prints", s=9.5, c="#333333"),
                     *([P(f"{len(owe)} still owe{'s' if len(owe) == 1 else ''} {_money(sum(s['due_cents'] for _, s in owe))}", s=9.5, c="#B06A00")] if owe else [])]
        timg = pic(team_photos.get(team, ""), 2.3 * inch, 1.5 * inch)
        story.append(Table([[head_left, [timg, P(f"Team photo · {team_photos.get(team) or 'not picked'}", s=8, c="#666666", a=2)]]],
                           colWidths=[W - 2.4 * inch, 2.4 * inch],
                           style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                             ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.black), ("BOTTOMPADDING", (0, 0), (-1, 0), 10)])))
        story.append(Spacer(1, 6))
        data = [[P(h, f="Helvetica-Bold", s=8, c="#666666") for h in ["", "PHOTO", "ENV #", "WHAT GOES IN IT", "PHOTO #", "PAID"]]]
        for o, s in zip(rows, sums):
            stem = o.get("edited") or o.get("image") or ""
            pk = " + ".join(x for x in [s.get("packages") or "", s.get("extras") or ""] if x)
            due = s.get("due_cents", 0)
            if due > 0:
                paid = P(f"<b>Owes {_money(due)}</b>" + (f"<br/>{escape(o.get('athlete') or '')}" if o.get("athlete") else ""), raw=True, s=9.5, c="#B06A00")
            elif s.get("change_cents"):
                paid = P(f"Give {_money(s['change_cents'])} change", s=9.5, c="#B06A00")
            elif s.get("short_cents"):
                paid = P(f"Paid · {_money(s['short_cents'])} short", s=9.5, c="#666666")
            else:
                paid = P(paid_label(o, s), s=9.5, c="#666666")
            box = Table([[""]], colWidths=[0.2 * inch], rowHeights=[0.2 * inch],
                        style=TableStyle([("BOX", (0, 0), (-1, -1), 1.4, colors.HexColor("#333333"))]))
            data.append([box, pic(stem, 0.5 * inch, 0.62 * inch), P(str(o.get("envelope") or "?"), f="Helvetica-Bold", s=20),
                         [P(pk or "—", f="Helvetica-Bold", s=10.5), P(envelope_contents(o, catalog), s=9, c="#444444")],
                         P(re.sub(r"^(IMG|DSC|_MG)_?", "", stem, flags=re.I) or "—", f="Courier", s=10),
                         paid])
        story.append(Table(data, colWidths=[0.35 * inch, 0.65 * inch, 0.75 * inch, 3.65 * inch, 0.8 * inch, 1.3 * inch], repeatRows=1,
                           style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                             ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#999999")),
                                             ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                                             ("TOPPADDING", (0, 1), (-1, -1), 3), ("BOTTOMPADDING", (0, 1), (-1, -1), 3)])))
        story.append(PageBreak())
    if extras:
        story.append(P("School &amp; other orders", raw=True, f="Helvetica-Bold", s=20))
        story.append(P(shoot.get("name") or "", c="#555555"))
        story.append(Spacer(1, 10))
        data = [[P(h, f="Helvetica-Bold", s=8, c="#666666") for h in ["", "FOR", "WHAT GOES IN IT"]]]
        for x in extras:
            box = Table([[""]], colWidths=[0.2 * inch], rowHeights=[0.2 * inch],
                        style=TableStyle([("BOX", (0, 0), (-1, -1), 1.4, colors.HexColor("#333333"))]))
            data.append([box, P(x.get("customer") or x.get("kind") or "", f="Helvetica-Bold", s=11),
                         [P(_extra_item_text(it), s=9.5) for it in x.get("items") or []] or P("—")])
        story.append(Table(data, colWidths=[0.35 * inch, 2.2 * inch, 4.95 * inch], repeatRows=1,
                           style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                             ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#DDDDDD"))])))
    elif story and isinstance(story[-1], PageBreak):
        story.pop()

    def foot(c, d):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawString(0.5 * inch, 0.45 * inch, "Match each print to its photo · tick the box when the envelope is stuffed")
        c.drawRightString(8.0 * inch, 0.45 * inch, f"{business} · page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.7 * inch, title=f"{shoot.get('name') or 'Shoot'} — matching sheets")
    doc.build(story or [P("No envelopes yet.")], onFirstPage=foot, onLaterPages=foot)
    return path


# ------------------------------------------------------- digital envelopes --
# A record of each envelope drawn like the paper order form: the same packages
# and a la carte boxes with the family's choices filled in, the name lines at the
# bottom, and a strip with the envelope number, photo, total and payment.

BUSINESS_LINES = ("www.jbextenphotography.com · 114 Hogan Ln · Bryan, Ohio 43506 · 419-551-2103 · jbexten89@gmail.com")
_SIZE_WORDS = {"memory-mate": "MEMORY MATE", "wallet": "WALLETS"}


def _logo_path() -> Path | None:
    from . import paths
    for base in (paths.bundle_dir(), Path(__file__).resolve().parent):
        p = base / "ui" / "logo.jpg"
        if p.is_file():
            return p
    return None


def envelopes_pdf(shoot: dict, orders: list[dict], catalog, find_photo, path: Path) -> Path:
    """One letter page per envelope, sorted by team then envelope number."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    from .library import thumbnail
    from .orders import _env_num, order_summary, paid_label

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = letter
    M = 42
    INK, BLUE, MUTED, LIGHT = colors.HexColor("#111111"), colors.HexColor("#1A63C9"), colors.HexColor("#777777"), colors.HexColor("#EEF6FF")
    AMBER = colors.HexColor("#E3A04F")
    logo = _logo_path()
    logo_r = ImageReader(str(logo)) if logo else None
    day = shoot.get("date") or ""
    try:
        day = dt.date.fromisoformat(day).strftime("%b %d, %Y").replace(" 0", " ")
    except ValueError:
        pass
    pkgs = [p for p in catalog.products if p.type == "package"]
    alc = [p for p in catalog.products if p.type == "alacarte"]
    misc = [p for p in catalog.products if p.type == "misc"]
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.setTitle(f"Envelopes - {shoot.get('name', '')}")
    rows = sorted(orders, key=lambda o: (int(o.get("team_rank", 10_000)), str(o.get("team") or "").lower(), _env_num(o.get("envelope"))))

    def blank(x, y, qty, w=26):
        c.setStrokeColor(INK); c.setLineWidth(.7); c.line(x, y - 2, x + w, y - 2)
        if qty:
            c.setFillColor(BLUE); c.setFont("Helvetica-Bold", 11); c.drawCentredString(x + w / 2, y, str(qty))
        c.setFillColor(INK)

    for o in rows:
        s = order_summary(o, catalog)
        q = {}
        for l in o.get("lines") or []:
            q[l["product_id"]] = q.get(l["product_id"], 0) + int(l.get("qty") or 0)
        has_pkg = any(q.get(p.id) for p in pkgs)
        y = H - 30
        if logo_r:  # the logo, centred
            iw, ih = logo_r.getSize(); lh = 74; lw = iw * lh / ih
            c.drawImage(logo_r, (W - lw) / 2, y - lh, lw, lh, mask="auto")
        y -= 84
        # the strip: the photo first (it's what prints are matched by), then envelope, total, payment
        SH = 60
        c.setFillColor(colors.HexColor("#E8F2FF")); c.setStrokeColor(colors.HexColor("#2F9BFF")); c.setLineWidth(1.2)
        c.rect(0, y - SH, W, SH, fill=1, stroke=0); c.line(0, y, W, y); c.line(0, y - SH, W, y - SH)
        stem = o.get("edited") or o.get("image") or ""
        px = M
        ph = find_photo(stem) if stem else None
        if ph:
            try:
                im = ImageReader(io.BytesIO(thumbnail(str(ph), 240))); iw, ih = im.getSize(); th = SH - 8; tw = iw * th / ih
                c.drawImage(im, px, y - SH + 4, tw, th); px += tw + 10
            except Exception:  # noqa: BLE001 - a missing thumbnail never stops the page
                pass
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 15); c.drawString(px, y - 24, stem or "No photo picked")
        c.setFont("Helvetica", 9.5)
        c.drawString(px, y - 41, " · ".join(x for x in [f"Envelope {o.get('envelope') or '-'}", o.get("team") or "", shoot.get("name") or ""] if x))
        c.setFont("Helvetica", 9.5); c.drawRightString(W - M, y - 24, f"Total {_money(s['total_cents'])}")
        how = paid_label(o, s)
        pay = f"Paid {how.lower()} {_money(s.get('handed_cents', s['paid_cents']))}" if s.get("handed_cents") or s["paid_cents"] else how
        tag = f"Change due {_money(s['change_cents'])}" if s.get("change_cents") else f"Owes {_money(s['due_cents'])}" if s["due_cents"] else ""
        if tag:
            tw = c.stringWidth(tag, "Helvetica-Bold", 9.5) + 12
            c.setFillColor(AMBER); c.roundRect(W - M - tw, y - 45, tw, 14, 3, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#1A1208")); c.setFont("Helvetica-Bold", 9.5); c.drawRightString(W - M - 6, y - 41, tag)
            c.setFillColor(INK); c.setFont("Helvetica", 9.5); c.drawRightString(W - M - tw - 6, y - 41, pay)
        else:
            c.drawRightString(W - M, y - 41, pay)
        y -= 14
        y -= 64
        c.setFont("Helvetica", 9); c.setFillColor(INK)
        c.drawCentredString(W / 2, y, "PAYMENT DUE DAY OF SHOOT.  CASH/CHECKS ACCEPTABLE.  PLEASE PLACE AN X OR QTY BY CHOICE.")
        c.drawCentredString(W / 2, y - 12, "CHECKS PAYABLE TO: Jamie Bexten Photography")
        y -= 34
        # packages in two columns, as on the form
        half = len(pkgs) // 2  # A-C on the left, D-G on the right, as on the form
        cols = [pkgs[:half], pkgs[half:]]
        bottom = y
        for ci, col in enumerate(cols):
            cx, cy = M + 30 + ci * 250, y
            for p in col:
                n = q.get(p.id, 0)
                lines = [f"{v} - {_SIZE_WORDS.get(k, k)}" for k, v in p.contents.items()]
                hgt = 14 + 11.5 * len(lines)
                if n:
                    c.setFillColor(LIGHT); c.roundRect(cx - 4, cy - hgt + 4, 200, hgt + 6, 4, fill=1, stroke=0); c.setFillColor(INK)
                blank(cx, cy, n)
                c.setFont("Helvetica-Bold", 10.5); c.drawString(cx + 32, cy, f"{p.label.upper()} - {_money(p.price)}")
                c.setFont("Helvetica", 9.5)
                for i, t in enumerate(lines):
                    c.drawString(cx + 32, cy - 13 - 11.5 * i, t)
                cy -= hgt + 10
            bottom = min(bottom, cy)
        y = bottom - 2
        c.setFont("Helvetica", 9); c.drawString(M + 30, y, "Memory Mate: (Team 5x7 & Individual 5x7)")
        y -= 20
        c.setFont("Helvetica-Bold", 10); c.drawCentredString(W / 2, y, "Save on a la carte items with the purchase of a PACKAGE")
        y -= 10
        # the a la carte box: without package | with package | miscellaneous
        bh = 22 + 15 * max(len(alc), len(misc))
        c.setLineWidth(1); c.rect(M, y - bh, W - 2 * M, bh)
        colw = (W - 2 * M) / 3
        heads = [("Without PACKAGE Purchase", alc, False), ("With PACKAGE Purchase", alc, True), ("Miscellaneous", misc, None)]
        for hi, (title, items, withp) in enumerate(heads):
            x0 = M + 8 + hi * colw
            c.setFont("Helvetica-BoldOblique" if withp is not None else "Helvetica-Bold", 9.5); c.drawString(x0, y - 14, title)
            c.setLineWidth(.6); c.line(x0, y - 16, x0 + c.stringWidth(title, "Helvetica-Bold", 9.5), y - 16)
            for i, p in enumerate(items):
                ly = y - 31 - 15 * i
                n = q.get(p.id, 0) if (withp is None or withp == has_pkg) else 0
                if n:
                    c.setFillColor(LIGHT); c.rect(x0 - 3, ly - 4, colw - 12, 14, fill=1, stroke=0); c.setFillColor(INK)
                blank(x0, ly, n, 20)
                word = p.label.upper()
                if re.match(r"^\d", p.label):
                    word = word.replace("X", "x")  # 8x10, as printed on the form
                label = f"{p.unit} - {word}"
                c.setFont("Helvetica", 9); c.drawString(x0 + 26, ly, label)
                price = p.price if withp is None or not withp else p.with_package
                c.drawRightString(x0 + colw - 18, ly, _money(price))
        y -= bh + 26
        # the name lines
        fields = [("NAME", o.get("athlete")), ("PARENTS NAME", o.get("parent")), ("ADDRESS / PHONE", " · ".join(x for x in [o.get("address") or "", o.get("phone") or ""] if x)),
                  ("TEAM NAME", o.get("team")), ("COACH'S NAME", o.get("coach"))]
        for label, val in fields:
            c.setFont("Helvetica-Bold", 12); c.setFillColor(INK); c.drawString(M + 30, y, label)
            if val:
                c.setFont("Helvetica-Bold", 11.5); c.setFillColor(BLUE); c.drawString(M + 175, y, str(val)[:70])
            c.setStrokeColor(INK); c.setLineWidth(.7); c.line(M + 30, y - 5, W - M - 30, y - 5)
            y -= 22
        if o.get("notes") or o.get("glasses"):
            c.setFont("Helvetica", 9.5); c.setFillColor(MUTED)
            c.drawString(M + 30, y - 2, ("Glasses. " if o.get("glasses") else "") + (o.get("notes") or "")[:120])
        # picture day up the left edge, and the address line
        c.saveState(); c.translate(24, 300); c.rotate(90); c.setFont("Helvetica-Bold", 10); c.setFillColor(INK)
        c.drawString(0, 0, f"PICTURE DAY: {day}"); c.restoreState()
        c.setFont("Helvetica", 8.5); c.setFillColor(INK); c.drawCentredString(W / 2, 30, BUSINESS_LINES)
        c.showPage()
    if not rows:
        c.setFont("Helvetica", 12); c.drawString(M, H - 80, "No envelopes in this shoot yet."); c.showPage()
    c.save()
    return path
