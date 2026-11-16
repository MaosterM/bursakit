"""Local SQLite cache and its expiry rules.

Two kinds of entry:

* **Series** (prices, fx, opr) are stored row by row with a coverage record.
  Rows dated before the day they were fetched are settled and kept for good;
  only the missing head or tail of a requested range is fetched.
* **Values** (dividends, listings, name lookups) are stored whole with a TTL.

Nothing is written without passing :func:`bursakit.schema.validate` first.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import _util
from .schema import SCHEMAS, validate

__all__ = ["TTL", "clear", "frame", "get_value", "info", "path", "put_value", "series"]

MINUTE, HOUR, DAY = 60.0, 3600.0, 86400.0

#: Seconds before an entry is refetched. For series this applies only to rows
#: dated today; older rows never expire.
TTL: dict[str, float] = {
    "prices": 15 * MINUTE,
    "fx": 6 * HOUR,
    "opr": 6 * HOUR,
    "dividends": 24 * HOUR,
    "listings": 7 * DAY,
    "alias": 30 * DAY,
}

#: Relative difference in an overlapping value that means history was restated.
RESTATED = 0.01

_DDL = """
CREATE TABLE IF NOT EXISTS series_rows (
    kind TEXT NOT NULL, key TEXT NOT NULL, date TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (kind, key, date)
);
CREATE TABLE IF NOT EXISTS coverage (
    kind TEXT NOT NULL, key TEXT NOT NULL,
    start TEXT NOT NULL, covered_through TEXT NOT NULL, settled_through TEXT NOT NULL,
    fetched_at REAL NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS vals (
    kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
    source TEXT NOT NULL, fetched_at REAL NOT NULL, expires_at REAL NOT NULL,
    PRIMARY KEY (kind, key)
);
"""

FetchRange = Callable[[date, date], "tuple[pd.DataFrame, str]"]
FetchFrame = Callable[[], "tuple[pd.DataFrame, str]"]


def _now() -> float:
    return time.time()


def path() -> Path:
    """Directory holding the cache database."""
    override = os.environ.get("BURSAKIT_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "bursakit" / "Cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "bursakit"


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    folder = path()
    folder.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(folder / "bursakit.sqlite3", timeout=30)) as con:
        con.executescript(_DDL)
        with con:  # one transaction per block
            yield con


def clear(kind: str | None = None) -> None:
    """Delete everything, or only one data type (``"prices"``, ``"fx"``, ...)."""
    with _db() as con:
        for table in ("series_rows", "coverage", "vals"):
            if kind is None:
                con.execute(f"DELETE FROM {table}")
            else:
                con.execute(f"DELETE FROM {table} WHERE kind = ?", (kind,))


def info() -> dict[str, Any]:
    """Where the cache lives and how much is in it."""
    with _db() as con:
        rows = dict(con.execute("SELECT kind, COUNT(*) FROM series_rows GROUP BY kind").fetchall())
        keys = dict(con.execute("SELECT kind, COUNT(*) FROM coverage GROUP BY kind").fetchall())
        vals = dict(con.execute("SELECT kind, COUNT(*) FROM vals GROUP BY kind").fetchall())
    file = path() / "bursakit.sqlite3"
    return {
        "path": str(file),
        "bytes": file.stat().st_size if file.exists() else 0,
        "series": {kind: {"keys": keys.get(kind, 0), "rows": n} for kind, n in rows.items()},
        "entries": vals,
    }


# --------------------------------------------------------------------- values


def get_value(kind: str, key: str) -> Any | None:
    """A cached JSON value, or ``None`` if absent or expired."""
    hit = _get_entry(kind, key)
    return hit[0] if hit else None


def _get_entry(kind: str, key: str) -> tuple[Any, str] | None:
    with _db() as con:
        row = con.execute(
            "SELECT payload, source, expires_at FROM vals WHERE kind = ? AND key = ?", (kind, key)
        ).fetchone()
    if row is None or row[2] <= _now():
        return None
    return json.loads(row[0]), row[1]


def put_value(kind: str, key: str, value: Any, *, source: str, ttl: float | None = None) -> None:
    now = _now()
    lifetime = TTL[kind] if ttl is None else ttl
    with _db() as con:
        con.execute(
            "INSERT OR REPLACE INTO vals VALUES (?, ?, ?, ?, ?, ?)",
            (kind, key, json.dumps(value), source, now, now + lifetime),
        )


def frame(
    kind: str, key: str, fetch: FetchFrame, *, refresh: bool = False
) -> tuple[pd.DataFrame, str]:
    """A whole-frame entry: served from cache until its TTL passes."""
    schema = SCHEMAS[kind]
    if not refresh:
        hit = _get_entry(kind, key)
        if hit is not None:
            payload, source = hit
            cached = pd.DataFrame.from_records(
                payload, columns=[schema.index, *schema.column_names]
            )
            return validate(cached.set_index(schema.index), schema, source="cache"), source
    fetched, source = fetch()
    df = validate(fetched, schema, source=source)
    put_value(kind, key, _records(df, index=True), source=source)
    return df, source


# --------------------------------------------------------------------- series


@dataclass(frozen=True)
class Coverage:
    """What is stored for one series: an unbroken range of dates."""

    start: date
    covered_through: date
    #: Last date fetched after that day had ended. Rows up to here never expire.
    settled_through: date
    fetched_at: float
    source: str


def coverage(kind: str, key: str) -> Coverage | None:
    with _db() as con:
        row = con.execute(
            "SELECT start, covered_through, settled_through, fetched_at, source "
            "FROM coverage WHERE kind = ? AND key = ?",
            (kind, key),
        ).fetchone()
    if row is None:
        return None
    return Coverage(
        date.fromisoformat(row[0]), date.fromisoformat(row[1]), date.fromisoformat(row[2]),
        row[3], row[4],
    )  # fmt: skip


def plan(
    cov: Coverage | None, start: date, end: date, *, now: float, ttl: float, overlap: int = 0
) -> list[tuple[str, date, date]]:
    """Which ranges must be fetched to answer ``start..end`` from the cache.

    Returns ``(part, from, to)`` tuples, where part is ``"all"``, ``"tail"`` or
    ``"head"``. An empty list means the cache can answer on its own.
    """
    if cov is None:
        return [("all", start, end)]
    ranges: list[tuple[str, date, date]] = []
    stale = now - cov.fetched_at > ttl
    if end > cov.covered_through or (end > cov.settled_through and stale):
        tail_from = cov.settled_through + timedelta(days=1 - overlap)
        ranges.append(("tail", max(tail_from, cov.start), end))
    if start < cov.start:
        ranges.append(("head", start, cov.start - timedelta(days=1)))
    return ranges


def series(
    kind: str,
    key: str,
    start: date,
    end: date,
    fetch: FetchRange,
    *,
    verify: str | None = None,
    overlap: int = 0,
    refresh: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Answer ``start..end`` (inclusive), fetching only what the cache lacks.

    ``verify`` names a column to compare where a tail fetch overlaps stored
    rows. If the values moved (a split restated the history), the whole series
    is refetched.

    ``refresh`` swaps everything stored for the series for a new fetch of
    ``start..end``. Stored rows are only removed once that fetch has succeeded.
    """
    schema = SCHEMAS[kind]
    today = _util.today()
    now = _now()
    end = min(end, today)
    if start > end:
        empty = pd.DataFrame(columns=schema.column_names, index=pd.Index([], dtype="object"))
        return validate(empty, schema), "cache"
    if refresh:
        # Fetch before touching the cache: a failed refresh leaves the stored rows alone.
        df, source = fetch(start, end)
        _store(kind, key, df, start, end, source=source, today=today, now=now, replace=True)
        return _read(kind, key, start, end), source

    cov = coverage(kind, key)
    source = cov.source if cov else ""
    for part, part_start, part_end in plan(
        cov, start, end, now=now, ttl=TTL[kind], overlap=overlap if verify else 0
    ):
        df, source = fetch(part_start, part_end)
        df = validate(df, schema, source=source)
        if (
            part == "tail"
            and verify
            and cov
            and not _agrees(kind, key, df, cov, part_start, verify)
        ):
            full_start = min(start, cov.start)
            df, source = fetch(full_start, end)  # the old history stays if this fails
            _store(
                kind, key, df, full_start, end, source=source, today=today, now=now, replace=True
            )
            break
        _store(kind, key, df, part_start, part_end, source=source, today=today, now=now)
    return _read(kind, key, start, end), source


def _agrees(
    kind: str, key: str, new: pd.DataFrame, cov: Coverage, start: date, column: str
) -> bool:
    """Do freshly fetched rows match what is stored for the settled overlap?"""
    stored = _read(kind, key, start, cov.settled_through)[column]
    fresh = new.loc[new.index <= pd.Timestamp(cov.settled_through), column]
    if not stored.index.equals(fresh.index):
        return False
    if stored.empty:
        return True
    drift = ((stored - fresh).abs() / stored.abs()).max()
    return bool(drift <= RESTATED)


def _store(
    kind: str,
    key: str,
    df: pd.DataFrame,
    start: date,
    end: date,
    *,
    source: str,
    today: date,
    now: float,
    replace: bool = False,
) -> None:
    """Replace the stored rows for ``start..end`` and extend the coverage record.

    With ``replace``, everything stored for the series is swapped for these
    rows in the same transaction, so a reader never sees it half done.
    """
    df = validate(df, SCHEMAS[kind], source=source)  # the only door into the cache
    df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    rows = [(kind, key, r.pop("date"), json.dumps(r)) for r in _records(df, index=True)]
    reached = min(end, today)
    settled = min(end, today - timedelta(days=1))
    with _db() as con:
        if replace:
            con.execute("DELETE FROM series_rows WHERE kind = ? AND key = ?", (kind, key))
            con.execute("DELETE FROM coverage WHERE kind = ? AND key = ?", (kind, key))
        else:
            con.execute(
                "DELETE FROM series_rows WHERE kind = ? AND key = ? AND date BETWEEN ? AND ?",
                (kind, key, start.isoformat(), end.isoformat()),
            )
        con.executemany("INSERT INTO series_rows VALUES (?, ?, ?, ?)", rows)
        old = con.execute(
            "SELECT start, covered_through, settled_through, fetched_at FROM coverage "
            "WHERE kind = ? AND key = ?",
            (kind, key),
        ).fetchone()
        if old is not None:
            new_start = min(start, date.fromisoformat(old[0]))
            reached = max(reached, date.fromisoformat(old[1]))
            settled = max(settled, date.fromisoformat(old[2]))
            # A head fetch says nothing about how fresh today's rows are.
            fetched_at = now if end >= today else old[3]
        else:
            new_start, fetched_at = start, now
        con.execute(
            "INSERT OR REPLACE INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                key,
                new_start.isoformat(),
                reached.isoformat(),
                settled.isoformat(),
                fetched_at,
                source,
            ),
        )


