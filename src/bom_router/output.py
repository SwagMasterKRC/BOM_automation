"""Write vendor cart CSVs, skip list, pack-size needs, and surplus report."""
from __future__ import annotations

import csv
from pathlib import Path

from .database import product_url


def write_vendor_cart(path: Path, entries: list[dict]) -> None:
    """Write part_number,quantity rows. `quantity` is pack count, not piece count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["part_number", "quantity"])
        for e in entries:
            w.writerow([e["pn"], e["packs_to_order"]])


def write_needs_pack_size(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vendor", "pn", "pieces_needed", "description", "product_url"])
        for e in entries:
            w.writerow([
                e["vendor"],
                e["pn"],
                e["qty"],
                e.get("description", ""),
                product_url(e["vendor"], e["pn"]),
            ])


def write_skipped(path: Path, skipped) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["part_number", "part_name", "description", "qty", "reason"])
        for s in skipped:
            w.writerow([s.part_number, s.part_name, s.description, s.qty, s.reason])


def write_surplus_report(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in entries:
        surplus = e["packs_to_order"] * e["pack_size"] - e["qty"]
        if surplus <= 0:
            continue
        lines.append(
            f"PN {e['pn']}: need {e['qty']}, ordering {e['packs_to_order']} "
            f"pack{'s' if e['packs_to_order'] != 1 else ''} of {e['pack_size']}, "
            f"surplus {surplus}"
        )
    with open(path, "w", encoding="utf-8") as f:
        if lines:
            f.write("\n".join(lines) + "\n")
        else:
            f.write("No surplus — all quantities divide evenly into pack sizes.\n")
