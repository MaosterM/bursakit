# Week 1 spike: go / no-go

Date: 2026-11-16. Decision: **GO**, with two caveats (listings market column, Yahoo terms).

## What was checked

| Check | Result |
| --- | --- |
| `bursakit` on PyPI | Free (`pypi.org/pypi/bursakit/json` returns 404). |
| `bursakit` on GitHub | No user or org of that name. One unrelated repo, `bursapemancing/bursakita`. |
| Yahoo coverage, 10 tickers, 5 years | 10 of 10. Each returned 1,224 daily rows for 2021-11-01 to 2026-10-30, no missing OHLC, longest gap 6 days (holidays). Currency reported as MYR. |
| Yahoo dividends | Present for all 10 (2 to 20 events each in the window). |
| Yahoo name search | `MAYBANK`, `TENAGA`, `PBBANK` each resolve to the `.KL` code. Unknown names return nothing. |
| Yahoo screener | 1,066 KLS equities with code, short name and long name. Sector is available by querying one sector at a time (1,053 classified). No Main / ACE / LEAP field. |
| BNM Open API, OPR | `GET api.bnm.gov.my/public/opr/year/{year}` works, 2004 onward. One request per year. Responses contain duplicate rows, so the adapter de-duplicates. |
| BNM Open API, FX | `GET /public/exchange-rate/{CCY}/year/{y}/month/{m}?session=1700&quote=rm` works. One request per month. JPY and similar are quoted per 100 units and can have a null middle rate. |
| data.gov.my, FX | `exchangerates_daily_1700` returns buying, middle and selling rates for 27 currencies from 2003, per 1 unit, in a single filtered request. Values match BNM for the days compared. |
| data.gov.my, OPR | No OPR dataset (`id=opr` is a 404). |

The tickers tested: 1155, 1295, 1023, 5347, 5183, 6947, 5225, 3182, 7113, 0166.

## Source order

| Data type | Order | Why |
| --- | --- | --- |
| prices | Yahoo | Only source that qualified. |
| dividends | Yahoo | Same. |
| listings | Yahoo screener | Bursa's site is unverified, so it is not used. |
| name lookup | Yahoo search | One request per new name, then cached. |
| opr | BNM | Only official source. |
| fx | data.gov.my, then BNM | Both official and both carry BNM's 17:00 rates. data.gov.my needs 1 request for any range; BNM needs 12 per year. |

The plan listed BNM first for exchange rates. The order above swaps it because a five-year
FX pull through BNM is 60 requests against 1 through data.gov.my. BNM remains the fallback.

## Terms

Superseded by [source-terms.md](source-terms.md), read on 2026-11-18. The table below is
what this spike knew.

| Source | Status |
| --- | --- |
| data.gov.my | Rate limit read from developer.data.gov.my: 4 requests per minute on the Data Catalogue API, HTTP 429 beyond that. The policy table uses this. Licence wording not read in this spike. |
| BNM | API responds without a key. The terms page did not render to text, so the attribution wording is still to be read by hand. |
| Yahoo | Terms not read in this spike. Access is unofficial; treat as personal and research use until read. |
| Bursa Malaysia | Terms page could not be fetched. Not used by any adapter. |

## Open items before v0.1.0

1. ~~Read the Yahoo, BNM and data.gov.my terms pages by hand and record the wording in the README.~~
   Done in [source-terms.md](source-terms.md).
2. `listings()` cannot fill `market` (Main / ACE / LEAP) from Yahoo. The column exists and is empty until a source with clear terms supplies it.
3. Sector labels are Yahoo's 11 sectors, not Bursa's own classification.
4. Yahoo back-adjusts prices and dividends for splits and bonus issues. The cache detects a changed history on the next refresh and refetches, but figures are split-adjusted, not as-traded.
