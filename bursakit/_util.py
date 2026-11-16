"""Date helpers shared across the package."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

#: Malaysia Time. UTC+8 all year, so no tz database is needed.
MYT = timezone(timedelta(hours=8), "MYT")

DateLike = str | date | datetime | pd.Timestamp


def today() -> date:
    """Today's calendar date in Malaysia."""
    return datetime.now(MYT).date()


def span(start: DateLike | None, end: DateLike | None, *, default: timedelta) -> tuple[date, date]:
    """An inclusive date range: ``end`` defaults to today, ``start`` to ``end - default``."""
    last = to_date(end) if end is not None else today()
    first = to_date(start) if start is not None else last - default
    if first > last:
        raise ValueError(f"start {first} is after end {last}")
    return first, last


def tag(df: pd.DataFrame, kind: str, source: str, **extra: str) -> pd.DataFrame:
    """Record where a result came from in ``df.attrs``."""
    from . import router

    attrs: dict[str, str] = {"kind": kind}
    attrs.update(extra)
    attrs.update(currency="MYR", source=source, attribution=router.attribution(source))
    df.attrs.clear()
    df.attrs.update(attrs)
    return df


def to_date(value: DateLike) -> date:
    """Turn a string, date, datetime or Timestamp into a plain date."""
    if isinstance(value, datetime):  # also covers pd.Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
        try:
            parsed = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"not a date: {value!r}") from exc
        if pd.isna(parsed):
            raise ValueError(f"not a date: {value!r}")
        return parsed.date()
    raise TypeError(f"expected a date or ISO date string, got {type(value).__name__}")
