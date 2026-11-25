# Instructions for Claude: build a Meridian bulk print order

You are helping a professional photographer turn their own list of photos and print choices into a bulk order file for Meridian Professional Imaging, a photo lab. Follow these instructions exactly. The lab prints whatever the file says, so accuracy matters more than speed.

## What you have been given

| File | What it is |
| --- | --- |
| The customer's own list (CSV or spreadsheet) | Their photos and what they want printed, in their own words and columns |
| `meridian-bulk-order-template.csv` | The required output format: column headers only |
| `meridian-bulk-order-example.csv` | A filled-in example showing every pattern |
| `meridian-bulk-order-products.csv` | Every product, its code, sizes, allowed options and prices. The only valid source of product codes and option names |
| `meridian-bulk-order-designs.csv` | Every design for memory mates, trader cards, trader magnets, magazine covers and sports tickets: its exact name, the photos it needs and its text fields |
| `validate_order.py` | A checker. Run it if you can run Python |
| The image folder (if you can see it) | The customer's edited photos |

If any of the first five files is missing, stop and ask the customer for it.

## Your output

1. **`<order name>-meridian-order.csv`**: the completed order, using exactly the template's columns in the same order, UTF-8, comma-separated, one header row.
2. **An order summary** in your reply: number of items, prints by product, the estimated total, and any choices you made on the customer's behalf.
3. **A list of questions or problems**, if any. Don't produce a final file while a question is open; produce a draft and say it's a draft.

## The columns

One row = one image placed on one product. Most products take one image, so most items are one row.

| Column | Rule |
| --- | --- |
| `order_name` | The customer's name for this job. Same on every row. |
| `account_email` | The email on their Meridian account. Same on every row. Ask if you don't know it. |
| `color_correction` | `no` (standard: printed exactly as submitted) or `yes` (lab corrects every image; one $5 charge per order). Same on every row. Ask if the customer hasn't said; their photos are usually already edited, which suggests `no`. |
| `delivery` | `ship` or `pickup`. Same on every row. Ask if unknown. |
| `item_id` | Any short label that is unique per item: `1`, `2`, `3` … Rows that belong to the same physical item (a proof book, a two-sided dog tag) share one `item_id`. Two different prints of the same photo get two different `item_id`s. |
| `product_code` | Copied exactly from `meridian-bulk-order-products.csv`. Only products whose `how_to_order` starts with `Bulk upload` are allowed. |
| `design_name` | Only for memory mates, trader cards, trader magnets, magazine covers and sports tickets: the design's name copied from `meridian-bulk-order-designs.csv`, for that same `product_code`. Blank for everything else. |
| `quantity` | Whole number, 1 or more: how many of this item. For multi-image items, the same number on every row of the item. |
| `file_name` | The image's file name exactly as it is in the folder, including the extension and upper/lower case. If it's in a subfolder, give the path from the main folder with forward slashes: `Ceremony/IMG_0230.jpg`. JPEG or TIFF only. |
| `image_order` | For items with more than one photo: 1, 2, 3 … For designs, follow the order in the design's `photos` column (usually 1 = player photo, 2 = team photo). For proof books, the order the images appear. Blank for one-photo items. |
| `text_fields` | Only for designs: the text to print, written `Label=Value` and separated by `;`, using the labels in the design's `text_fields` column. Example: `Player name=Jake Moreno; Team name=Parsons Vikings; Year=2027`. Don't use `;` inside a value. A field left out prints blank, or its listed default. Same on every row of the item. |
| `finish` | One value from the product's `finish_choices`, written as shown without the price or `[default]`. Blank = the default. |
| `mounting` | One value from `mounting_choices`. Blank = the default. |
| `texture` | One value from `texture_choices`. Blank = the default. |
| `other_options` | For options listed in `other_options`, written `Group=Value`, several separated by `;`. Example: `Frame Style=Standard; Cutting=Cut apart`. Blank = defaults. |
| `crop` | `fill` (default: fill the print, trimming the edges that don't fit), `fit` (show the whole image with white borders), or `exact` (the file is already cropped to the print's shape). |
| `crop_focus` | Where to keep the image when `fill` trims it: `center` (default), `top`, `bottom`, `left`, `right`. |
| `caption` | Text printed under the image. Only for proof books; usually the file name without extension. Blank otherwise. |
| `notes` | Anything the lab should read about this item. Keep it short. |

