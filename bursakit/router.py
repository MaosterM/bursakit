"""Source order and fallback, per data type.

``fetch`` tries each source for a data type in order and returns the first
answer that passes the schema check. A source that is down, rate limited or
returning a new shape is skipped in favour of the next one.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .errors import (
    BursakitError,
    NotSupported,
    RateLimited,
    SchemaError,
    SourceUnavailable,
    TickerNotFound,
)
from .schema import SCHEMAS, validate
from .sources import BNM, DataGovMy, Source, Yahoo
from .tickers import Ticker

__all__ = ["ROUTES", "attribution", "fetch", "lookup", "register", "reset", "terms"]

#: Sources to try, in order, for each data type. Official APIs come first
#: wherever one exists. For fx both are official; data.gov.my answers any date
#: range in one request where BNM needs one per month.
ROUTES: dict[str, tuple[str, ...]] = {
    "prices": ("yahoo",),
    "dividends": ("yahoo",),
    "listings": ("yahoo",),
    "lookup": ("yahoo",),
    "opr": ("bnm",),
    "fx": ("datagovmy", "bnm"),
}

_FACTORIES: dict[str, type[Source]] = {"yahoo": Yahoo, "bnm": BNM, "datagovmy": DataGovMy}
_instances: dict[str, Source] = {}


def register(source: Source) -> None:
    """Use ``source`` wherever its ``name`` appears in :data:`ROUTES`."""
    _instances[source.name] = source


def reset() -> None:
    """Drop registered sources and go back to the built-in adapters."""
    _instances.clear()


def _source(name: str) -> Source:
    if name not in _instances:
        _instances[name] = _FACTORIES[name]()
    return _instances[name]


def attribution(source: str) -> str:
    """The credit line for a source name, or the name itself if unknown."""
    if source in _instances or source in _FACTORIES:
        return _source(source).attribution
    return source


def terms(source: str) -> str:
    """The link to a source's terms of use, or "" if unknown."""
    if source in _instances or source in _FACTORIES:
        return _source(source).terms
    return ""


def _attempt(kind: str, *args: Any) -> tuple[Any, str]:
    failures: list[BaseException] = []
    for name in ROUTES[kind]:
        source = _source(name)
        try:
            result = getattr(source, kind)(*args)
            if kind in SCHEMAS:
                result = validate(result, SCHEMAS[kind], source=name)
            return result, name
        except NotSupported as exc:
            failures.append(exc)
        except (TickerNotFound, SourceUnavailable, SchemaError) as exc:
            failures.append(exc)
    raise _summarise(kind, failures)


def _summarise(kind: str, failures: list[BaseException]) -> BursakitError:
    not_found = [f for f in failures if isinstance(f, TickerNotFound)]
    if not_found and len(not_found) == len(failures):
        return not_found[0]
    if failures and all(isinstance(f, RateLimited) for f in failures):
        waits = [f.retry_after for f in failures if isinstance(f, RateLimited) and f.retry_after]
        return RateLimited(
            f"rate limited by every source for {kind}",
            retry_after=min(waits) if waits else None,
            causes=failures,
        )
    detail = "; ".join(f"{type(f).__name__}: {f}" for f in failures) or "no source configured"
    return SourceUnavailable(f"no source could provide {kind} ({detail})", causes=failures)


def fetch(kind: str, *args: Any) -> tuple[pd.DataFrame, str]:
    """The first schema-valid answer for ``kind``, with the name of its source."""
    result, name = _attempt(kind, *args)
    assert isinstance(result, pd.DataFrame)
    return result, name


def lookup(name: str) -> tuple[Ticker, str]:
    """Resolve a stock name through the lookup route."""
    result, source = _attempt("lookup", name)
    assert isinstance(result, Ticker)
    return result, source
