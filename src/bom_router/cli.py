"""CLI entry point for bom_router."""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from .database import append_missing_rows, interactive_fill, load_db, lookup
from .output import (
    write_needs_pack_size,
    write_skipped,
    write_surplus_report,
    write_vendor_cart,
)
from .parser import list_subassemblies, parse_bom, rollup

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "parts_db.csv"
DEFAULT_OUTPUT = REPO_ROOT / "output"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(
        prog="bom_router",
        description="Fusion 360 BOM → vendor-specific bulk-order CSVs.",
    )
    ap.add_argument(
        "bom_csv",
        type=Path,
        nargs="?",
        help="Path to Fusion 360 BOM export CSV (not required with --fill-db)",
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Parts database CSV")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    ap.add_argument(
        "--populate-db",
        action="store_true",
        help="After the run, append any newly discovered PNs to the parts DB as "
             "skeleton rows with empty pack_size, so you can fill them in directly.",
    )
    ap.add_argument(
        "--fill-db",
        action="store_true",
        help="Interactive mode: walk every row with an empty pack_size and prompt for "
             "values at the terminal. Saves after each entry so Ctrl-C is safe.",
    )
    ap.add_argument(
        "--list-subassemblies",
        action="store_true",
        help="Print the top two levels of the BOM tree with line counts and exit. "
             "Use to pick a --level to process.",
    )
    ap.add_argument(
        "--level",
        type=str,
        default=None,
        help="Process only a sub-assembly. Pass the Level prefix (e.g. '1.7'); "
             "includes that node and every descendant. Output files are suffixed "
             "with the level (e.g. mcmaster_cart_1.7.csv) to avoid clobbering "
             "full-BOM runs.",
    )
    ap.add_argument(
        "--depth",
        type=int,
        default=2,
        help="Depth for --list-subassemblies (default: 2).",
    )
    args = ap.parse_args(argv)

    if args.fill_db:
        return 0 if interactive_fill(args.db) >= 0 else 1

    if args.bom_csv is None:
        ap.error("bom_csv is required unless --fill-db is used")
    if not args.bom_csv.exists():
        print(f"error: BOM not found: {args.bom_csv}", file=sys.stderr)
        return 2

    if args.list_subassemblies:
        subs = list_subassemblies(args.bom_csv, depth=args.depth)
        if not subs:
            print(f"No sub-assemblies found at depth {args.depth}.")
            return 0
        print(f"Sub-assemblies at depth {args.depth} (pass --level LEVEL to process one):")
        width = max(len(s["level"]) for s in subs)
        for s in subs:
            print(f"  {s['level']:<{width}}  {s['line_count']:>4} lines  {s['name']}")
        return 0

    parsed, skipped = parse_bom(args.bom_csv, level_prefix=args.level)
    total_lines = len(parsed) + len(skipped)
    rolled = rollup(parsed)
    db = load_db(args.db)

    carts: dict[str, list[dict]] = {"mcmaster": [], "automationdirect": []}
    needs_pack: list[dict] = []
    resolved_count = 0

    for (vendor, pn), entry in rolled.items():
        pack = lookup(db, vendor, pn)
        if pack is None:
            needs_pack.append(entry)
            continue
        packs_to_order = math.ceil(entry["qty"] / pack.pack_size)
        carts[vendor].append({
            **entry,
            "pack_size": pack.pack_size,
            "packs_to_order": packs_to_order,
        })
        resolved_count += 1

    out = args.output
    suffix = f"_{args.level}" if args.level else ""
    write_vendor_cart(out / f"mcmaster_cart{suffix}.csv", carts["mcmaster"])
    write_vendor_cart(out / f"automationdirect_cart{suffix}.csv", carts["automationdirect"])
    write_needs_pack_size(out / f"needs_pack_size{suffix}.csv", needs_pack)
    write_skipped(out / f"skipped{suffix}.csv", skipped)
    write_surplus_report(
        out / f"surplus_report{suffix}.txt",
        carts["mcmaster"] + carts["automationdirect"],
    )

    scope = f" (Level {args.level}.*)" if args.level else ""
    print(f"Processed BOM{scope}: {total_lines} lines")
    print(f"  \u2713 {resolved_count} PNs found in database")
    print(f"  ? {len(needs_pack)} PNs need pack size lookup \u2192 {out / f'needs_pack_size{suffix}.csv'}")
    print(f"  \u2298 {len(skipped)} lines skipped \u2192 {out / f'skipped{suffix}.csv'}")

    if args.populate_db and needs_pack:
        appended = append_missing_rows(args.db, needs_pack)
        print(f"  + appended {appended} skeleton row(s) to {args.db}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
