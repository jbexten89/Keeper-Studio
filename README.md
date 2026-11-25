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

Switch with the tabs at the top or **Ctrl+1…6**: Library, Retouch, Crop,
Composite, Extract, Orders.

| Module | What it does |
| --- | --- |
| **Library** | Open a shoot folder; flag picks and rejects; rate and label; use Quick Collection and collections; compare in Grid, Loupe, Compare and Survey with synced zoom; export copies or resized JPEGs. |
| **Retouch** | Fix glasses glare by swapping in the eyes from a frame without glasses: pick that frame, line it up, brush the eyes in (or **Paint eyes for me**) and **Save retouch**. The fixed copy goes in a `_retouched` folder beside the photo under the same name, and Crop, Composite, Extract and exports use it automatically. The camera file is never changed. |
| **Crop** | PhotoCropper's face-anchored framing for every print size. Each photo shows its crop boxes (hover a size to see just that one) and a status: *Ready*, *Shortened to fit*, *Placed by hand* or *Needs review* with the reason. Press **A** to place the framing by hand. **Check framing** previews a whole shoot; **Export prints** writes the same folders PhotoCropper does: one per size, *Orders*, *review*, and contact sheets. |
| **Composite** | The class composite builder. Students and teachers come from a collection, the selection or the filmstrip, so you can pick them in Library first. |
| **Extract** | Background removal to transparent PNGs, using BiRefNet, the same model PhotoExtractor uses. |
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
  copies just those files into one folder per size plus `lab-order.csv`.
  With *One file per print* on, two 4x6s become two files, so a whole size
  folder uploads to the Meridian website with every quantity at 1.
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

* `config.yaml`, `models\`, `luts\`: beside the app, editable. In Crop,
  **Framing settings…** edits the main framing numbers and keeps the file's
  comments; a backup is saved as `config.yaml.bak`.
* Flags, ratings, collections, hand-placed crops and settings:
  `%LOCALAPPDATA%\KeeperStudio\catalog.sqlite3`, along with the thumbnail cache.
  They survive app updates.
* Orders: `%LOCALAPPDATA%\KeeperStudio\orders.sqlite3`, with a dated copy in
  `backups\` each day the app opens (the last 30 are kept), and your
  `prices.yaml` beside it. Updating the app never touches them; the
  repository's `prices.yaml` is only the starting copy.
* Hand-placed crops are also written into the output folder's `manual\` folder
  in PhotoCropper's format when you export, so PhotoCropper honours them too.

## The extraction model

It's 220 MB, so it isn't in the repository. Setup copies it from
`..\Photo Cropper\models\rembg\` if it finds it there; otherwise Keeper Studio
downloads it the first time you use Extract. You can also copy
`birefnet-general-lite.onnx` into `models\rembg\` yourself.

## Structure

* `photocropper/`, `photoextractor/`: PhotoCropper's engine, copied as is. The one
  addition is a small hook in `pipeline._write_crop`, so the app can preview crop
  boxes through exactly the same code path as a real run, without writing files.
* `keeperstudio/`: the app. That's a local server bound to 127.0.0.1 with a
  per-launch token (`server.py`), the bridge to the engine (`engine.py`), folder
  scans and thumbnails (`library.py`), the catalog (`catalog.py`), orders
  (`orders.py` for prices and everything worked out from an order,
  `orderbook.py` for storage, `order_routes.py` for the endpoints), and the
  interface (`ui/index.html`), shown in a native window by pywebview (`app.py`).
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
