from __future__ import annotations

import pandas as pd
import pytest

from bursakit.errors import SchemaError
from bursakit.schema import FX, LISTINGS, PRICES, SCHEMAS, validate


def bars(**overrides: object) -> pd.DataFrame:
    data: dict[str, object] = {
        "open": [8.9, 8.8],
        "high": [9.0, 8.9],
        "low": [8.7, 8.7],
        "close": [8.8, 8.85],
        "volume": [2000, 1000],
    }
    data.update(overrides)
    return pd.DataFrame(data, index=pd.to_datetime(["2024-01-03", "2024-01-02"]))


def test_valid_frame_is_coerced_to_the_contract() -> None:
    raw = bars(open=[9, 8], volume=[2000.0, 1000.0], extra=["x", "y"])
    raw.index = pd.Index(["2024-01-03", "2024-01-02"])  # ISO strings, unsorted

    out = validate(raw, PRICES)

    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.dtypes.astype(str).tolist() == ["float64"] * 4 + ["int64"]
    assert out.index.name == "date"
    assert str(out.index.dtype) == "datetime64[ns]"
    assert out.index.is_monotonic_increasing
    assert out.loc["2024-01-02", "volume"] == 1000


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (bars().drop(columns="volume"), "missing columns"),
        (bars(close=[8.8, None]), "missing values"),
        (bars(volume=[2000.5, 1000]), "non-integer"),
        (bars(volume=[None, 1000]), "missing values"),
        (bars(close=["n/a", "8.8"]), "not numeric"),
        (bars(low=[9.5, 8.7]), "low is above high"),
        (bars(open=[0.0, 8.8]), "non-positive"),
        (bars(volume=[-1, 1000]), "negative volume"),
        (bars().set_axis(pd.to_datetime(["2024-01-02", "2024-01-02"])), "duplicate"),
        (
            bars().set_axis(pd.to_datetime(["2024-01-02", "2024-01-03"]).tz_localize("UTC")),
            "timezone",
        ),
        (bars().set_axis(pd.to_datetime(["2024-01-02 09:00", "2024-01-03 00:00"])), "intraday"),
        (bars().set_axis([0, 1]), "expected dates"),
        (bars().set_axis(["yesterday", "2024-01-03"]), "not parseable"),
    ],
)
def test_a_changed_shape_fails_loudly(frame: pd.DataFrame, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        validate(frame, PRICES, source="yahoo")


def test_error_names_the_data_type_and_source() -> None:
    with pytest.raises(SchemaError, match="prices from yahoo"):
        validate(bars().drop(columns="close"), PRICES, source="yahoo")
    with pytest.raises(SchemaError, match="expected a DataFrame"):
        validate([1, 2, 3], PRICES)


@pytest.mark.parametrize("kind", sorted(SCHEMAS))
def test_empty_frames_still_carry_the_dtypes(kind: str) -> None:
    schema = SCHEMAS[kind]
    out = validate(pd.DataFrame(columns=schema.column_names), schema)
    assert out.empty
    assert list(out.columns) == schema.column_names
    assert out.index.name == schema.index
    for column in schema.columns:
        assert str(out[column.name].dtype) == column.dtype


def test_listings_keep_leading_zeros_and_allow_unknown_sector() -> None:
    raw = pd.DataFrame(
        {"name": ["INARI", "MAYBANK"], "company": [None, "Malayan Banking Berhad"],
         "sector": ["Technology", None], "market": [None, None]},
        index=["0166", "1155"],
    )  # fmt: skip
    out = validate(raw, LISTINGS)
    assert out.index.tolist() == ["0166", "1155"]
    assert out.index.name == "code"
    assert pd.isna(out.loc["1155", "sector"])
    assert all(str(dtype) == "string" for dtype in out.dtypes)

    raw.loc["1155", "name"] = None
    with pytest.raises(SchemaError, match="'name' has missing values"):
        validate(raw, LISTINGS)


def test_fx_allows_missing_buy_and_sell_but_not_mid() -> None:
    raw = pd.DataFrame(
        {"buy": [None, 4.6], "sell": [None, 4.7], "mid": [4.6, 4.65]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    assert validate(raw, FX)["buy"].isna().sum() == 1
    raw.loc["2024-01-02", "mid"] = None
    with pytest.raises(SchemaError, match="'mid' has missing values"):
        validate(raw, FX)
