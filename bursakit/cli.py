"""Command line interface: ``bursakit prices 1155 --start 2024-01-01 --csv``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

import bursakit

from .errors import BursakitError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bursakit", description="Bursa Malaysia stock data and Malaysian macro series."
    )
    parser.add_argument("--version", action="version", version=f"bursakit {bursakit.__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    def output(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--csv", action="store_true", help="write CSV instead of a table")
        sub.add_argument("--out", metavar="FILE", help="write to FILE instead of the screen")
        sub.add_argument("--refresh", action="store_true", help="ignore the local cache")

    def dates(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--start", metavar="YYYY-MM-DD", help="first date, inclusive")
        sub.add_argument("--end", metavar="YYYY-MM-DD", help="last date, inclusive")

    sub = commands.add_parser("prices", help="daily open, high, low, close, volume")
    sub.add_argument("ticker", help="stock code, .KL symbol or stock name")
    dates(sub)
    output(sub)

    sub = commands.add_parser("dividends", help="dividend history")
    sub.add_argument("ticker", help="stock code, .KL symbol or stock name")
    output(sub)

    sub = commands.add_parser("listings", help="companies listed on Bursa Malaysia")
    output(sub)

    sub = commands.add_parser("opr", help="Overnight Policy Rate decisions")
    dates(sub)
    output(sub)

    sub = commands.add_parser("fx", help="ringgit exchange rates, MYR per 1 unit")
    sub.add_argument("currency", help="currency code, e.g. USD")
    dates(sub)
    output(sub)

    sub = commands.add_parser("resolve", help="show which ticker an input resolves to")
    sub.add_argument("ticker")

    sub = commands.add_parser("cache", help="inspect or empty the local cache")
    sub.add_argument("action", choices=["info", "clear"])
    sub.add_argument("kind", nargs="?", help="with clear: only this data type, e.g. prices")
    return parser


def _emit(df: pd.DataFrame, args: argparse.Namespace) -> None:
    as_csv = args.csv or bool(args.out and str(args.out).lower().endswith(".csv"))
    if as_csv:
        text = df.to_csv(lineterminator="\n", date_format="%Y-%m-%d")
    elif df.empty:
        text = "(no rows)\n"
    else:
        shown = df.copy()
        if isinstance(shown.index, pd.DatetimeIndex):
            shown.index = pd.Index(shown.index.strftime("%Y-%m-%d"), name=shown.index.name)
        text = shown.to_string(max_rows=None, na_rep="") + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {len(df)} rows to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _run(args: argparse.Namespace) -> None:
    if args.command == "prices":
        _emit(bursakit.prices(args.ticker, args.start, args.end, refresh=args.refresh), args)
    elif args.command == "dividends":
        _emit(bursakit.dividends(args.ticker, refresh=args.refresh), args)
    elif args.command == "listings":
        _emit(bursakit.listings(refresh=args.refresh), args)
    elif args.command == "opr":
        _emit(bursakit.macro.opr(args.start, args.end, refresh=args.refresh), args)
    elif args.command == "fx":
        _emit(bursakit.macro.fx(args.currency, args.start, args.end, refresh=args.refresh), args)
    elif args.command == "resolve":
        ticker = bursakit.resolve(args.ticker)
        print(f"{ticker.code}\t{ticker.symbol}\t{ticker.name or ''}".rstrip())
    elif args.action == "info":
        print(json.dumps(bursakit.cache.info(), indent=2))
    else:
        bursakit.cache.clear(args.kind)
        print(f"cleared {args.kind or 'everything'}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except (BursakitError, ValueError) as exc:
        print(f"bursakit: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