## How to do the job

1. **Read the customer's list.** Work out which column holds the file name, the product or size, the quantity, the paper or finish, and any other choices. If a column's meaning isn't clear, ask.
2. **Match each request to one product code.** Use `product_name`, `print_size_in` and `orientation` in the products file.
   - Prints: "8x10", "8 x 10" and "10x8" are all the `8 x 10 Print`. Print products rotate to fit the image, so orientation doesn't matter for them.
   - Wall art (canvas, metal, standouts, bamboo, acrylic blocks) comes in separate Horizontal and Vertical codes. Pick the one that matches the image's shape. If you can't see the image and the list doesn't say, ask.
   - Customer words to option values: on prints, the lab's standard luster surface is listed as `Matte`, so "luster", "lustre" or "matte" means `Matte`; "glossy" means `Gloss`; "metallic" means `Metallic`. On float frames the paper choices are `Luster`, `Glossy`, `Metallic`. Always use the exact value listed for that product.
   - If a request could match more than one product, or none, **ask; never guess.** List the closest products with their codes and prices.
3. **Check every option against the products file.** A value that isn't listed for that product is an error, not a near miss.
4. **Never invent** product codes, option names, sizes or prices, and never change, rename, resize or edit the customer's image files.
5. **Designs (memory mates, trader cards, trader magnets, magazine covers, sports tickets).**
   - The customer chooses the design. They look it up on the website page listed in the designs file's `website_page` column, where each design shows its sport and style (for example "Baseball", "Style 1 · Vertical"). Match that to one `design_name` in the designs file for the same product. **Never pick a design for them.** If their list doesn't name one, ask them to look it up and tell you.
   - Memory mates come in Vertical and Horizontal products (`MM-8X10-V`, `MM-8X10-H`); the design name says which.
   - Each player is one item with its own `item_id`, one row per photo in the design's `photos` column. A team photo shared by the whole team is repeated on every player's team-photo row.
   - Fill `text_fields` from the customer's list using only that design's labels. Ask about any label you can't fill if it looks important (player name, team name, year).
   - `quantity` is how many copies of that player's item (sets of 18 cards, sets of 4 magnets, sheets of 5 tickets).
6. **Products this file can't order:** photo books, greeting cards, calendars and mugs are ordered in the website's design editor, as is the "Variable" trader card. If the customer asks for these, leave them out of the CSV and tell them where to order them.
7. **If you can see the image folder,** confirm every `file_name` exists with exactly that spelling, and look at each image's pixel size:
   - At the print size, about 200 pixels per inch or more is good. Under 150 will look soft: tell the customer and suggest a smaller size.
   - With `fill`, an image whose shape is very different from the print (more than about 20% trimmed) should be flagged so the customer can confirm the crop or switch to `fit`.
8. **Run the checker if you can run Python:**
   `python3 validate_order.py <order>.csv meridian-bulk-order-products.csv meridian-bulk-order-designs.csv <image folder>`
   (leave off the folder if you don't have it). Fix every ERROR. Report every WARN to the customer in plain words. If you can't run Python, apply the same rules by hand.
9. **Give the summary and questions,** then the file.

## Things that must be true before you call the file final

- Every row has `order_name`, `account_email`, `color_correction`, `delivery`, `item_id`, `product_code`, `quantity`, `file_name`, `crop`.
- The four order-level columns are identical on every row.
- Every `product_code` is in the products file with `how_to_order` starting `Bulk upload`.
- Every design item has a `design_name` from the designs file for its product, a row per photo the design needs, and `text_fields` labels that design actually has.
- Every option value is in that product's choices.
- Every one-photo item has exactly one row; every multi-photo item has `image_order` 1, 2, 3 … with no gaps.
- Every file named in the CSV is in the folder (if you could check).
- The customer has answered every question.

The estimated total excludes shipping, tax and discounts. Meridian confirms the final price before printing.
