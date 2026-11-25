#!/usr/bin/env python3
"""Check a Meridian bulk order CSV before sending it.

Usage:
    python3 validate_order.py ORDER.csv PRODUCTS.csv DESIGNS.csv [IMAGE_FOLDER]

ORDER.csv     the filled-in bulk order (same columns as meridian-bulk-order-template.csv)
PRODUCTS.csv  meridian-bulk-order-products.csv
DESIGNS.csv   meridian-bulk-order-designs.csv (memory mates, trader cards and magnets,
              magazine covers, sports tickets)
IMAGE_FOLDER  optional: the folder holding the images. When given, every file is
              checked for existence and, if Pillow is installed, for pixel size.

Prints a list of problems (ERROR must be fixed, WARN should be reviewed), then an
order summary with an estimated print cost. Exit code 1 if there are errors.
Estimates exclude shipping, tax and discounts; Meridian confirms the final total.
"""
import csv, math, os, re, sys
from collections import defaultdict, OrderedDict

COLUMNS = ['order_name', 'account_email', 'color_correction', 'delivery', 'item_id',
           'product_code', 'design_name', 'quantity', 'file_name', 'image_order', 'text_fields',
           'finish', 'mounting', 'texture', 'other_options', 'crop', 'crop_focus', 'caption', 'notes']
ORDER_LEVEL = ['order_name', 'account_email', 'color_correction', 'delivery']
ITEM_LEVEL = ['product_code', 'design_name', 'text_fields', 'quantity', 'finish', 'mounting', 'texture', 'other_options', 'crop']
CROPS = {'fill', 'fit', 'exact'}
FOCUS = {'center', 'top', 'bottom', 'left', 'right', ''}
IMAGE_EXT = {'.jpg', '.jpeg', '.tif', '.tiff'}
MIN_PPI_WARN, MIN_PPI_ERROR = 200, 150
# Common customer words for the same surface. Prints list the standard luster surface as 'Matte'.
ALIASES = {'luster': 'matte', 'lustre': 'matte', 'glossy': 'gloss', 'gloss': 'glossy', 'matte': 'luster'}


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def parse_choices(text):
    """'Matte [default] | Gloss | Metallic (+$3.00)' -> {'matte': 0.0, ...}, default"""
    out, default = OrderedDict(), None
    for part in [p.strip() for p in (text or '').split('|') if p.strip()]:
        up = re.search(r'\(\+\$([\d.]+)\)', part)
        is_def = '[default]' in part
        name = re.sub(r'\(\+\$[\d.]+\)|\[default\]', '', part).strip()
        out[norm(name)] = float(up.group(1)) if up else 0.0
        if is_def:
            default = norm(name)
    return out, default


def parse_other(text):
    """'Frame Style: Recessed [default] | Standard (+$5.30); Cutting: ...' -> {group: choices}"""
    groups = {}
    for chunk in [c.strip() for c in (text or '').split(';') if c.strip()]:
        g, _, rest = chunk.partition(':')
        groups[norm(g)] = parse_choices(rest)
    return groups


