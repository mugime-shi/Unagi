"""
"Today story": one rule-based headline about Swedish electricity for a day.

Spec: work/SPEC_2026-11-07_today_story.md. Every rule turns already-stored data
into a scored candidate; the highest score wins, with a rotation so the same
kind never headlines three days in a row. Pure templates, no LLM.

Timestamps are stored in UTC. SQL stays portable to SQLite (tests), so rows are
fetched plain and bucketed into Europe/Stockholm days here in Python.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.utils.timezone import STOCKHOLM, stockholm_midnight_utc

AREAS = ("SE1", "SE2", "SE3", "SE4")
ROTATION_DAYS = 7  # days replayed from the start so the result is deterministic per request
PRICE_HISTORY_DAYS = 365
WIND_HISTORY_DAYS = 30
FORECAST_HISTORY_DAYS = 28
PCTL_WINDOW_DAYS = 90
MIN_PCTL_HISTORY = 30  # days of history needed before a percentile rule may fire
MIN_COMPLETE_MINUTES = 20 * 60  # a day with less price coverage is treated as missing
MIN_WIND_SLOTS = 16
MIN_FORECAST_HOURS = 18
FORECAST_GOOD_MAX_SEK = 0.10
FORECAST_MISS_MIN_SEK = 0.20
TOMORROW_MIN_DELTA_SEK = 0.15
# Tie-break order when scores are equal (deterministic output).
KIND_ORDER = [
    "negative",
    "low",
    "high",
    "spread",
    "swing",
    "wind",
    "coupled",
    "forecast",
    "tomorrow",
    "baseline",
]


@dataclass
class DayStats:
    minutes: float = 0.0
    weighted_sum: float = 0.0  # SEK/kWh * minutes
    min_price: float = math.inf
    min_time: datetime | None = None
    max_price: float = -math.inf
    max_time: datetime | None = None
    neg_minutes: float = 0.0

    @property
    def avg(self) -> float:
        return self.weighted_sum / self.minutes

    @property
    def complete(self) -> bool:
        return self.minutes >= MIN_COMPLETE_MINUTES


@dataclass
class Candidate:
    kind: str
    area: str
    score: float
    text: str
    sub: str | None = None


@dataclass
class StoryData:
    prices: dict[str, dict[date, DayStats]] = field(default_factory=lambda: {a: {} for a in AREAS})
    # (area, day, stockholm hour) -> [weighted sum, minutes]; only inside the forecast window
    hourly: dict[tuple[str, date, int], list[float]] = field(default_factory=dict)
    wind: dict[date, list[float]] = field(default_factory=dict)  # day -> [wind MW sum, total MW sum, slots]
    forecast: dict[str, dict[date, list[tuple[int, float]]]] = field(default_factory=dict)
    _cache: dict[date, list[Candidate]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _local(ts) -> datetime:
    if isinstance(ts, str):  # SQLite returns raw timestamps as strings
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(STOCKHOLM)


def _as_date(v) -> date:
    return date.fromisoformat(v) if isinstance(v, str) else v


def _utc_naive(d: date) -> datetime:
    return stockholm_midnight_utc(d).replace(tzinfo=None)


def load_story_data(db: Session, first_day: date, last_day: date) -> StoryData:
    """Load everything the rules need to build stories for first_day..last_day.

    Reaches ROTATION_DAYS-1 days before first_day so the rotation replay has data.
    """
    data = StoryData()
    replay_start = first_day - timedelta(days=ROTATION_DAYS - 1)

    fc_start = replay_start - timedelta(days=FORECAST_HISTORY_DAYS)
    fc_rows = db.execute(
        text(
            """
            SELECT area, target_date, hour, predicted_sek_kwh
            FROM forecast_accuracy
            WHERE model_name = 'lgbm'
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"start": fc_start.isoformat(), "end": last_day.isoformat()},
    ).all()
    for area, target_date, hour, pred in fc_rows:
        data.forecast.setdefault(area, defaultdict(list))[_as_date(target_date)].append((int(hour), float(pred)))

    price_rows = db.execute(
        text(
            """
            SELECT area, timestamp_utc, price_sek_kwh, resolution
            FROM spot_prices
            WHERE timestamp_utc >= :start AND timestamp_utc < :end
              AND price_sek_kwh IS NOT NULL
            """
        ),
        {
            "start": _utc_naive(replay_start - timedelta(days=PRICE_HISTORY_DAYS)),
            "end": _utc_naive(last_day + timedelta(days=2)),  # through D+1
        },
    ).all()
    for area, ts, price, resolution in price_rows:
        if area not in data.prices:
            continue
        price = float(price)
        minutes = 15.0 if resolution == "PT15M" else 60.0
        local = _local(ts)
        day = local.date()
        st = data.prices[area].setdefault(day, DayStats())
        st.minutes += minutes
        st.weighted_sum += price * minutes
        if price < st.min_price:
            st.min_price, st.min_time = price, local
        if price > st.max_price:
            st.max_price, st.max_time = price, local
        if price < 0:
            st.neg_minutes += minutes
        if day >= fc_start and area in data.forecast:
            h = data.hourly.setdefault((area, day, local.hour), [0.0, 0.0])
            h[0] += price * minutes
            h[1] += minutes

    gen_rows = db.execute(
        text(
            """
            SELECT timestamp_utc,
                   SUM(CASE WHEN psr_type IN ('B18', 'B19') THEN value_mw ELSE 0 END) AS wind_mw,
                   SUM(value_mw) AS total_mw
            FROM generation_mix
            WHERE timestamp_utc >= :start AND timestamp_utc < :end
            GROUP BY timestamp_utc
            """
        ),
        {
            "start": _utc_naive(replay_start - timedelta(days=WIND_HISTORY_DAYS)),
            "end": _utc_naive(last_day + timedelta(days=1)),
        },
    ).all()
    for ts, wind_mw, total_mw in gen_rows:
        w = data.wind.setdefault(_local(ts).date(), [0.0, 0.0, 0])
        w[0] += float(wind_mw or 0)
        w[1] += float(total_mw or 0)
        w[2] += 1
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ore(sek_kwh: float) -> int:
    return round(sek_kwh * 100)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _pct_rank(history: list[float], x: float) -> float:
    """Mid-rank percentile of x within history (ties count half), 0-100."""
    below = sum(1 for h in history if h < x)
    equal = sum(1 for h in history if h == x)
    return 100 * (below + 0.5 * equal) / len(history)


