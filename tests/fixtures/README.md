# Recorded responses

Recorded on 2026-11-16 by `python tests/record_fixtures.py`. The test suite replays
these and never opens a network connection.

- `http/` holds BNM and data.gov.my response bodies exactly as received. `index.json`
  maps each request URL to its file.
- `yahoo/history_1155.KL.json` is what yfinance returned for Maybank, 2023 to 2024.
- `yahoo/search_*.json` are yfinance search results, unmodified.
- `yahoo/screen.json` is reduced in two ways to keep the repository small: each quote
  keeps only `symbol`, `shortName`, `longName`, `exchange` and `quoteType`, and each
  sector list is cut to its first 30 rows.

Re-record when a source changes shape, then update any test that asserts a recorded value.
