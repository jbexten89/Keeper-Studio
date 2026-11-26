"""Sales analysis for the Orders tab: what sold, what it cost at the lab, what's left.

Everything here works on orders that already carry their `summary` with the
lab estimate (order_routes._decorate). Money is in cents.
"""

from __future__ import annotations

from .orders import Catalog, calculate, short_label

KIND = {"package": "package", "alacarte": "alacarte", "misc": "keepsake"}


def unit_lab_cents(catalog: Catalog, cost_fn) -> dict[str, int]:
    """Lab cost of one of each product, from a one-line envelope.

    cost_fn(order, catalog) -> {"cents", "unpriced"}; a product with nothing
    priced gets None so the screen can say "not priced".
    """
    out = {}
    for p in catalog.products:
        try:
            c = cost_fn({"lines": [{"product_id": p.id, "qty": 1}], "team": "Team", "athlete": "x"}, catalog)
            out[p.id] = None if (c["unpriced"] and not c["cents"]) else c["cents"]
        except Exception:  # noqa: BLE001 - an estimate must never break the screen
            out[p.id] = None
    return out


def _totals(orders: list[dict], shipping: int) -> dict:
    live = [o for o in orders if o.get("lines") and o["summary"]["total_cents"] > 0]
    S = lambda k: sum(int(o["summary"].get(k) or 0) for o in orders)
    sales, lab, paid = S("total_cents"), S("lab_cents"), S("paid_cents")
    n = len(live)
    ac = ks = ac_s = ks_s = 0
    for o in live:
        types = {l["type"]: 0 for l in o["summary"]["lines"]}
        for l in o["summary"]["lines"]:
            types[l["type"]] += l["line_cents"]
        if "alacarte" in types:
            ac += 1
            ac_s += types["alacarte"]
        if "misc" in types:
            ks += 1
            ks_s += types["misc"]
    return {"envelopes": len(orders), "n": n, "sales": sales, "lab": lab, "paid": paid, "due": sales - paid,
            "shipping": shipping, "profit_before": sales - lab, "profit": sales - lab - shipping,
            "avg": sales // n if n else 0, "ac_env": ac, "ks_env": ks, "ac_sales": ac_s, "ks_sales": ks_s,
            }


def _sold(orders: list[dict], catalog: Catalog) -> dict[str, dict]:
    """Per product: qty, sales, and how many were bought alone vs with a package (a la carte)."""
    out: dict[str, dict] = {}
    for o in orders:
        t = calculate(o.get("lines"), catalog)
        for l in t["lines"]:
            d = out.setdefault(l["product_id"], {"qty": 0, "sales": 0, "with_pkg": 0, "alone": 0})
            d["qty"] += l["qty"]
            d["sales"] += l["line_cents"]
            d["with_pkg" if l["discount"] else "alone"] += l["qty"]
    return out


def _packages_bought(o: dict, catalog: Catalog) -> list[str]:
    return [l["product_id"] for l in o["summary"]["lines"] if l["type"] == "package"]


def _add_extras(t: dict, ex: dict | None) -> dict:
    """Fold school & other orders into a whole-shoot total; average order stays families only."""
    ex = ex or {}
    t["extra"] = {k: ex.get(k, 0) for k in ("count", "sales_cents", "lab_cents", "paid_cents", "due_cents", "prints")}
    t["family_sales"] = t["sales"]
    t["sales"] += t["extra"]["sales_cents"]
    t["lab"] += t["extra"]["lab_cents"]
    t["paid"] += t["extra"]["paid_cents"]
    t["due"] = t["sales"] - t["paid"]
    t["profit_before"] = t["sales"] - t["lab"]
    t["profit"] = t["profit_before"] - t["shipping"]
    return t


