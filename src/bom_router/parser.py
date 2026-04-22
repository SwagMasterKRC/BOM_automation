"""Parse Fusion 360 BOM CSVs and identify vendor part numbers."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

MCMASTER_RE = re.compile(r"\b(\d{4,5}[A-Z]\d{1,4})(?:_|\b)")

AD_PREFIXES = (
    "P1-", "KN-", "SE-SW", "GC-", "ACG-", "T1E-", "CWC",
    "GMCBU-", "EN4SD", "ML1-", "EPG", "DN-Q",
    "CMV-", "SBF-", "AVS-", "AR2-", "ME14-", "MS14-",
)

# Other brands whose PNs happen to look like McMaster's \d{4,5}[A-Z]\d{1,4}.
# Reject matches starting with these.
MCMASTER_EXCLUDE_PREFIXES = ("8020",)

_AD_TOKEN_SPLIT = re.compile(r"[\s(]")
_HAS_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class ParsedLine:
    vendor: str
    pn: str
    qty: int
    description: str
    raw_part_name: str
    level: str = ""


@dataclass(frozen=True)
class SkippedLine:
    part_number: str
    part_name: str
    description: str
    qty: int
    reason: str
    level: str = ""


def _match_mcmaster(text: str) -> str | None:
    if not text:
        return None
    for m in MCMASTER_RE.finditer(text):
        pn = m.group(1)
        if any(pn.startswith(p) for p in MCMASTER_EXCLUDE_PREFIXES):
            continue
        return pn
    return None


def _match_automationdirect(text: str) -> str | None:
    if not text:
        return None
    token = _AD_TOKEN_SPLIT.split(text, maxsplit=1)[0]
    for prefix in AD_PREFIXES:
        if not token.startswith(prefix) or len(token) <= len(prefix):
            continue
        # Real AD PNs always contain a digit after the prefix; e.g. "P1-540",
        # "CMV-C1X-4X". Rejects false positives like "P1-PRODUCT" from labels.
        if not _HAS_DIGIT.search(token[len(prefix):]):
            continue
        return token
    return None


def extract_vendor_pn(part_name: str, part_number: str) -> tuple[str, str] | None:
    """Return (vendor, pn) or None. Tries Part Name first, then Part Number."""
    for candidate in (part_name, part_number):
        pn = _match_mcmaster(candidate)
        if pn:
            return ("mcmaster", pn)
    for candidate in (part_name, part_number):
        pn = _match_automationdirect(candidate)
        if pn:
            return ("automationdirect", pn)
    return None


def _iter_bom_rows(csv_path: Path):
    """Yield dict rows from a Fusion BOM, skipping the metadata preamble."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header_idx = next(
        (i for i, r in enumerate(rows) if r and r[0].strip() == "Level"),
        None,
    )
    if header_idx is None:
        raise ValueError(f"No 'Level' header row found in {csv_path} — not a Fusion BOM?")
    header = rows[header_idx]
    for row in rows[header_idx + 1:]:
        if not row or all(c == "" for c in row):
            continue
        yield dict(zip(header, row))


def _in_subtree(level: str, prefix: str) -> bool:
    """True if `level` is `prefix` or a descendant. E.g. prefix='1.7' matches
    '1.7', '1.7.1', '1.7.1.1' but not '1.70'."""
    return level == prefix or level.startswith(prefix + ".")


def parse_bom(
    csv_path: Path,
    level_prefix: str | None = None,
) -> tuple[list[ParsedLine], list[SkippedLine]]:
    parsed: list[ParsedLine] = []
    skipped: list[SkippedLine] = []
    for row in _iter_bom_rows(csv_path):
        level = (row.get("Level") or "").strip()
        if level_prefix and not _in_subtree(level, level_prefix):
            continue
        part_name = (row.get("Part Name") or "").strip()
        part_number = (row.get("Part Number") or "").strip()
        description = (row.get("Description") or "").strip()
        qty_raw = (row.get("Quantity") or "").strip()
        try:
            qty = int(qty_raw) if qty_raw else 1
        except ValueError:
            qty = 1
        if not part_name and not part_number:
            continue
        match = extract_vendor_pn(part_name, part_number)
        if match is None:
            skipped.append(SkippedLine(
                part_number=part_number,
                part_name=part_name,
                description=description,
                qty=qty,
                reason="no vendor pattern match",
                level=level,
            ))
            continue
        vendor, pn = match
        parsed.append(ParsedLine(
            vendor=vendor,
            pn=pn,
            qty=qty,
            description=description or part_name,
            raw_part_name=part_name,
            level=level,
        ))
    return parsed, skipped


def list_subassemblies(csv_path: Path, depth: int = 2) -> list[dict]:
    """Return subassemblies up to `depth` levels deep, with line counts in each subtree.

    Depth 1 = top-level (1, 2, ...), depth 2 = 1.1, 1.2, 1.3, ... etc.
    """
    all_rows = list(_iter_bom_rows(csv_path))
    # Collect distinct levels at exactly `depth` (measured by number of dots + 1).
    candidates: list[dict] = []
    seen: set[str] = set()
    for row in all_rows:
        level = (row.get("Level") or "").strip()
        if not level:
            continue
        parts = level.split(".")
        if len(parts) != depth:
            continue
        if level in seen:
            continue
        seen.add(level)
        name = (row.get("Part Name") or row.get("Part Number") or "").strip()
        # Count every BOM row within this subtree.
        line_count = sum(
            1 for r in all_rows
            if _in_subtree((r.get("Level") or "").strip(), level)
        )
        candidates.append({"level": level, "name": name, "line_count": line_count})
    candidates.sort(key=lambda d: [int(p) if p.isdigit() else p for p in d["level"].split(".")])
    return candidates


def rollup(parsed: list[ParsedLine]) -> dict[tuple[str, str], dict]:
    """Sum quantities across duplicate (vendor, pn) lines."""
    rolled: dict[tuple[str, str], dict] = {}
    for line in parsed:
        key = (line.vendor, line.pn)
        if key not in rolled:
            rolled[key] = {
                "vendor": line.vendor,
                "pn": line.pn,
                "qty": 0,
                "description": line.description,
            }
        rolled[key]["qty"] += line.qty
    return rolled
