import csv
from io import StringIO
from typing import Dict, Iterable, TextIO

from core.models import TrackedCompany


class CSVFormatError(Exception):
    pass


def _normalize_symbol(raw: str) -> str:
    return (raw or "").strip().upper()


def import_tracked_companies_from_text(
    text: str, *, deactivate_missing: bool = False
) -> Dict[str, int]:
    """Import tracked companies from CSV text.

    Expected headers: symbol, name, industry, sector, market

    Returns a dict with counts: created, updated, deactivated.
    """
    return import_tracked_companies_from_file(
        StringIO(text), deactivate_missing=deactivate_missing
    )


def import_tracked_companies_from_file(
    file_obj: TextIO, *, deactivate_missing: bool = False
) -> Dict[str, int]:
    created = 0
    updated = 0
    seen_symbols: set[str] = set()

    reader = csv.DictReader(file_obj)
    required_headers = {"symbol", "name", "industry", "sector", "market"}
    fieldnames = set(reader.fieldnames or [])
    missing = required_headers - fieldnames
    if missing:
        raise CSVFormatError(
            f"Missing required CSV headers: {', '.join(sorted(missing))}"
        )

    for row in reader:
        symbol = _normalize_symbol(row.get("symbol", ""))
        if not symbol:
            continue
        seen_symbols.add(symbol)
        defaults = {
            "name": (row.get("name") or "").strip(),
            "industry": (row.get("industry") or "").strip(),
            "sector": (row.get("sector") or "").strip(),
            "market": (row.get("market") or "").strip(),
            "is_active": True,
        }
        obj, was_created = TrackedCompany.objects.update_or_create(
            symbol=symbol, defaults=defaults
        )
        if was_created:
            created += 1
        else:
            updated += 1

    deactivated = 0
    if deactivate_missing:
        deactivated = (
            TrackedCompany.objects.exclude(symbol__in=seen_symbols)
            .filter(is_active=True)
            .update(is_active=False)
        )

    return {"created": created, "updated": updated, "deactivated": deactivated}