def analyze(orders: list[dict], catalog: Catalog, unit_lab: dict, shipping_cents: int = 0,
            team: str | None = None, extras: dict | None = None) -> dict:
    """The Analysis view for a shoot (or several), optionally narrowed to one team.

    Shipping is one charge for the shoot, so a team's profit is before shipping.
    """
    pick = [o for o in orders if (o.get("team") or "") == team] if team is not None else orders
    one = team is not None
    whole = _add_extras(_totals(orders, shipping_cents), extras)
    sel = _totals(pick, 0 if one else shipping_cents) if one else _add_extras(_totals(pick, shipping_cents), extras)
    sold_sel, sold_all = _sold(pick, catalog), _sold(orders, catalog)

    # Which packages each selection's envelopes bought (A-C-style "big" = the three priciest)
    pk_sorted = sorted(catalog.packages, key=lambda p: -p.price)
    big_ids = {p.id for p in pk_sorted[:3]}

    def big_share(os_):
        live = [o for o in os_ if o.get("lines") and o["summary"]["total_cents"] > 0]
        if not live:
            return None
        return 100 * sum(1 for o in live if big_ids & set(_packages_bought(o, catalog))) / len(live)

    products = []
    for p in catalog.products:
        s, a = sold_sel.get(p.id, {}), sold_all.get(p.id, {})
        products.append({
            "id": p.id, "kind": KIND.get(p.type, p.type),
            "label": p.label if p.type == "package" else short_label(p),
            "letter": p.letter, "price": p.price, "with_package": p.with_package if p.type == "alacarte" else None,
            "lab_each": unit_lab.get(p.id), "sold": s.get("qty", 0), "sales": s.get("sales", 0),
            "sold_with_pkg": s.get("with_pkg", 0), "sold_alone": s.get("alone", 0),
            "sold_shoot": a.get("qty", 0),
        })

    teams = []
    if not one:
        from .orders import by_team_order
        names = by_team_order({o.get("team") or "" for o in orders}, orders)
        for t in names:
            tt = _totals([o for o in orders if (o.get("team") or "") == t], 0)
            teams.append({"team": t or "No team", "n": tt["n"], "envelopes": tt["envelopes"], "sales": tt["sales"],
                          "avg": tt["avg"], "profit": tt["profit_before"],
                          "profit_pct": round(100 * tt["profit_before"] / tt["sales"], 1) if tt["sales"] else None})

    pays: dict[str, list[int]] = {}
    for o in pick:
        su = o["summary"]
        if su["total_cents"] <= 0 and not su["paid_cents"]:
            continue
        if su["paid_cents"] > 0:
            m = "Picture day" if su.get("paid_auto") else ("Other" if (o.get("paid_method") or "") in ("", "none") else o["paid_method"].title())
            pays.setdefault(m, [0, 0])
            pays[m][0] += 1
            pays[m][1] += su["paid_cents"]
        if su["due_cents"] > 0:
            pays.setdefault("Not paid", [0, 0])
            pays["Not paid"][0] += 1
            pays["Not paid"][1] += su["due_cents"]
    order_m = ["Picture day", "Cash", "Check", "Card", "Other", "Not paid"]
    payments = [{"method": m, "envelopes": v[0], "cents": v[1]}
                for m, v in sorted(pays.items(), key=lambda kv: order_m.index(kv[0]) if kv[0] in order_m else 5)]

    compare = None
    if one:
        def pct(a, b):
            return 100 * a / b if b else None
        compare = [
            {"label": "Average order", "team": sel["avg"], "shoot": whole["avg"], "kind": "money"},
            {"label": f"Bought a big package ({', '.join(p.letter or p.label for p in pk_sorted[:3])})",
             "team": big_share(pick), "shoot": big_share(orders), "kind": "pct"},
            {"label": "Added a la carte prints", "team": pct(sel["ac_env"], sel["n"]), "shoot": pct(whole["ac_env"], whole["n"]), "kind": "pct"},
            {"label": "Added a keepsake", "team": pct(sel["ks_env"], sel["n"]), "shoot": pct(whole["ks_env"], whole["n"]), "kind": "pct"},
            {"label": "Profit % (before shipping)", "team": pct(sel["profit_before"], sel["sales"]),
             "shoot": pct(whole["profit_before"], whole["sales"]), "kind": "pct1"},
        ]

    live = [o for o in pick if o.get("lines") and o["summary"]["total_cents"] > 0]
    totals_each = sorted(o["summary"]["total_cents"] for o in live)
    pkgs_each = [sum(l["qty"] for l in o["summary"]["lines"] if l["type"] == "package") for o in live]
    items_each = [sum(l["qty"] for l in o["summary"]["lines"]) for o in live]
    n = len(live)
    habits = {
        "order_totals": totals_each,
        "median": (totals_each[n // 2] if n % 2 else (totals_each[n // 2 - 1] + totals_each[n // 2]) // 2) if n else 0,
        "multi_pkg": sum(1 for k in pkgs_each if k >= 2),
        "no_pkg": sum(1 for k in pkgs_each if k == 0),
        "items_avg": round(sum(items_each) / n, 1) if n else 0,
    }

    unpriced = sorted({u for o in pick for u in (o["summary"].get("lab_unpriced") or [])})
    return {"team": team, "selection": sel, "shoot": whole, "products": products, "teams": teams,
            "payments": payments, "compare": compare, "lab_unpriced": unpriced, "habits": habits}
