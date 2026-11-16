"""The output contract: one schema per data type, whatever the source.

``validate`` is the only way a DataFrame gets into the cache or out of the
library. A source that starts returning a different shape fails here.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from .errors import SchemaError

__all__ = [
    "DIVIDENDS",
    "FX",
    "LISTINGS",
    "OPR",
    "PRICES",
    "SCHEMAS",
    "Column",
    "Schema",
    "validate",
]

ColumnType = Literal["float64", "int64", "string"]


@dataclass(frozen=True)
class Column:
    name: str
    dtype: ColumnType
    nullable: bool = False


@dataclass(frozen=True)
class Schema:
    kind: str
    index: str
    index_type: Literal["date", "string"]
    columns: tuple[Column, ...]
    unit: str

    @property
    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]


PRICES = Schema(
    kind="prices",
    index="date",
    index_type="date",
    columns=(
        Column("open", "float64"),
        Column("high", "float64"),
        Column("low", "float64"),
        Column("close", "float64"),
        Column("volume", "int64"),
    ),
    unit="MYR per share; volume in shares",
)

DIVIDENDS = Schema(
    kind="dividends",
    index="date",
    index_type="date",
    columns=(Column("amount", "float64"),),
    unit="MYR per share, indexed by ex-date",
)

LISTINGS = Schema(
    kind="listings",
    index="code",
    index_type="string",
    columns=(
        Column("name", "string"),
        Column("company", "string", nullable=True),
        Column("sector", "string", nullable=True),
        Column("market", "string", nullable=True),
    ),
    unit="one row per listed security",
)

OPR = Schema(
    kind="opr",
    index="date",
    index_type="date",
    columns=(Column("rate", "float64"), Column("change", "float64")),
    unit="percent, indexed by decision date",
)

FX = Schema(
    kind="fx",
    index="date",
    index_type="date",
    columns=(
        Column("buy", "float64", nullable=True),
        Column("sell", "float64", nullable=True),
        Column("mid", "float64"),
    ),
    unit="MYR per 1 unit of the foreign currency",
)

SCHEMAS: dict[str, Schema] = {s.kind: s for s in (PRICES, DIVIDENDS, LISTINGS, OPR, FX)}


def validate(df: object, schema: Schema, *, source: str | None = None) -> pd.DataFrame:
    """Return ``df`` coerced to ``schema``, or raise :class:`SchemaError`.

    The result has exactly the schema's columns in order, the schema's dtypes,
    and a sorted, unique, named index. Extra columns are dropped.
    """
    where = f"{schema.kind} from {source}" if source else schema.kind
    if not isinstance(df, pd.DataFrame):
        raise SchemaError(f"{where}: expected a DataFrame, got {type(df).__name__}")
    missing = [name for name in schema.column_names if name not in df.columns]
    if missing:
        raise SchemaError(f"{where}: missing columns {missing}; got {list(df.columns)}")

    index = _index(df.index, schema, where)
    data = {col.name: _coerce(df[col.name], col, where).to_numpy() for col in schema.columns}
    out = pd.DataFrame(data, index=index)
    for col in schema.columns:  # to_numpy() loses the string dtype; restore it
        if col.dtype == "string":
            out[col.name] = out[col.name].astype("string")
    if not out.index.is_unique:
        dupes = out.index[out.index.duplicated()].unique()[:3].tolist()
        raise SchemaError(f"{where}: duplicate {schema.index} values, e.g. {dupes}")
    out = out.sort_index()
    if schema.kind == "prices":
        _check_prices(out, where)
    return out


def _index(index: pd.Index, schema: Schema, where: str) -> pd.Index:
    if schema.index_type == "string":
        idx = pd.Index(index.astype("string").str.strip(), dtype="string", name=schema.index)
        if idx.hasnans or (idx == "").any():
            raise SchemaError(f"{where}: empty {schema.index} in index")
        return idx

    if len(index) and not (
        isinstance(index, pd.DatetimeIndex)
        or pd.api.types.is_object_dtype(index.dtype)
        or pd.api.types.is_string_dtype(index.dtype)
    ):
        raise SchemaError(f"{where}: index is {index.dtype}, expected dates")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # "could not infer format"
            dates = pd.DatetimeIndex(pd.to_datetime(index))
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"{where}: index is not parseable as dates ({exc})") from exc
    if dates.tz is not None:
        raise SchemaError(f"{where}: index is timezone-aware ({dates.tz}); expected naive dates")
    if dates.hasnans:
        raise SchemaError(f"{where}: missing dates in index")
    if not (dates == dates.normalize()).all():
        raise SchemaError(f"{where}: index has intraday timestamps; expected calendar dates")
    return pd.DatetimeIndex(dates.astype("datetime64[ns]"), name=schema.index)


def _coerce(series: pd.Series, column: Column, where: str) -> pd.Series:
    label = f"{where}: column {column.name!r}"
    if column.dtype == "string":
        text = series.astype("string")
        if not column.nullable and bool(text.isna().any()):
            raise SchemaError(f"{label} has missing values")
        return text

    try:
        numeric = pd.to_numeric(series, errors="raise").astype("float64")
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"{label} is not numeric ({exc})") from exc
    has_nan = bool(numeric.isna().any())
    if has_nan and (not column.nullable or column.dtype == "int64"):
        raise SchemaError(f"{label} has missing values")
    if column.dtype == "int64":
        if bool((numeric != numeric.round()).any()):
            raise SchemaError(f"{label} has non-integer values")
        return numeric.astype("int64")
    return numeric


def _check_prices(df: pd.DataFrame, where: str) -> None:
    ohlc = df[["open", "high", "low", "close"]]
    if bool((ohlc <= 0).any().any()):
        raise SchemaError(f"{where}: non-positive prices")
    if bool((df["low"] > df["high"]).any()):
        raise SchemaError(f"{where}: low is above high")
    if bool((df["volume"] < 0).any()):
        raise SchemaError(f"{where}: negative volume")
