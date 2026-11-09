"""
Generation outage service (ENTSO-E A77 / A80).

Ingest: fetch_and_store_outages() upserts outage documents by mRID.
Read:   outages_for_day() builds the per-day nuclear / large-outage view.
"""

import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generation_outage import GenerationOutage
from app.services.entsoe_client import EntsoEError, fetch_unavailability
from app.utils.timezone import stockholm_day_range_utc

log = logging.getLogger(__name__)

ALL_AREAS = ["SE1", "SE2", "SE3", "SE4"]
DOC_TYPES = ("A77", "A80")

# The six Swedish reactors, in display order: (name, nominal MW)
NUCLEAR_UNITS: list[tuple[str, int]] = [
    ("Forsmark 1", 1100),
    ("Forsmark 2", 1121),
    ("Forsmark 3", 1172),
    ("Ringhals 3", 1063),
    ("Ringhals 4", 1134),
    ("Oskarshamn 3", 1400),
]
OTHER_OUTAGE_MIN_MW = 300  # non-nuclear outages smaller than this are not shown


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; everything stored is UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def normalize_unit_name(name: str | None) -> str:
    """'Forsmark block 1' / 'forsmark  1' -> 'forsmark 1'."""
    n = re.sub(r"\bblock\b", " ", (name or "").lower())
    return re.sub(r"\s+", " ", n).strip()


_NUCLEAR_BY_NORM = {normalize_unit_name(n): (n, mw) for n, mw in NUCLEAR_UNITS}


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def fetch_and_store_outages(
    db: Session,
    start_utc: datetime,
    end_utc: datetime,
    areas: list[str] = ALL_AREAS,
) -> dict:
    """
    Fetch A77 + A80 for each area over [start_utc, end_utc) and upsert by mRID.

    Previously-active rows of the same (area, doc type) overlapping the window
    that this fetch no longer returned are marked "withdrawn" — but only when
    the fetch itself succeeded. A failing area/type is logged and skipped.
    """
    summary = {"fetched": 0, "inserted": 0, "updated": 0, "cancelled": 0, "withdrawn": 0, "errors": 0, "failures": []}
    now = datetime.now(timezone.utc)
    start_utc, end_utc = _aware(start_utc), _aware(end_utc)

    for area in areas:
        for doc_type in DOC_TYPES:
            try:
                outages = fetch_unavailability(area, doc_type, start_utc, end_utc)
            except EntsoEError as exc:
                log.error("FAIL outages %s %s: %s", area, doc_type, exc)
                summary["errors"] += 1
                summary["failures"].append(f"{area}/{doc_type}: {exc}")
                continue
            except Exception as exc:  # parse bugs etc. must not stop the other areas
                log.exception("FAIL outages %s %s (unexpected): %s", area, doc_type, exc)
                summary["errors"] += 1
                summary["failures"].append(f"{area}/{doc_type}: {exc}")
                continue

            by_mrid = {o["mrid"]: o for o in outages}
            existing = {}
            if by_mrid:
                rows = db.execute(select(GenerationOutage).where(GenerationOutage.mrid.in_(list(by_mrid)))).scalars()
                existing = {r.mrid: r for r in rows}

            for mrid, o in by_mrid.items():
                row = existing.get(mrid)
                if row is None:
                    row = GenerationOutage(mrid=mrid)
                    db.add(row)
                    summary["inserted"] += 1
                else:
                    summary["updated"] += 1
                for k, v in o.items():
                    if k != "mrid":
                        setattr(row, k, v)
                row.last_seen_utc = now
                if o["status"] == "cancelled":
                    summary["cancelled"] += 1
            db.flush()

            active = db.execute(
                select(GenerationOutage).where(
                    GenerationOutage.area == area,
                    GenerationOutage.document_type == doc_type,
                    GenerationOutage.status == "active",
                )
            ).scalars()
            for row in active:
                if row.mrid in by_mrid:
                    continue
                if _aware(row.start_utc) < end_utc and _aware(row.end_utc) > start_utc:
                    row.status = "withdrawn"
                    summary["withdrawn"] += 1
            db.commit()
            summary["fetched"] += len(by_mrid)
            log.info("OK   outages %s %s — %d documents", area, doc_type, len(by_mrid))
    return summary


# ---------------------------------------------------------------------------
# Read: per-day view
# ---------------------------------------------------------------------------


def _min_available_in_day(row: GenerationOutage, day_start: datetime, day_end: datetime) -> float | None:
    """Minimum available MW over the part of the row's periods inside the day (None if none inside)."""
    periods = row.available_periods or [
        # No point data: be conservative and treat the unit as fully unavailable.
        {"start": _aware(row.start_utc).isoformat(), "end": _aware(row.end_utc).isoformat(), "mw": 0.0}
    ]
    best = None
    for p in periods:
        ps, pe = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
        if ps < day_end and pe > day_start:
            best = p["mw"] if best is None else min(best, p["mw"])
    return best


def _outage_info(row: GenerationOutage) -> dict:
    return {
        "start": _aware(row.start_utc).isoformat(),
        "end": _aware(row.end_utc).isoformat(),
        "type": "forced" if row.business_type == "A54" else "planned",
        "reason": row.reason_text or row.reason_code or "",
    }


