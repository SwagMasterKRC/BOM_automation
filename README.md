# BOM_automation
This repo contains everything that is needed to do the BOM automation thingy that we all love so much hopefully.

## What it does

Takes a Fusion 360 BOM export CSV and produces vendor-specific order CSVs you can paste into the bulk-order pages at **McMaster-Carr** and **AutomationDirect** to build a cart in one shot.

## Install

Requires Python 3.10+. From the repo root:

```
pip install -e .
```

The `-e` (editable) install means future edits to the source take effect without reinstalling. Once installed, the commands below work from any directory.

## Usage

```
python -m bom_router path/to/fusion_bom.csv
```

Optional flags:
- `--db path/to/parts_db.csv` — override default `data/parts_db.csv`
- `--output path/to/output_dir` — override default `output/`
- `--populate-db` — after the run, append skeleton rows (empty `pack_size`) for any newly discovered PNs to the DB.
- `--fill-db` — interactive mode. Walks every row in `parts_db.csv` with an empty `pack_size`, shows the description + vendor URL, and prompts you for the pack size at the terminal. Auto-stamps today's date in `last_verified`. Enter `s` to skip a row, `q` to save & quit. Progress is saved after every entry, so Ctrl-C is safe. Usage: `python -m bom_router --fill-db` (no BOM argument needed).
- `--list-subassemblies` — print the BOM tree (top two levels by default) with line counts and exit. Use to pick a sub-assembly to process.
- `--level PREFIX` — process only the sub-assembly at that Level and its descendants. Output files are suffixed with the level (e.g. `mcmaster_cart_1.7.csv`) so they don't clobber a full-BOM run.
- `--depth N` — how many levels deep `--list-subassemblies` should show (default: 2).

After each run it writes five files into `output/`:

| File | Contents |
|---|---|
| `mcmaster_cart.csv` | `part_number,quantity` — quantity is **pack count**, pasteable into McMaster's bulk order page |
| `automationdirect_cart.csv` | Same format for AutomationDirect |
| `needs_pack_size.csv` | PNs whose pack size isn't in the DB yet, with a vendor product URL for each |
| `skipped.csv` | BOM lines that didn't match any vendor pattern (assemblies, internal CAD names, other brands) |
| `surplus_report.txt` | Where pack rounding causes over-ordering (e.g. need 30, pack of 100, surplus 70) |

Stdout summary:

```
Processed BOM: 127 lines
  ✓ 34 PNs found in database
  ? 28 PNs need pack size lookup → output/needs_pack_size.csv
  ⊘ 65 lines skipped → output/skipped.csv
```

## How `data/parts_db.csv` works

Schema: `vendor,pn,pack_size,description,last_verified`

Each row represents **one purchased part**, where `pack_size` is the count per purchase unit on the vendor's website as of `last_verified`. For example, if McMaster sells `91290A115` in boxes of 100, write `mcmaster,91290A115,100,...,2026-04-22`.

**The DB is built lazily.** On each run, any PN the parser finds that isn't in the DB goes to `needs_pack_size.csv` with a clickable vendor URL. You open the URL, look up the pack size, add the row to `parts_db.csv`, and re-run the tool. Over time the DB covers your full catalog.

**Fast-path: `--populate-db` + `--fill-db`.** Instead of hand-editing the CSV:

1. `python -m bom_router new_bom.csv --populate-db` — appends skeleton rows for every new PN.
2. `python -m bom_router --fill-db` — walks those rows one at a time, shows the vendor URL, and prompts you for the pack size at the terminal. Auto-dates each entry. Saves after every row (safe to Ctrl-C).
3. `python -m bom_router new_bom.csv` — final run, now with full DB, produces populated carts.

No spreadsheet app required.

## Per-sub-assembly workflow

For a large BOM (especially one where the same sub-assembly appears multiple times in the CAD tree) it's often safer to process one sub-assembly at a time so you can visually verify each cart against what you actually need to build.

```
# 1. See the structure
python -m bom_router my_bom.csv --list-subassemblies

  Sub-assemblies at depth 2 (pass --level LEVEL to process one):
    1.1     5 lines  Robot Controller and Electrical Cabinet
    1.2     9 lines  Pallet Location Assembly
    1.3    86 lines  7100_FASA_7.5_ND_RH_RLC_T-BASE
    ...
    1.7    57 lines  Conveyor clamp

# 2. Run one sub-assembly
python -m bom_router my_bom.csv --level 1.7

  Processed BOM (Level 1.7.*): 57 lines
    ✓ 16 PNs found in database
    ...

# Outputs are suffixed with the level:
#   output/mcmaster_cart_1.7.csv
#   output/automationdirect_cart_1.7.csv
#   output/surplus_report_1.7.txt
#   output/skipped_1.7.csv
```

Go one level deeper with `--depth 3` to see grandchildren (e.g. `1.3.7 Electrical Panel V2`) and filter on those instead.

## Vendor detection

- **McMaster**: regex `\b(\d{4,5}[A-Z]\d{1,4})(?:_|\b)` — matches e.g. `91290A432`, `60645K361`, `9269K42`, `7410T28`, `2030N22`. Excludes known-other-brand prefixes (`8020*` → 80/20 Inc).
- **AutomationDirect**: product-family prefix match. Current prefix set: `P1-`, `KN-`, `SE-SW`, `GC-`, `ACG-`, `T1E-`, `CWC`, `GMCBU-`, `EN4SD`, `ML1-`, `EPG`, `DN-Q`, `CMV-`, `SBF-`, `AVS-`, `AR2-`, `ME14-`, `MS14-`. Requires at least one digit after the prefix (rejects false positives like `P1-PRODUCT`).

The parser tries `Part Name` first, then falls back to `Part Number` — Fusion often puts CAD noise in one but not the other.

## Output directory

`output/` is gitignored — treat it as per-run scratch.
