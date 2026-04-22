"""Pack-size database lookup for vendor part numbers."""
from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackEntry:
    vendor: str
    pn: str
    pack_size: int
    description: str
    last_verified: str


def load_db(path: Path) -> dict[tuple[str, str], PackEntry]:
    """Load parts_db.csv into a {(vendor, pn): PackEntry} dict.

    Returns an empty dict if the file is missing or only has a header.
    """
    db: dict[tuple[str, str], PackEntry] = {}
    if not path.exists():
        return db
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vendor = (row.get("vendor") or "").strip().lower()
            pn = (row.get("pn") or "").strip()
            pack_raw = (row.get("pack_size") or "").strip()
            if not vendor or not pn or not pack_raw:
                continue
            try:
                pack_size = int(pack_raw)
            except ValueError:
                continue
            if pack_size <= 0:
                continue
            db[(vendor, pn)] = PackEntry(
                vendor=vendor,
                pn=pn,
                pack_size=pack_size,
                description=(row.get("description") or "").strip(),
                last_verified=(row.get("last_verified") or "").strip(),
            )
    return db


def lookup(db: dict[tuple[str, str], PackEntry], vendor: str, pn: str) -> PackEntry | None:
    return db.get((vendor, pn))


def product_url(vendor: str, pn: str) -> str:
    if vendor == "mcmaster":
        # McMaster's canonical PN URL resolves to the product page in a browser.
        return f"https://www.mcmaster.com/{pn}/"
    if vendor == "automationdirect":
        # AutomationDirect's own search endpoint returns empty pages, and direct
        # product URLs require knowing the category path. Google site-search
        # reliably lands on the product detail page as the first result.
        from urllib.parse import quote_plus
        return f"https://www.google.com/search?q=site%3Aautomationdirect.com+{quote_plus(pn)}"
    return ""


def append_missing_rows(db_path: Path, entries: list[dict]) -> int:
    """Append skeleton rows for PNs not already in the DB file.

    Writes (vendor, pn, "", description, "") — user fills pack_size + last_verified.
    Returns the number of rows appended. Preserves any existing rows verbatim.
    """
    existing: set[tuple[str, str]] = set()
    header_present = False
    if db_path.exists():
        with open(db_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header_present = rows[0] and rows[0][0].strip().lower() == "vendor"
            data_rows = rows[1:] if header_present else rows
            for r in data_rows:
                if len(r) >= 2 and r[0] and r[1]:
                    existing.add((r[0].strip().lower(), r[1].strip()))

    to_append = [
        e for e in entries
        if (e["vendor"], e["pn"]) not in existing
    ]
    if not to_append:
        return 0

    db_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not db_path.exists() or not header_present
    mode = "a" if db_path.exists() else "w"
    with open(db_path, mode, newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["vendor", "pn", "pack_size", "description", "last_verified"])
        for e in to_append:
            w.writerow([e["vendor"], e["pn"], "", e.get("description", ""), ""])
    return len(to_append)


_DB_COLUMNS = ("vendor", "pn", "pack_size", "description", "last_verified")


def _read_db_rows(db_path: Path) -> list[dict]:
    """Read all rows as dicts, preserving order and untouched columns."""
    if not db_path.exists():
        return []
    with open(db_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_db_rows(db_path: Path, rows: list[dict]) -> None:
    """Atomic write: temp file + rename, so a Ctrl-C mid-write can't corrupt the DB."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(_DB_COLUMNS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _DB_COLUMNS})
    tmp.replace(db_path)


def interactive_fill(db_path: Path) -> int:
    """Walk rows with empty pack_size and prompt for values. Saves after each entry.

    Returns the number of rows filled this session.
    """
    rows = _read_db_rows(db_path)
    if not rows:
        print(f"DB is empty: {db_path}. Run with --populate-db first.")
        return 0

    pending = [i for i, r in enumerate(rows) if not (r.get("pack_size") or "").strip()]
    if not pending:
        print("Nothing to fill — every row already has a pack_size. Done.")
        return 0

    today = _dt.date.today().isoformat()
    filled = 0
    print(f"Filling pack sizes in {db_path}")
    print(f"  {len(pending)} row(s) pending. Enter integer, or 's' to skip, 'q' to save & quit.\n")

    for n, idx in enumerate(pending, start=1):
        row = rows[idx]
        pn = row.get("pn", "")
        vendor = row.get("vendor", "")
        desc = row.get("description", "")
        url = product_url(vendor, pn)
        print(f"[{n}/{len(pending)}] {vendor} / {pn}")
        if desc:
            print(f"  Description: {desc}")
        if url:
            print(f"  URL: {url}")
        while True:
            raw = input("  Pack size: ").strip().lower()
            if raw in ("q", "quit", "exit"):
                _write_db_rows(db_path, rows)
                print(f"\nSaved. Filled {filled} row(s) this session. "
                      f"{len(pending) - n + 1} still pending.")
                return filled
            if raw in ("s", "skip", ""):
                print("  (skipped)\n")
                break
            try:
                pack = int(raw)
            except ValueError:
                print("  Not an integer. Try again, or 's' to skip, 'q' to quit.")
                continue
            if pack <= 0:
                print("  Must be > 0. Try again.")
                continue
            row["pack_size"] = str(pack)
            row["last_verified"] = today
            _write_db_rows(db_path, rows)  # save after every entry
            filled += 1
            print(f"  ✓ saved ({pack}, {today})\n")
            break

    print(f"\nAll done. Filled {filled} row(s).")
    return filled
