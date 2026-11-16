from __future__ import annotations

from typing import Any

import pytest

import bursakit
from bursakit import router
from bursakit.errors import TickerNotFound
from bursakit.sources import Yahoo
from bursakit.tickers import Ticker, parse, resolve
from tests.conftest import Offline


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (1155, "1155"),
        ("1155", "1155"),
        ("1155.KL", "1155"),
        (" 1155.kl ", "1155"),
        (166, "0166"),
        ("166", "0166"),
        ("0166", "0166"),
        ("0820EA", "0820EA"),
        ("5235ss.kl", "5235SS"),
    ],
)
def test_codes_resolve_without_a_lookup(raw: object, code: str, offline: Offline) -> None:
    assert resolve(raw) == Ticker(code)
    assert offline.yf.calls == []


@pytest.mark.parametrize("raw", ["MAYBANK", "99SMART", "", "12345678", 0, 10_000, True, None, 3.5])
def test_parse_returns_none_for_anything_that_is_not_a_code(raw: object) -> None:
    assert parse(raw) is None


def test_code_symbol_and_name_are_one_ticker() -> None:
    by_code, by_symbol, by_name = resolve(1155), resolve("1155.KL"), resolve("MAYBANK")
    assert by_code.code == by_symbol.code == by_name.code == "1155"
    assert by_name.name == "MAYBANK"
    assert by_name.symbol == "1155.KL"
    assert str(by_name) == "1155"
    assert resolve(by_name) is by_name
    assert bursakit.resolve("maybank") == by_name


def test_a_name_is_looked_up_once_then_cached(offline: Offline) -> None:
    resolve("Maybank")
    resolve("MAYBANK")
    resolve("maybank.kl")
    assert offline.yf.calls == [("search", "MAYBANK")]


@pytest.mark.parametrize("raw", ["NOTAREALCO", "PUBLIC", "", "!!", "A", "x" * 40, None, 3.5, -5])
def test_unknown_inputs_raise_ticker_not_found(raw: object) -> None:
    with pytest.raises(TickerNotFound) as caught:
        resolve(raw)
    assert caught.value.ticker == str(raw)
    assert isinstance(caught.value, LookupError)


def test_near_misses_are_offered_as_suggestions() -> None:
    class Stub:
        def search(self, query: str) -> list[dict[str, Any]]:
            return [
                {"symbol": "1155.KL", "shortname": "MAYBANK"},
                {"symbol": "BNII.JK", "shortname": "Bank Maybank Indonesia"},
                {"symbol": "5258.KL", "shortname": "BIMB"},
            ]

    router.register(Yahoo(Stub()))  # type: ignore[arg-type]
    with pytest.raises(TickerNotFound, match="did you mean MAYBANK, BIMB") as caught:
        resolve("MAYBAN")
    assert caught.value.suggestions == ("MAYBANK", "BIMB")