def _worst_per_resource(rows: list[GenerationOutage], day_start: datetime, day_end: datetime) -> dict:
    """
    Group by resource; per resource return (min_available_mw, row_with_min, nominal_mw).
    Only documents actually reducing availability below nominal count.
    Ties on the minimum -> the document with the latest end.
    """
    groups: dict[str, list[GenerationOutage]] = {}
    for r in rows:
        groups.setdefault(r.resource_eic or normalize_unit_name(r.resource_name), []).append(r)

    out = {}
    for key, rs in groups.items():
        nominal = max((float(r.nominal_mw) for r in rs if r.nominal_mw is not None), default=None)
        best = None  # (available, -end_ts, row)
        for r in rs:
            avail = _min_available_in_day(r, day_start, day_end)
            if avail is None:
                continue
            cand = (avail, -_aware(r.end_utc).timestamp(), r)
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best is not None:
            out[key] = (best[0], best[2], nominal)
    return out


def active_outage_rows(db: Session) -> list[GenerationOutage]:
    """All active outage documents; pass to outages_for_day(rows=...) to build many days from one query."""
    return list(db.execute(select(GenerationOutage).where(GenerationOutage.status == "active")).scalars())


def outages_for_day(
    db: Session,
    day: date,
    rows: list[GenerationOutage] | None = None,
    min_mw: float = OTHER_OUTAGE_MIN_MW,
) -> dict:
    """
    Nuclear status (6 reactors) and non-nuclear outages for a Stockholm-local day.

    Non-nuclear outages with unavailable MW >= min_mw are listed; with min_mw <= 0 every
    real reduction (unavailable > 0) is listed, fully-available rows are not.
    """
    day_start, day_end = stockholm_day_range_utc(day)
    if rows is None:
        rows = active_outage_rows(db)
    rows = [r for r in rows if _aware(r.start_utc) < day_end and _aware(r.end_utc) > day_start]

    nuclear_rows: dict[str, list[GenerationOutage]] = {n: [] for n, _ in NUCLEAR_UNITS}
    other_rows: list[GenerationOutage] = []
    for r in rows:
        unit = _NUCLEAR_BY_NORM.get(normalize_unit_name(r.resource_name))
        if unit is not None:
            nuclear_rows[unit[0]].append(r)
        else:
            other_rows.append(r)

    nuclear = []
    offline_mw = 0.0
    for name, nominal in NUCLEAR_UNITS:
        worst = _worst_per_resource(nuclear_rows[name], day_start, day_end)
        # All docs of one unit share a resource; collapse across resource keys defensively.
        pick = min(worst.values(), key=lambda t: (t[0], -_aware(t[1].end_utc).timestamp()), default=None)
        available, outage = float(nominal), None
        if pick is not None and pick[0] < nominal:
            available, outage = max(pick[0], 0.0), _outage_info(pick[1])
        status = "offline" if available == 0 else "reduced" if available < nominal else "running"
        offline_mw += nominal - available
        nuclear.append(
            {
                "name": name,
                "area": "SE3",
                "nominal_mw": nominal,
                "status": status,
                "available_mw": available,
                "outage": outage,
            }
        )

    other = []
    for available, row, nominal in _worst_per_resource(other_rows, day_start, day_end).values():
        if nominal is None:
            continue
        unavailable = nominal - available
        if unavailable > 0 and unavailable >= min_mw:
            other.append(
                {
                    "name": row.resource_name or row.resource_eic or "",
                    "resource_eic": row.resource_eic,
                    "area": row.area,
                    "psr_type": row.psr_type,
                    "nominal_mw": nominal,
                    "available_mw": available,
                    "outage": _outage_info(row),
                }
            )
    other.sort(key=lambda o: o["nominal_mw"] - o["available_mw"], reverse=True)

    return {
        "date": day.isoformat(),
        "nuclear": nuclear,
        "nuclear_offline_mw": offline_mw,
        "other": other,
    }


def nuclear_avg_mw_for_day(rows: list[GenerationOutage], day: date) -> dict[str, float]:
    """
    Time-weighted average available MW per reactor over the Stockholm day.

    Nominal where no document applies; at each instant the minimum across the unit's
    overlapping documents. Unlike outages_for_day (per-day minimum, for the board) a
    few-hour dip barely moves this number.
    """
    day_start, day_end = stockholm_day_range_utc(day)
    per_unit: dict[str, list[tuple[datetime, datetime, float]]] = {n: [] for n, _ in NUCLEAR_UNITS}
    for r in rows:
        unit = _NUCLEAR_BY_NORM.get(normalize_unit_name(r.resource_name))
        if unit is None or not (_aware(r.start_utc) < day_end and _aware(r.end_utc) > day_start):
            continue
        periods = r.available_periods or [
            {"start": _aware(r.start_utc).isoformat(), "end": _aware(r.end_utc).isoformat(), "mw": 0.0}
        ]
        for p in periods:
            ps, pe = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
            ps, pe = max(_aware(ps), day_start), min(_aware(pe), day_end)
            if ps < pe:
                per_unit[unit[0]].append((ps, pe, float(p["mw"])))

    total = (day_end - day_start).total_seconds()
    out = {}
    for name, nominal in NUCLEAR_UNITS:
        spans = per_unit[name]
        cuts = sorted({day_start, day_end, *(t for s, e, _ in spans for t in (s, e))})
        acc = 0.0
        for a, b in zip(cuts, cuts[1:]):
            avail = min([float(nominal)] + [mw for s, e, mw in spans if s <= a and e >= b])
            acc += max(avail, 0.0) * (b - a).total_seconds()
        out[name] = acc / total
    return out