def key(s):
    """Loose match for design names: case, spaces, dots and symbols don't matter."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower().replace('×', 'x'))


def short_key(s):
    """Design name without the words every design of that product shares."""
    k = key(s)
    for w in ('setof18', 'setof4', 'cover8x10', '8x10', 'vertical', 'horizontal'):
        k = k.replace(w, '')
    return k


def find_design(pool, name):
    d = pool.get(key(name))
    if d:
        return d
    hits = [x for x in pool.values() if short_key(x['design_name']) == short_key(name)]
    return hits[0] if len(hits) == 1 else None


def parse_fields(text):
    """'Player name=Jake Moreno; Team name=Vikings' -> [('player name', 'Jake Moreno'), ...]"""
    out = []
    for chunk in [c.strip() for c in (text or '').split(';') if c.strip()]:
        label, eq, value = chunk.partition('=')
        out.append((norm(label), value.strip(), bool(eq), chunk))
    return out


def size_inches(text):
    m = re.match(r'\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$', text or '')
    return (float(m.group(1)), float(m.group(2))) if m else None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    if len(sys.argv) < 4 or not sys.argv[3].lower().endswith('.csv'):
        print('Give the designs file too: validate_order.py ORDER.csv PRODUCTS.csv DESIGNS.csv [IMAGE_FOLDER]')
        sys.exit(2)
    order_path, products_path, designs_path = sys.argv[1], sys.argv[2], sys.argv[3]
    folder = sys.argv[4] if len(sys.argv) > 4 else None
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    except ImportError:
        Image = None

    products = {r['product_code'].strip(): r for r in csv.DictReader(open(products_path, encoding='utf-8-sig'))}
    prod_ci = {k.lower(): k for k in products}
    designs = defaultdict(dict)
    for d in csv.DictReader(open(designs_path, encoding='utf-8-sig')):
        designs[d['product_code'].strip()][key(d['design_name'])] = d
    rows = list(csv.DictReader(open(order_path, encoding='utf-8-sig')))
    problems = []

    def err(line, msg): problems.append(('ERROR', line, msg))
    def warn(line, msg): problems.append(('WARN', line, msg))

    if not rows:
        print('ERROR: the order file has no rows.')
        sys.exit(1)
    header = list(rows[0].keys())
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        err('header', 'missing columns: ' + ', '.join(missing))
    extra = [c for c in header if c not in COLUMNS]
    if extra:
        warn('header', 'columns Meridian will ignore: ' + ', '.join(extra))

    first = rows[0]
    for c in ORDER_LEVEL:
        vals = {(r.get(c) or '').strip() for r in rows}
        if len(vals) > 1:
            err('all', f'{c} must be the same on every row (found: {", ".join(sorted(vals))})')
    if not (first.get('order_name') or '').strip():
        err('all', 'order_name is empty')
    if '@' not in (first.get('account_email') or ''):
        err('all', 'account_email must be the email of your Meridian account')
    cc = norm(first.get('color_correction'))
    if cc not in ('yes', 'no'):
        err('all', 'color_correction must be yes or no')
    if norm(first.get('delivery')) not in ('ship', 'pickup'):
        err('all', 'delivery must be ship or pickup')

    items = OrderedDict()
    for i, r in enumerate(rows, start=2):
        r = {k: (v or '').strip() for k, v in r.items() if k}
        r['_line'] = i
        if not r.get('item_id'):
            err(i, 'item_id is empty')
            continue
        items.setdefault(r['item_id'], []).append(r)

    seen_files = defaultdict(list)
    lines_out, total = [], 0.0
    for item_id, rs in items.items():
        r0 = rs[0]
        line = r0['_line']
        for c in ITEM_LEVEL:
            if len({norm(x.get(c)) for x in rs}) > 1:
                err(line, f'item {item_id}: {c} differs between its rows; it must be the same on every row of the item')
        code = prod_ci.get(r0.get('product_code', '').lower())
        if not code:
            err(line, f'item {item_id}: product_code "{r0.get("product_code")}" is not in the product list')
            continue
        p = products[code]
        if not p['how_to_order'].startswith('Bulk upload'):
            err(line, f'item {item_id}: {p["product_name"]} can\'t be ordered with this CSV ({p["how_to_order"]})')
            continue
        try:
            qty = int(r0.get('quantity', ''))
            if qty < 1:
                raise ValueError
        except ValueError:
            err(line, f'item {item_id}: quantity must be a whole number of 1 or more')
            qty = 0

        unit = float(p['base_price_usd'] or 0)
        for col, choice_col in (('finish', 'finish_choices'), ('mounting', 'mounting_choices'), ('texture', 'texture_choices')):
            choices, default = parse_choices(p[choice_col])
            val = norm(r0.get(col))
            if not val:
                continue
            if val not in choices and ALIASES.get(val) in choices:
                warn(line, f'item {item_id}: {col} "{r0.get(col)}" read as "{ALIASES[val]}"; use "{ALIASES[val]}" to remove this warning')
                val = ALIASES[val]
            if not choices:
                err(line, f'item {item_id}: {p["product_name"]} has no {col} option; leave {col} blank')
            elif val not in choices:
                err(line, f'item {item_id}: {col} "{r0.get(col)}" is not offered for {p["product_name"]} (choices: {p[choice_col]})')
            else:
                unit += choices[val]
        groups = parse_other(p['other_options'])
        for pair in [x.strip() for x in (r0.get('other_options') or '').split(';') if x.strip()]:
            g, eq, v = pair.partition('=')
            if not eq:
                err(line, f'item {item_id}: other_options must be written Group=Value (got "{pair}")')
                continue
            g, v = norm(g), norm(v)
            if g not in groups:
                err(line, f'item {item_id}: option group "{pair.split("=")[0].strip()}" is not offered for {p["product_name"]}')
            elif v not in groups[g][0]:
                err(line, f'item {item_id}: "{pair}" is not a valid choice (choices: {p["other_options"]})')
            else:
                unit += groups[g][0][v]

        crop = norm(r0.get('crop')) or 'fill'
        if crop not in CROPS:
            err(line, f'item {item_id}: crop must be fill, fit or exact')

        design = None
        if 'design_name' in p['how_to_order']:
            dn = r0.get('design_name', '')
            if not dn:
                err(line, f'item {item_id}: {p["product_name"]} needs a design_name; look it up on {next(iter(designs[code].values()), {}).get("website_page", "the website")}')
            else:
                design = find_design(designs[code], dn)
                if not design:
                    close = [d['design_name'] for k, d in designs[code].items() if key(dn)[:6] and k.startswith(key(dn)[:6])][:5]
                    err(line, f'item {item_id}: design "{dn}" isn\'t a {p["product_name"]} design' + (f' (did you mean: {"; ".join(close)}?)' if close else ''))
            if design:
                allowed = {norm(re.sub(r'\s*\(default:.*?\)', '', f)): f for f in design['text_fields'].split(' | ') if f.strip()}
                given = parse_fields(r0.get('text_fields'))
                for label, value, has_eq, raw in given:
                    if not has_eq:
                        err(line, f'item {item_id}: text_fields must be written Label=Value (got "{raw}")')
                    elif label not in allowed:
                        err(line, f'item {item_id}: "{raw.split("=")[0].strip()}" is not a text field on {design["design_name"]} (fields: {design["text_fields"] or "none"})')
                if allowed and not any(v for _, v, _, _ in given):
                    warn(line, f'item {item_id}: no text given; {design["design_name"]} has fields {design["text_fields"]}')
        else:
            if r0.get('design_name') or r0.get('text_fields'):
                warn(line, f'item {item_id}: {p["product_name"]} doesn\'t use design_name or text_fields; they will be ignored')
        multi = p['images_per_item'].startswith('Many')
        need = 2 if p['images_per_item'].startswith('2') else None
        if design:
            need = len([x for x in design['photos'].split(' | ') if x.strip()])
            multi = False
        if multi or (need and need > 1) or (need and len(rs) > 1):
            orders = [x.get('image_order') for x in rs]
            if any(not o.isdigit() for o in orders):
                err(line, f'item {item_id}: every row needs an image_order number (1, 2, 3 ...)')
            elif sorted(int(o) for o in orders) != list(range(1, len(rs) + 1)):
                err(line, f'item {item_id}: image_order must run 1, 2, 3 ... with no gaps or repeats')
            if need and len(rs) != need:
                what = f' ({design["photos"]})' if design else ''
                err(line, f'item {item_id}: {p["product_name"]} needs exactly {need} image{"s" if need != 1 else ""}{what}, one row each (found {len(rs)})')
        elif len(rs) > 1 and not design:
            err(line, f'item {item_id}: {p["product_name"]} takes one image, but {len(rs)} rows share this item_id; give each print its own item_id')

        if multi:
            per = int(re.search(r'(\d+) per page', p['images_per_item']).group(1))
            pages = math.ceil(len(rs) / per)
            cost = unit * pages * qty
            desc = f'{p["product_name"]}: {len(rs)} images, {pages} page{"s" if pages != 1 else ""} x {qty}'
        else:
            cost = unit * qty
            desc = f'{p["product_name"]}{" - " + design["design_name"] if design else ""} x {qty}'
        total += cost
        lines_out.append((item_id, desc, cost))

        dims = None if design else size_inches(p['print_size_in'])
        for x in rs:
            ln, fn = x['_line'], x.get('file_name', '')
            if norm(x.get('crop_focus')) not in FOCUS:
                err(ln, 'crop_focus must be center, top, bottom, left or right')
            if not fn:
                err(ln, f'item {item_id}: file_name is empty')
                continue
            if '\\' in fn:
                err(ln, f'use forward slashes in file_name: {fn}')
            ext = os.path.splitext(fn)[1].lower()
            if ext not in IMAGE_EXT:
                err(ln, f'{fn}: only JPEG or TIFF files are accepted')
            seen_files[fn].append(item_id)
            if not folder:
                continue
            path = os.path.join(folder, fn)
            if not os.path.isfile(path):
                err(ln, f'{fn}: file not found in the image folder (names must match exactly, including upper/lower case)')
                continue
            if Image is None or not dims:
                continue
            try:
                with Image.open(path) as im:
                    w, h = im.size
                    mode = im.mode
            except Exception as e:
                err(ln, f'{fn}: can\'t be opened as an image ({e})')
                continue
            if mode not in ('RGB', 'L'):
                warn(ln, f'{fn}: image mode is {mode}; send 8-bit RGB (sRGB) files')
            pw, ph = dims
            orient = p['orientation']
            if orient.startswith('either') or orient == 'square':
                pw, ph = (max(dims), min(dims)) if w >= h else (min(dims), max(dims))
            img_ar, print_ar = w / h, pw / ph
            if crop == 'exact' and abs(img_ar / print_ar - 1) > 0.02:
                err(ln, f'{fn}: crop is "exact" but the image shape ({w}x{h}) doesn\'t match {p["print_size_in"]}; crop it or use fill/fit')
            if crop == 'fill':
                lost = 1 - min(img_ar, print_ar) / max(img_ar, print_ar)
                if lost > 0.20:
                    warn(ln, f'{fn}: fill will trim about {round(lost * 100)}% of the image to fit {p["print_size_in"]}; check crop_focus or use fit')
                if (orient == 'landscape' and h > w) or (orient == 'portrait' and w > h):
                    warn(ln, f'{fn}: a {"portrait" if h > w else "landscape"} image on a {orient} product will be heavily cropped')
            ppi = min(max(w, h) / max(pw, ph), min(w, h) / min(pw, ph))
            if ppi < MIN_PPI_ERROR:
                warn(ln, f'{fn}: only about {int(ppi)} pixels per inch at {p["print_size_in"]}; it will look soft. Use a larger file or a smaller print')
            elif ppi < MIN_PPI_WARN:
                warn(ln, f'{fn}: about {int(ppi)} pixels per inch at {p["print_size_in"]}; acceptable, but a larger file would print sharper')

    if cc == 'yes':
        total += 5.0
        lines_out.append(('order', 'Color correction (whole order)', 5.0))

    errors = [p for p in problems if p[0] == 'ERROR']
    print(f'Checked {len(rows)} rows, {len(items)} items, {len(seen_files)} different image files.')
    print(f'{len(errors)} errors, {len(problems) - len(errors)} warnings.\n')
    for level, line, msg in problems:
        print(f'{level:5}  row {line}: {msg}')
    print('\nORDER SUMMARY (estimate; excludes shipping, tax and discounts)')
    for item_id, desc, cost in lines_out:
        print(f'  {item_id:>10}  {desc:<60} ${cost:8.2f}')
    print(f'  {"":>10}  {"Estimated total":<60} ${total:8.2f}')
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
