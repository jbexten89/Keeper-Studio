# Keeper Studio

Keeper's Lightroom-style culling interface and PhotoCropper's print engine in one
desktop app for Jamie Bexten Photography. Cull a shoot, crop every print size,
build class composites and cut out backgrounds without switching programs.

The originals stay untouched as fallbacks: **PhotoCropper** (`E:\Photo Cropper`)
and the web version of **Keeper** (jbexten89/Keeper) keep working exactly as
before. Keeper Studio has its own copy of the engine and its own `config.yaml`,
so changing framing here never changes PhotoCropper.

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

## The four modules

Switch with the tabs at the top or **Ctrl+1…4**.

| Module | What it does |
| --- | --- |
| **Library** | Open a shoot folder; flag picks and rejects; rate and label; use Quick Collection and collections; compare in Grid, Loupe, Compare and Survey with synced zoom; export copies or resized JPEGs. |
| **Crop** | PhotoCropper's face-anchored framing for every print size. Each photo shows its crop boxes (hover a size to see just that one) and a status: *Ready*, *Shortened to fit*, *Placed by hand* or *Needs review* with the reason. Press **A** to place the framing by hand. **Check framing** previews a whole shoot; **Export prints** writes the same folders PhotoCropper does: one per size, *Orders*, *review*, and contact sheets. |
| **Composite** | The class composite builder. Students and teachers come from a collection, the selection or the filmstrip, so you can pick them in Library first. |
| **Cut-out** | Background removal to transparent PNGs, using BiRefNet, the same model PhotoExtractor uses. |

A typical picture day: open the folder → cull in **Library** (P / X, Quick
Collection) → filter to the picks → **Crop** → *Check framing* → fix anything
flagged → *Export prints*.

## Where things live

* `config.yaml`, `models\`, `luts\`: beside the app, editable. In Crop,
  **Framing settings…** edits the main framing numbers and keeps the file's
  comments; a backup is saved as `config.yaml.bak`.
* Flags, ratings, collections, hand-placed crops and settings:
  `%LOCALAPPDATA%\KeeperStudio\catalog.sqlite3`, along with the thumbnail cache.
  They survive app updates.
* Hand-placed crops are also written into the output folder's `manual\` folder
  in PhotoCropper's format when you export, so PhotoCropper honours them too.

## The cut-out model

It's 220 MB, so it isn't in the repository. Setup copies it from
`..\Photo Cropper\models\rembg\` if it finds it there; otherwise Keeper Studio
downloads it the first time you use Cut-out. You can also copy
`birefnet-general-lite.onnx` into `models\rembg\` yourself.

## Structure

* `photocropper/`, `photoextractor/`: PhotoCropper's engine, copied as is. The one
  addition is a small hook in `pipeline._write_crop`, so the app can preview crop
  boxes through exactly the same code path as a real run, without writing files.
* `keeperstudio/`: the app. That's a local server bound to 127.0.0.1 with a
  per-launch token (`server.py`), the bridge to the engine (`engine.py`), folder
  scans and thumbnails (`library.py`), the catalog (`catalog.py`), and the
  interface (`ui/index.html`), shown in a native window by pywebview (`app.py`).
* `run_studio.py --browser` opens the app in your web browser instead of its own
  window, which is handy for troubleshooting.

## Licences

PhotoCropper's engine is MIT (see `LICENSE-PhotoCropper`). Bundled components keep
their own licences: mediapipe and its models (Apache 2.0), rembg (MIT), BiRefNet
(MIT), onnxruntime (MIT), pywebview (BSD), Pillow (MIT-CMU), and Nunito Sans (OFL).