def _read(kind: str, key: str, start: date, end: date) -> pd.DataFrame:
    schema = SCHEMAS[kind]
    with _db() as con:
        rows = con.execute(
            "SELECT date, data FROM series_rows "
            "WHERE kind = ? AND key = ? AND date BETWEEN ? AND ? ORDER BY date",
            (kind, key, start.isoformat(), end.isoformat()),
        ).fetchall()
    df = pd.DataFrame(  # not from_records: pandas 2.x rejects an empty index there
        [json.loads(data) for _, data in rows],
        index=pd.Index([day for day, _ in rows], dtype="object"),
        columns=schema.column_names,
    )
    return validate(df, schema, source="cache")


def _records(df: pd.DataFrame, *, index: bool) -> list[dict[str, Any]]:
    """Rows as JSON-ready dicts: dates as ISO strings, missing values as ``None``."""
    flat = df.reset_index() if index else df
    out: list[dict[str, Any]] = []
    for row in flat.to_dict("records"):
        clean: dict[str, Any] = {}
        for name, value in row.items():
            if isinstance(value, pd.Timestamp):
                clean[str(name)] = value.strftime("%Y-%m-%d")
            elif value is None or value is pd.NA or (isinstance(value, float) and value != value):
                clean[str(name)] = None
            elif hasattr(value, "item"):
                clean[str(name)] = value.item()
            else:
                clean[str(name)] = value
        out.append(clean)
    return out
