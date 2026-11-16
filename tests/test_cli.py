from __future__ import annotations

import json
from pathlib import Path

import pytest

from bursakit.cli import main

Capture = pytest.CaptureFixture[str]


def test_prices_csv(capsys: Capture) -> None:
    assert main(["prices", "1155", "--start", "2024-01-01", "--end", "2024-01-04", "--csv"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "date,open,high,low,close,volume",
        "2024-01-02,8.89,8.92,8.83,8.92,6414300",
        "2024-01-03,8.92,8.93,8.88,8.89,8678500",
        "2024-01-04,8.9,9.05,8.9,9.03,5560000",
    ]


def test_prices_table_accepts_a_name(capsys: Capture) -> None:
    assert main(["prices", "MAYBANK", "--start", "2024-01-01", "--end", "2024-01-04"]) == 0
    out = capsys.readouterr().out
    assert "close" in out and "2024-01-02" in out and "00:00" not in out


def test_out_file_infers_csv(tmp_path: Path, capsys: Capture) -> None:
    target = tmp_path / "maybank.csv"
    assert main(["dividends", "1155", "--out", str(target)]) == 0
    assert target.read_text("utf-8").splitlines()[:2] == ["date,amount", "2023-03-13,0.3"]
    assert "wrote 4 rows" in capsys.readouterr().err


def test_macro_and_listing_commands(capsys: Capture) -> None:
    assert main(["fx", "USD", "--start", "2024-01-01", "--end", "2024-02-29", "--csv"]) == 0
    assert capsys.readouterr().out.splitlines()[1] == "2024-01-02,4.5975,4.602,4.5998"

    assert main(["opr", "--start", "2023-01-01", "--end", "2024-12-31", "--csv"]) == 0
    assert "2023-05-03,3.0,0.25" in capsys.readouterr().out.splitlines()

    assert main(["listings", "--csv"]) == 0
    assert "1155,MAYBANK,Malayan Banking Berhad,Financial Services," in capsys.readouterr().out


def test_empty_result(capsys: Capture) -> None:
    assert main(["prices", "1155", "--start", "2024-01-06", "--end", "2024-01-07"]) == 0
    assert capsys.readouterr().out == "(no rows)\n"


def test_resolve(capsys: Capture) -> None:
    assert main(["resolve", "maybank"]) == 0
    assert capsys.readouterr().out.split() == ["1155", "1155.KL", "MAYBANK"]
    assert main(["resolve", "166"]) == 0
    assert capsys.readouterr().out.split() == ["0166", "0166.KL"]


def test_cache_commands(capsys: Capture) -> None:
    main(["prices", "1155", "--start", "2024-01-01", "--end", "2024-01-31", "--csv"])
    capsys.readouterr()

    assert main(["cache", "info"]) == 0
    assert json.loads(capsys.readouterr().out)["series"]["prices"]["keys"] == 1
    assert main(["cache", "clear", "prices"]) == 0
    assert main(["cache", "info"]) == 0
    assert json.loads(capsys.readouterr().out)["series"] == {}


def test_errors_exit_with_a_message_not_a_traceback(capsys: Capture) -> None:
    assert main(["prices", "NOTAREALCO"]) == 1
    assert capsys.readouterr().err == "bursakit: no Bursa listing matches 'NOTAREALCO'\n"
    assert main(["fx", "XYZ"]) == 1
    assert "unknown currency" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--version"])
