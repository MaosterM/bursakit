# Changelog

## 0.1.1 (2026-11-19)

First release on PyPI. No change to the library.

- `pip install bursakit` now works.
- README links point to GitHub, so they work on the PyPI page.
- Releases are built and uploaded to PyPI by GitHub Actions.
- README badges and a chart; a runnable example in `examples/quickstart.ipynb`.

## 0.1.0 (2026-11-18)

First release.

### Data

- `prices(ticker, start, end)`: daily open, high, low, close and volume, from Yahoo Finance.
- `dividends(ticker)`: ex-dates and amounts per share in MYR, from Yahoo Finance.
- `listings()`: Bursa codes with name, company and sector, from Yahoo Finance.
- `resolve(name)`: turns `1155`, `1155.KL` or `MAYBANK` into the same `Ticker`.
- `macro.opr()`: Overnight Policy Rate decisions, from the Bank Negara Malaysia Open API.
- `macro.fx(currency)`: MYR buy, sell and mid rates, from data.gov.my with BNM as the fallback.

### Behaviour

- One schema per data type. Every source's answer is checked against it before it is cached or
  returned, so column names and dtypes never depend on which source answered.
- Local SQLite cache. Past rows are kept and only the missing tail is fetched; today's rows,
  dividends, listings and lookups expire. A changed price history (a split or bonus issue) is
  detected and refetched. A failed refresh keeps what was stored.
- Requests to each source are spaced out and retried with backoff; waits of 5 s or more are
  logged on the `bursakit` logger.
- A price day with a missing value is dropped and logged instead of failing the whole range.
- `df.attrs` records the data type, source, required credit line and a link to the source's
  terms.
- `bursakit` command line tool for every function, with CSV output.

### Known limitations

- Yahoo Finance data is for personal, non-commercial use only and must not be redistributed.
  See [docs/source-terms.md](docs/source-terms.md).
- `listings()` leaves `market` (Main / ACE / LEAP) empty and uses Yahoo's sector names, not
  Bursa's.
- Prices and dividends are adjusted for splits and bonus issues by the source.
