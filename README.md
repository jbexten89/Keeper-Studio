# Keeper Studio

Keeper's Lightroom-style culling interface and PhotoCropper's print engine in one
desktop app for Jamie Bexten Photography. Cull a shoot, crop every print size,
build class composites, cut out backgrounds and run the picture-day orders
without switching programs.

The originals stay untouched as fallbacks: **PhotoCropper** (`E:\Photo Cropper`)
and the web version of **Keeper** (jbexten89/Keeper) keep working exactly as
before. Keeper Studio has its own copy of the engine and its own `config.yaml`,
so changing framing here never changes PhotoCropper.


## Download

Get the newest version from **[Releases](https://github.com/jbexten89/Keeper-Studio/releases/latest)**:
download `KeeperStudio-Windows-vX.Y.Z.zip`, unzip it, and run **Keeper Studio.exe**.
To update, replace the old Keeper Studio folder with the new one; settings, framing
and the catalog live in `%LOCALAPPDATA%\KeeperStudio` and are kept. The app shows a
banner when a newer release is out.

To make a release: on GitHub open **Releases → Draft a new release**, type a new tag
such as `v1.1.0`, give it a title and press **Publish release**. The build stamps that
version into the app and attaches the zip a few minutes later. Ordinary pushes still
make test builds under Actions, kept for 30 days.

## Install

**Easiest (no Python needed):** open this repository's **Actions** tab → the
latest **Build Windows app** run → download **KeeperStudio-Windows**, right-click →
**Extract All**, and double-click **Keeper Studio.exe**. The first launch may show
"Windows protected your PC" because the app isn't code-signed: **More info →
Run anyway**.

**From source:** download the repository (green **Code** button → Download ZIP),
extract it, then:

1. Double-click **Setup.bat**. It installs everything into `.venv` and needs
   Python 3.9–3.12. Leave the window open; the first run takes a few minutes.
2. Double-click **Keeper Studio.bat** to open the app.

**Build.bat** makes your own `Keeper Studio.exe` from the source folder.

## The six modules

Switch with the tabs at the top or **Ctrl+1…6**: Library, Retouch, Crop, Orders
(the picture-day tabs, in workflow order), then Composite and Extract after a
divider (used once a year: preschool composites and fall sports banners).
In Crop, the **Show** buttons (All · Picks + Teams · Picks · Teams) filter the
filmstrip to just those photos, ready to check framing and export; the arrow keys
step through only what's shown. If an envelope's photo isn't marked Pick, an amber
"not marked Pick - Show" button finds it. Leaving Crop shows the whole folder again.

| Module | What it does |
| --- | --- |
| **Library** | Open a shoot folder; flag picks and rejects; rate and label; use Quick Collection and collections; compare in Grid, Loupe, Compare and Survey with synced zoom; export copies or resized JPEGs. |
| **Retouch** | Fix glasses glare by swapping in the eyes from a frame without glasses: pick that frame, line it up, brush the eyes in (or **Paint eyes for me**) and **Save retouch**. The fixed copy goes in a `_retouched` folder beside the photo under the same name, and Crop, Composite, Extract and exports use it automatically. The camera file is never changed. |
| **Crop** | PhotoCropper's face-anchored framing for every print size. Each photo shows its crop boxes (hover a size to see just that one) and a status: *Ready*, *Shortened to fit*, *Placed by hand* or *Needs review* with the reason. Press **A** to place the framing by hand. **Check framing** previews a whole shoot; **Export prints** writes the same folders PhotoCropper does: one per size, *Orders*, *review*, and contact sheets. |
| **Composite** | The class composite builder. Students and teachers come from a collection, the selection or the filmstrip, so you can pick them in Library first. |
| **Extract** | Background removal to transparent PNGs. **Quality: Best** uses BiRefNet (cleanest hair and pom-pom edges, needs about 7 GB of free memory per photo); **Fast** uses ISNet (a few seconds and about 3 GB per photo). Works on the selected photos when there are any, and asks before a big batch. |
| **Orders** | The picture-day envelopes, kept on this computer. One shoot per picture day; type each envelope in (athlete, team, package A–G, extras, how they paid, the photo number, glasses), see what's still owed, and build the lab order from only the photos and sizes families bought. |

A typical picture day: open the folder → cull in **Library** (P / X, Quick
Collection) → fix glasses glare in **Retouch** → filter to the picks → **Crop** → *Check framing* → fix anything
flagged → *Export prints*.

### Orders

Prices and pricing rules are the same as the online order site
(jbexten89/photography-orders): any package unlocks the lower a la carte
price, keepsakes are one price, and a Memory Mate is built from an individual
5x7 and a team 5x7.

* **Typing in envelopes:** press **N**, type the name, **Enter**, then the
  package letter (**A**–**G**; Shift adds another for siblings). Pick Cash,
  Check or Card and the amount fills in. For the photo, type the number
  (`5371`) or click the photo in the filmstrip and press **Use IMG_5371**.
  Everything saves by itself; **Del** deletes with Undo.
* **Envelopes in shooting order:** turn on **Filmstrip: picks only** (one Pick
  per kid, flagged in Library). Each new envelope then gets the next kid's
  photo filled in and highlighted in the filmstrip; if it's the wrong kid,
  just click the right photo. Clicking an envelope highlights its photo, and
  clicking a photo (or **←** / **→**) opens the envelope using it.
* **Same kid, two envelopes** (Mom and Grandma each order): on the new
  envelope, click the kid's photo even though it's used; it's assigned to the
  new envelope. Afterwards each click on that photo opens the next envelope
  that uses it. Crop cuts it once; the lab folder adds the prints together; the
  ROES file keeps one row per envelope so each family gets its own.
* **Teams:** each team's group photo (▣ on the team) is what team 5x7s, team
  8x10s and Memory Mates print from. Press **T** on team photos in Library
  (a T badge shows); ▣ then switches the filmstrip to just those, and a click
  sets it. T photos are skipped when a new envelope takes the next photo. The
  toolbar toggle moved to **Shift+T**. To put many envelopes on a team at once,
  select them (Ctrl-click, Shift-click, or **Select all** / Ctrl+A), type the
  team and/or coach on the right and press **Apply**.
* **Crop only what was ordered:** *Select ordered photos* selects every picked
  photo and group shot in the filmstrip and switches to Crop with *Selected*
  on, so *Export prints* runs on just those.
* **Lab order:** lists every file the lab prints and how many, grouped by size,
  and ticks off the ones already in the crops folder. *Build lab folder…*
  copies just those files into one folder per size plus `lab-order.csv`
  (under *Other ways to send*, for the Meridian website or ROES). With *One
  file per print* on, two 4x6s become two files, so a whole size folder
  uploads to the Meridian website with every quantity at 1. Shipping sits
  beside Ship / Pickup in the Meridian box: type Meridian's price once and
  every shoot that ships gets it; Pickup is $0.
* **Analysis:** four numbers up top (Sales, You keep, Average order, Still
  owed), compared with the same league's last shoot when there is one
  ("Fall Sports 2025" for "Fall Sports 2026"), then **What stands out**: a few
  plain sentences about the package mix, keepsakes, the best and lowest
  team, and order sizes. Packages, a la carte and keepsakes list what sold;
  the rest fold into "+N didn't sell · show". For the shoot, a team picked on
  the left, or every shoot together. **What if** sits in the right pane: try
  new prices on any item, with a setting for families who stop buying when a
  price goes up, and it says how many buyers a raise could lose and still
  make the same profit.
* **Names:** only needed for envelopes that owe. Marking one Unpaid or
  accepting a short payment puts the cursor in the name box ("Who owes
  this?"), and Totals lists any that owe with no name.
* **Thumbnails:** each envelope row shows its photo beside the photo number
  (click it for the Preview window); a team photo's number turns amber.
  The ▣ in the header turns them off.
* **Matching sheets:** Export ▾ → Matching sheets (PDF): one page per team,
  each envelope's photo, number and what goes in it, in stuffing order, so
  prints that come back without numbers on the back can be matched by eye.
  The Meridian order names its files in the same order
  (`03-7thBoys_E047_IMG_5031_5x7.jpg`) so the lab packs them that way; turn
  off *Files in envelope order* in the Meridian panel to send plain names.
* **Keeping orders safe:** each shoot's orders are also saved in its photo
  folder as `Keeper Studio orders.json`, once the app sees the folder holds
  that shoot's photos. Copy the folder to the other PC and opening it offers
  to bring the orders in (or the newer ones, after backing up). The order
  book is also backed up each time the app closes; Shoot ▾ → Backups lists
  every backup with Restore, and can keep a second copy (OneDrive, a USB
  stick).
* **Folder work file:** marks (flags, stars, labels, team photos, collections,
  hand framing, rotations) are also saved in `Keeper Studio work.json` inside
  the shoot folder, a few seconds after each change (Ctrl+S saves at once). If
  a folder is moved, renamed or opened on another PC, the app offers to
  restore them; for folders moved before this existed, it finds the same
  photos (name and size) where they used to be and offers to bring their
  marks over.
* **Paid on picture day:** a shoot setting (Edit shoot; on for new shoots).
  Envelopes count as paid in full unless you type what a family paid or mark
  it Unpaid; Payments shows them as "Picture day".
* **Team order:** teams are listed in the order you first used them. Drag a
  team in the Teams list, or use its ↑ ↓, to rearrange; A–Z sorts them. That
  order is used everywhere: the envelope list, lab and Meridian orders, the
  pull sheet, the shoot summary and Analysis.
* **Team list:** a new shoot starts with every team (and its coach) from the
  last shoot of the same name - "Winter Sports 2026" from "Winter Sports
  2025" - in the same order, so the Team box is a pick list and picking a team
  fills in its coach. Those teams show dimmed ("From last year · no envelopes
  yet") until an envelope uses them; ✕ takes one off for the year. A team
  typed that isn't on the list is added to it, and carries to next year.
  **List…** in the Teams header opens the whole list: edit names and coaches,
  drag to reorder, add a team, or take off one with no envelopes.
* **Team 5×7s for the school** (Shoot ▾): checks every team on the team list
  (group photo picked, 5×7 cropped; skip a team that wasn't photographed),
  zips one 300-dpi 5×7 per team named by team, and emails it. *Send to school*
  sends from Gmail with an app password (Google Account → Security → 2-Step
  Verification → App passwords; kept with Windows' password protection);
  *Open in Gmail* opens a filled-in message to drag the zip into, then *I sent
  it*. The school's email carries to next year; Needs attention shows until
  it's sent, and again if a team photo changes after.
* **School & other orders…** (under Totals) are prints that aren't on any
  envelope: for the school, the park, teachers or a sponsor. Each item is a
  size (4x6 to 16x20) and a Meridian product (print, standout, canvas, metal…)
  of every team's group photo (a count for each team), one team's photo, or
  one photo, at a price you type; 0 makes it free. School starts as an 8x10
  of each team, Park and Teachers as a 5x7. They go into the lab order and
  the Meridian order labeled with who they're for, count in Totals, Analysis
  and the shoot summary (not in average order), take payments like an
  envelope, and print an invoice. *Copy from another shoot…* reuses last
  season's list.
* **Exports:** pull sheet (prints per athlete with totals), crop list, ROES
  event import file, and an orders CSV for the books. With a team selected on
  the left, an export covers just that team.
* **Import website CSV…** brings in orders from the website's /admin export
  (orders already imported are skipped), so online and paper orders end up in
  one place.
* **ROES file:** one row per athlete. Packages never go to the lab: each
  envelope is listed as the individual prints it comes to (Package F is one
  5 x 7 and two 4 x 6), matching the items in Meridian's ROES Sports group.
  Team prints are the same ROES item as that size, printed landscape from the
  group photo, so they share its code.
* **Prices…** opens `prices.yaml`: packages, prices, which Crop size each print
  is cut to, and Meridian's ROES code for each print item (still blank: ask
  Meridian for a sample import file; a blank code exports the item's name and
  the ROES button shows ⚠). Save it and the app picks the change up.

## Where things live

* `models\`, `luts\` and the app's own `config.yaml`: beside the app, replaced
  by each new build. The settings Keeper Studio actually uses are your copy,
  `%LOCALAPPDATA%\KeeperStudio\config.yaml`, made from the app's file. Fine-tune
  framing values are also saved in `framing-settings.json` and put back on every
  new build's copy, so updating never resets them. A backup is saved as
  `config.yaml.bak`. `changes.log` there notes when a hand placement is removed.
* Flags, ratings, collections, hand-placed crops and settings:
  `%LOCALAPPDATA%\KeeperStudio\catalog.sqlite3`, along with the thumbnail cache.
  They survive app updates.
* Orders: `%LOCALAPPDATA%\KeeperStudio\orders.sqlite3`, with a dated copy in
  `backups\` each day the app opens (the last 30 are kept) and each time it
  closes (the last 14), and your
  `prices.yaml` beside it. Updating the app never touches them; the
  repository's `prices.yaml` is only the starting copy.
* Hand-placed crops are also written into the output folder's `manual\` folder
  in PhotoCropper's format when you export, so PhotoCropper honours them too.

## The extraction model

The models (Best 224 MB, Fast 179 MB) aren't in the repository or the build.
Each downloads the first time you use it, with a percentage in the progress card
(Cancel stops it), into `%LOCALAPPDATA%\KeeperStudio\models\rembg\`, so a new
build reuses it. A model an older build downloaded beside its exe
(`models\rembg\`) is picked up and moved over the first time.

## Structure

* `photocropper/`, `photoextractor/`: PhotoCropper's engine, copied as is. The one
  addition is a small hook in `pipeline._write_crop`, so the app can preview crop
  boxes through exactly the same code path as a real run, without writing files.
* `keeperstudio/`: the app. That's a local server bound to 127.0.0.1 with a
  per-launch token (`server.py`), the bridge to the engine (`engine.py`), folder
  scans and thumbnails (`library.py`), the catalog (`catalog.py`), orders
  (`orders.py` for prices and everything worked out from an order,
  `orderbook.py` for storage, `order_routes.py` for the endpoints), and the
  interface (`ui/index.html`, with its styles in `ui/app.css` and one script per tab in `ui/js/`), shown in a native window by pywebview (`app.py`).
* `tests/`: `python -m unittest discover tests`. The order tests are the
  website's own pricing, pull-sheet, crop-list and ROES cases, and run on every
  build.
* `run_studio.py --browser` opens the app in your web browser instead of its own
  window, which is handy for troubleshooting.

## Licences

PhotoCropper's engine is MIT (see `LICENSE-PhotoCropper`). Bundled components keep
their own licences: mediapipe and its models (Apache 2.0), rembg (MIT), BiRefNet
(MIT), onnxruntime (MIT), pywebview (BSD), Pillow (MIT-CMU), and Nunito Sans (OFL).

### Meridian bulk order

Orders > **Lab order** > **Build Meridian order…** makes one folder Meridian's
bulk upload takes whole: the cropped files in a sub-folder per print size and
`<shoot>-meridian-order.csv` beside them, a row per file with Meridian's product
code, the quantity, Matte, and `crop=exact` (Crop already cut every file to the
print's shape). It then runs Meridian's own checker (`validate_order.py`) and
shows its errors, warnings and estimated total. Your Meridian account email and
Ship / Pickup are set on that panel.

Meridian's files live in `keeperstudio/meridian/`: their product list, designs,
template, example, instructions and checker. The code each item is ordered as is
under `meridian:` in Prices…: 8x10 `R1680A`, 5x7 `RA1657`, 4x6 `R1646`, 8 wallets
`PKG-8-Wallets`, team prints use their size's code, magnets `MAG45` / `MAG57`,
key ring `R606-2` (plastic keychain, medium), photo badge `R73` (3" pin-back
button). Memory Mates go as an individual 5x7 and a team 5x7, as before.
mini wallets `R1688` (sheet of 8, printed 1.5 x 2) and wallet magnets `RA78B`
(set of 4). If Meridian ever gives you a code that isn't in their products.csv
yet, add its row to a `products-extra.csv` beside it (same columns); the app and
the checker read both. Anything without a code is left out of the CSV and listed,
so you can order it on the website.