def _day_stats(data: StoryData, area: str, day: date) -> DayStats | None:
    st = data.prices[area].get(day)
    return st if st and st.complete else None


def _window(data: StoryData, area: str, day: date, days: int) -> list[DayStats]:
    """Complete days in [day-days, day-1]."""
    out = []
    for k in range(1, days + 1):
        st = _day_stats(data, area, day - timedelta(days=k))
        if st:
            out.append(st)
    return out


def _fmt_hours(minutes: float) -> str:
    if minutes < 60:
        return f"{round(minutes)} minutes"
    h = round(minutes / 60, 1)
    return "1 hour" if h == 1 else f"{h:g} hours"


def _best_per_kind(cands: list[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for c in cands:
        if c.kind not in best or c.score > best[c.kind].score:
            best[c.kind] = c
    return list(best.values())


# ---------------------------------------------------------------------------
# Rules — each returns candidates for one day
# ---------------------------------------------------------------------------


def _rule_negative(data: StoryData, day: date) -> list[Candidate]:
    zones = [(a, st.neg_minutes) for a in AREAS if (st := data.prices[a].get(day)) and st.neg_minutes >= 15]
    if not zones:
        return []
    zones.sort(key=lambda z: (-z[1], z[0]))
    area, minutes = zones[0]
    sub = "Producers are paying to deliver power — typically strong wind meeting low demand."
    others = sorted(a for a, _ in zones[1:])
    if others:
        sub += f" Also negative in {' and '.join(others) if len(others) < 3 else ', '.join(others)}."
    return [
        Candidate(
            "negative",
            area,
            60 + 3 * min(minutes / 60, 12),
            f"Prices dip below zero for {_fmt_hours(minutes)} in {area}",
            sub,
        )
    ]


def _rule_low_high(data: StoryData, day: date) -> list[Candidate]:
    out = []
    for area in AREAS:
        st = _day_stats(data, area, day)
        if not st:
            continue
        a = st.avg
        for kind, word, blocks in (
            ("low", "cheapest", lambda h: h <= a),
            ("high", "priciest", lambda h: h >= a),
        ):
            n, since = None, None
            complete_days = [d for d in data.prices[area] if _day_stats(data, area, d) and d < day]
            for k in range(1, PRICE_HISTORY_DAYS + 1):
                d = day - timedelta(days=k)
                prev = _day_stats(data, area, d)
                if prev and blocks(prev.avg):
                    n, since = k, d
                    break
            if n is None:
                if not complete_days:
                    continue
                span = (day - min(complete_days)).days
                if span >= PRICE_HISTORY_DAYS - 7:
                    n, since = PRICE_HISTORY_DAYS, None
                else:
                    n = span  # data does not reach back a year; only claim what we can see
            if n < 14:
                continue
            if since is not None:
                title = f"{area}'s {word} day since {since.day} {since:%B}"
            elif n >= PRICE_HISTORY_DAYS - 7:
                title = f"{area}'s {word} day in over a year"
            else:
                title = f"{area}'s {word} day in {n} days"
            prev30 = _window(data, area, day, 30)
            sub = f"Averaging {_ore(a)} öre/kWh"
            if len(prev30) >= 10:
                sub += f", against {_ore(sum(p.avg for p in prev30) / len(prev30))} over the past 30 days"
            out.append(Candidate(kind, area, min(100, 40 + 15 * math.log2(n / 14)), title, sub + "."))
    return out


def _rule_spread(data: StoryData, day: date) -> list[Candidate]:
    n, s = _day_stats(data, "SE4", day), _day_stats(data, "SE1", day)
    if not n or not s:
        return []
    diff = n.avg - s.avg
    history = []
    for k in range(1, PCTL_WINDOW_DAYS + 1):
        d = day - timedelta(days=k)
        a, b = _day_stats(data, "SE4", d), _day_stats(data, "SE1", d)
        if a and b:
            history.append(a.avg - b.avg)
    if len(history) < MIN_PCTL_HISTORY or _ore(diff) < 20:
        return []
    rank = _pct_rank(history, diff)
    if rank < 90:
        return []
    return [
        Candidate(
            "spread",
            "SE4",
            50 + 3 * (rank - 90),
            f"Southern Sweden pays {_ore(diff)} öre more than the north",
            f"SE4 averages {_ore(n.avg)} öre/kWh, SE1 just {_ore(s.avg)} — the grid between them is congested.",
        )
    ]


def _rule_coupled(data: StoryData, day: date) -> list[Candidate]:
    def coupled(d: date) -> bool | None:
        sts = [_day_stats(data, a, d) for a in AREAS]
        if not all(sts):
            return None
        avgs = [s.avg for s in sts]
        return round(max(avgs) - min(avgs), 6) < 0.01

    if not coupled(day):
        return []
    history = [c for k in range(1, PCTL_WINDOW_DAYS + 1) if (c := coupled(day - timedelta(days=k))) is not None]
    if len(history) < MIN_PCTL_HISTORY or sum(history) / len(history) >= 0.30:
        return []
    mean = sum(_day_stats(data, a, day).avg for a in AREAS) / 4
    return [
        Candidate(
            "coupled",
            "ALL",
            35,
            "One price for all of Sweden today",
            f"All four zones average {_ore(mean)} öre/kWh — no bottleneck on the grid.",
        )
    ]


def _rule_swing(data: StoryData, day: date) -> list[Candidate]:
    out = []
    for area in AREAS:
        st = _day_stats(data, area, day)
        if not st:
            continue
        history = [p.max_price - p.min_price for p in _window(data, area, day, PCTL_WINDOW_DAYS)]
        if len(history) < MIN_PCTL_HISTORY:
            continue
        rng = st.max_price - st.min_price
        rank = _pct_rank(history, rng)
        if rank < 90:
            continue
        lo, hi = (st.min_time, st.max_time)
        first, second = (
            ((st.min_price, lo), (st.max_price, hi)) if lo <= hi else ((st.max_price, hi), (st.min_price, lo))
        )
        out.append(
            Candidate(
                "swing",
                area,
                45 + 2 * (rank - 90),
                f"{area} swings {_ore(rng)} öre today",
                f"From {_ore(first[0])} öre at {_hhmm(first[1])} to {_ore(second[0])} at {_hhmm(second[1])}.",
            )
        )
    return out


def _wind_share(w: list[float]) -> float | None:
    return w[0] / w[1] if w[2] >= MIN_WIND_SLOTS and w[1] > 0 else None


def _rule_wind(data: StoryData, day: date, today: date) -> list[Candidate]:
    w = data.wind.get(day)
    share = _wind_share(w) if w else None
    if share is None:
        return []
    past = [
        s
        for k in range(1, WIND_HISTORY_DAYS + 1)
        if (wk := data.wind.get(day - timedelta(days=k))) and (s := _wind_share(wk)) is not None
    ]
    if len(past) < 10:
        return []
    usual = sum(past) / len(past)
    if usual <= 0:
        return []
    ratio = share / usual
    if 0.5 < ratio < 1.5:
        return []
    if ratio >= 1.5:
        rel = "twice the usual" if ratio >= 1.95 else f"{ratio:.1f}x the usual"
        title = f"Wind supplies {round(share * 100)}% of Sweden's power, {rel}"
    else:
        title = f"Wind falls quiet: {round(share * 100)}% of generation vs {round(usual * 100)}% usual"
    return [
        Candidate(
            "wind",
            "ALL",
            min(80, 40 + 40 * abs(ratio - 1)),
            title,
            "So far today." if day == today else None,
        )
    ]


def _daily_mae(data: StoryData, area: str, day: date) -> float | None:
    errs = []
    for hour, pred in data.forecast.get(area, {}).get(day, []):
        h = data.hourly.get((area, day, hour))
        if h and h[1] > 0:
            errs.append(abs(pred - h[0] / h[1]))
    return sum(errs) / len(errs) if len(errs) >= MIN_FORECAST_HOURS else None


def _rule_forecast(data: StoryData, day: date) -> list[Candidate]:
    out = []
    for area in data.forecast:
        mae = _daily_mae(data, area, day)
        if mae is None:
            continue
        history = [
            m
            for k in range(1, FORECAST_HISTORY_DAYS + 1)
            if (m := _daily_mae(data, area, day - timedelta(days=k))) is not None
        ]
        if len(history) < 14:
            continue
        rank = _pct_rank(history, mae)
        # Rank alone would call a 19-öre miss "nailed" after a volatile month;
        # the absolute bounds keep the wording honest.
        if rank <= 10 and mae <= FORECAST_GOOD_MAX_SEK:
            out.append(
                Candidate(
                    "forecast",
                    area,
                    35,
                    f"Our {area} forecast nailed today: within {_ore(mae)} öre on average",
                )
            )
        elif rank >= 90 and mae >= FORECAST_MISS_MIN_SEK:
            out.append(
                Candidate(
                    "forecast",
                    area,
                    45,
                    f"Today caught our {area} forecast off guard: off by {_ore(mae)} öre per hour",
                )
            )
    return out


def _rule_tomorrow(data: StoryData, day: date) -> list[Candidate]:
    today_st, tom_st = (
        _day_stats(data, "SE3", day),
        _day_stats(data, "SE3", day + timedelta(days=1)),
    )
    if not today_st or not tom_st or today_st.avg <= 0:
        return []
    change = tom_st.avg / today_st.avg - 1
    # Near-zero days turn small moves into "+629%"; require a real öre change
    # and state the prices instead of the ratio.
    if abs(change) < 0.30 or abs(tom_st.avg - today_st.avg) < TOMORROW_MIN_DELTA_SEK:
        return []
    word = "jumps" if change > 0 else "drops"
    return [
        Candidate(
            "tomorrow",
            "SE3",
            30,
            f"Tomorrow SE3 {word} to {_ore(tom_st.avg)} öre/kWh, from {_ore(today_st.avg)} today",
            "Day-ahead prices for tomorrow are out.",
        )
    ]


def _rule_baseline(data: StoryData, day: date) -> list[Candidate]:
    for area in ("SE3", "SE4", "SE2", "SE1"):
        st = _day_stats(data, area, day)
        if not st:
            continue
        sub = None
        prev30 = _window(data, area, day, 30)
        if len(prev30) >= 10:
            mean = sum(p.avg for p in prev30) / len(prev30)
            if mean > 0:
                pct = round((st.avg / mean - 1) * 100)
                sub = (
                    "In line with the 30-day average."
                    if pct == 0
                    else f"{abs(pct)}% {'above' if pct > 0 else 'below'} the 30-day average."
                )
        return [
            Candidate(
                "baseline",
                area,
                10,
                f"{area} averages {_ore(st.avg)} öre/kWh today",
                sub,
            )
        ]
    return [Candidate("baseline", "SE3", 10, "Today's spot prices are not in yet", None)]


def candidates_for(data: StoryData, day: date, today: date) -> list[Candidate]:
    """All fired candidates for a day, one per kind, best first."""
    if day not in data._cache:
        cands = (
            _rule_negative(data, day)
            + _rule_low_high(data, day)
            + _rule_spread(data, day)
            + _rule_coupled(data, day)
            + _rule_swing(data, day)
            + _rule_wind(data, day, today)
            + _rule_forecast(data, day)
            + _rule_tomorrow(data, day)
            + _rule_baseline(data, day)
        )
        data._cache[day] = sorted(
            _best_per_kind(cands),
            key=lambda c: (-c.score, KIND_ORDER.index(c.kind), c.area),
        )
    return data._cache[day]


# ---------------------------------------------------------------------------
# Headline selection with rotation
# ---------------------------------------------------------------------------


def replay_headlines(data: StoryData, day: date, today: date) -> tuple[list[Candidate], list[Candidate]]:
    """Headlines for D-6..D (oldest first) and the sorted candidates of D.

    A kind that headlined the previous two days is skipped. Days before D-7
    count as "no headline", which keeps the result a pure function of the
    loaded data (no stored state between requests).
    """
    headlines: list[Candidate] = []
    cands: list[Candidate] = []
    for k in range(ROTATION_DAYS - 1, -1, -1):
        cands = candidates_for(data, day - timedelta(days=k), today)
        blocked = None
        if len(headlines) >= 2 and headlines[-1].kind == headlines[-2].kind:
            blocked = headlines[-1].kind
        # Baseline is the last resort: if it is the only thing left it must still show.
        headlines.append(next((c for c in cands if c.kind != blocked), cands[-1]))
    return headlines, cands


def build_story(data: StoryData, day: date, today: date) -> dict:
    headlines, cands = replay_headlines(data, day, today)
    headline = headlines[-1]
    facts = [{"kind": c.kind, "area": c.area, "text": c.text} for c in cands if c.kind != headline.kind][:3]
    return {
        "date": day.isoformat(),
        "headline": {
            "kind": headline.kind,
            "area": headline.area,
            "text": headline.text,
            "sub": headline.sub,
        },
        "facts": facts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_story(db: Session, day: date, today: date) -> dict:
    return build_story(load_story_data(db, day, day), day, today)
