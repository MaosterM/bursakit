# Source terms

Read on 2026-11-18. This is a summary of each source's published terms as they apply to
bursakit, not legal advice. Section numbers refer to the page linked in each heading. Re-read
the pages before relying on this, and when a source is added or a release goes public.

bursakit ships no data. Each user's copy fetches data for that user and stores it in that
user's local cache. What a user may then do with the data is set by the terms below.

## Summary

| Source | Used for | Commercial use | Redistribution | Credit required |
| --- | --- | --- | --- | --- |
| Bank Negara Malaysia | `macro.opr`, `macro.fx` (fallback) | Yes, free | Yes | "Source: Bank Negara Malaysia" and a link to the terms |
| data.gov.my | `macro.fx` | Yes (CC BY 4.0) | Yes | Credit the source and name the licence |
| Yahoo Finance | `prices`, `dividends`, `listings`, name lookup | No, without written permission | No, without written permission | None stated |
| Bursa Malaysia | Not used | No, without written consent | No, without written consent | n/a |

## Bank Negara Malaysia

[Terms of Use for BNM Datasets](https://www.bnm.gov.my/terms-of-use-bnm-datasets), updated
November 2023. They apply to data where BNM is the compiler (section 1), which covers the OPR
and BNM's exchange rates. BNM owns the data (section 7).

- Free to use, for commercial and non-commercial purposes (sections 2 and 3).
- The data may be copied, published, distributed, adapted, and combined into a product
  (section 3).
- The product must carry the statement "Source: Bank Negara Malaysia" (4(a)) and a link to the
  dataset terms (4(b)).
- Do not suggest BNM endorses the product (4(d)), and do not put BNM's name or emblem on the
  data other than in that statement (4(f), 4(g)).
- The [Open API FAQ](https://apikijangportal.bnm.gov.my/faq) says the API is free for anyone.
  No API key or rate limit is published. Requests must send the `Accept` header the FAQ names,
  which the adapter does.

bursakit sets `df.attrs["attribution"]` to the required statement and `df.attrs["terms"]` to
the link.

## data.gov.my

The dataset the adapter reads,
[Daily Exchange Rates (1700)](https://data.gov.my/data-catalogue/exchangerates_daily_1700),
names BNM as its source and is published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The developer portal footer gives
the same licence.

- CC BY 4.0 allows commercial use and redistribution, with credit, a link to the licence, and a
  note of any changes made.
- Because the rates are BNM's, the credit names both: "Source: Bank Negara Malaysia, via
  data.gov.my (CC BY 4.0)". That also satisfies the BNM dataset terms above.
- [Rate limit](https://developer.data.gov.my/rate-limit): 4 requests a minute on the Data
  Catalogue API, HTTP 429 beyond that. No API key. The policy table spaces requests 15 s apart.
- data.gov.my's own terms-of-use page returned 404; the dataset page is the only licence
  statement found.

## Yahoo Finance

[Yahoo Terms of Service](https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html). Yahoo
Finance is provided by Yahoo Finance LLC (section 14.2). There is no official Yahoo Finance
data API; `yfinance` reads the endpoints the Yahoo Finance website uses.

- Collecting data by automated means (robots, spiders, scrapers) needs Yahoo's express prior
  permission (2(d)(ix)). This is how `yfinance` works.
- Commercial use of any part of the services is not allowed unless expressly stated (2(e)).
- Reproducing or distributing any part of the services needs written permission (2(h)).
- Building a database or data feed that substitutes for Yahoo's services is not allowed
  (2(d)(x)).
- High-volume activity needs written consent (2(m)).
- Some content shown is owned by third-party data providers (6(a)), which for prices means the
  exchange.

The [Yahoo developer API terms](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html)
cover keyed Yahoo developer APIs, which `yfinance` does not use. They add a 24-hour deletion
rule for "Yahoo user data" (section 2.1) without saying whether market data counts.

What this means for bursakit: Yahoo-sourced prices, dividends, listings and lookups are for the
user's own personal, non-commercial use, and must not be redistributed. The nightly live test
fetches a few rows of Yahoo data from GitHub's servers; keep it small.

## Bursa Malaysia

[Terms & Conditions of Use, Disclaimer and Linking Policy](https://www.bursamalaysia.com/term_conditions_of_use_disclaimer_and_linking_policy),
no date shown.

- The website and its content may be viewed, and one copy printed, for personal and
  non-commercial use, research or information.
- Copying, storing in an electronic retrieval system, downloading, publishing or distributing
  any of the content needs Bursa's prior written consent.

No adapter reads bursamalaysia.com, and none should without that consent. This is why
`listings()` cannot fill `market` (Main / ACE / LEAP) or Bursa's own sector names: the only
source for them is Bursa, through its website or a paid data licence.
