# Provider and capability layer (v0.1)

This layer keeps article methodology independent from any vendor. The skill must
work in a zero-paid-dependency mode, while optional providers can improve the
evidence. A provider may enrich the result; it must never license the model to
invent rankings, traffic, keyword volume, citations, media, or publication state.

Official product and price pages in this document were checked on 2026-08-29.
Prices are documentation, not executable defaults: never hardcode them into an
adapter, and re-check the official page before approving spend.

## Non-negotiable runtime contract

- `scripts/capability_preflight.py` is offline and Python-standard-library only.
- It probes only an explicitly supplied `--available` flag, environment variable
  name, or file path. It does not scan the shell, `$PATH`, `.env`, keychains,
  browsers, repositories, or home directories.
- It never prints an environment value. JSON contains only the variable name and
  an aggregate present/not-present result.
- It makes no network request, authenticates nowhere, and never calls a paid API.
- `paid` and `unknown` cost candidates require a per-run
  `--approve-cost CAPABILITY`. A stored API key is not cost approval.
- Per-capability approval and the run boundary must agree: any approved
  `paid`/`unknown` candidate also requires `manifest.permissions.paid_tools=true`.
  A capability report cannot grant permission that the manifest withholds.
- An existing `--file` is canonicalized to the absolute path observed at
  preflight, is rechecked for readability and non-empty regular-file status,
  and never triggers provider spend.
- CMS mutations are outside preflight. A future CMS adapter must default to draft
  or dry-run, require explicit publish authorization, and verify the live URL
  after publication.

## Capability states

| State | Meaning | Permitted claim |
|---|---|---|
| `AVAILABLE` | An explicit local flag or all explicitly named environment variables are present; any possible cost was approved | The named adapter is eligible to run, not that a network request has succeeded |
| `USER_EXPORT` | Every explicitly named readable, non-empty, non-symlink regular file exists at its recorded canonical absolute path | A user export is present, not that its schema, freshness, or ownership has been validated |
| `FALLBACK` | A configured or built-in no-network method is selected | Only the reduced-fidelity work named by the fallback |
| `UNAVAILABLE` | No usable candidate and no fallback | The downstream workflow must retain the capability-specific pending/blocking state |

Selection order is deterministic:

1. A readable `--file` becomes `USER_EXPORT`.
2. A present `--available` or `--env` probe becomes `AVAILABLE` only when its
   cost is `free`, or `paid`/`unknown` plus explicit approval.
3. Otherwise a configured fallback, then the built-in fallback, becomes
   `FALLBACK`.
4. Without any of those, the state is `UNAVAILABLE`.

Built-in fallback labels and every capability's absence-effect text are fixed by
the v0.1 contract; they cannot be replaced with a weaker disclosure. The JSON
Schema checks local shape and status constraints. `validate_run.py` additionally
recomputes cross-field counts, reference uniqueness, provider selection,
cost/state consistency, limitations, and the complete summary because JSON
Schema cannot express all of those equalities.

The report is run-bound, not permanent configuration: `checked_at` must not
predate `manifest.created_at`, must not postdate `manifest.updated_at`, and must
be no more than 31 days old at validation time. Re-run preflight sooner whenever
credentials, exports, provider availability, or the requested scope changes.

Multiple environment variables or files can be declared for one capability;
all are required. Mixing probe kinds for the same capability is rejected as
ambiguous.

## CLI examples

Free/offline baseline:

```bash
python3 <skill-root>/scripts/capability_preflight.py --pretty
```

Paid SERP candidate with per-run approval, an existing GSC export, and an
explicit local crawler:

```bash
python3 <skill-root>/scripts/capability_preflight.py \
  --provider serp=serpapi \
  --env serp=SERPAPI_API_KEY \
  --cost serp=paid \
  --approve-cost serp \
  --provider gsc=gsc-csv \
  --file gsc=exports/gsc.csv \
  --provider crawl=local-bounded-crawler \
  --available crawl=local-bounded-crawler \
  --cost crawl=free \
  --pretty
```

Provider requiring two credentials; only their names appear in output:

```bash
python3 <skill-root>/scripts/capability_preflight.py \
  --provider serp=dataforseo \
  --env serp=DATAFORSEO_LOGIN \
  --env serp=DATAFORSEO_PASSWORD \
  --cost serp=paid \
  --approve-cost serp
```

Unknown cost fails closed. If the named credential exists but `--cost` is
omitted, the candidate needs `--approve-cost`; otherwise the report selects a
fallback or reports `UNAVAILABLE`.

The JSON contract is `schemas/capabilities.schema.json`. Fixtures are in
`evals/fixtures/`. Reports use artifact `schema_version: "0.1"`, include a UTC
`checked_at`, and copy every fallback/unavailable consequence into the top-level
`limitations` array. `--checked-at` exists only to make fixtures and controlled
replays deterministic; normal runs use the current UTC time.

## Capability matrix

| Capability | Zero-paid fallback | Optional providers | Authentication / requirement | If absent |
|---|---|---|---|---|
| SERP | Manual browser capture with query, locale, device, date, and supplied screenshot/export | [SerpApi pricing](https://serpapi.com/pricing): free 250 searches/month; Starter $25/1,000; Developer $75/5,000. [DataForSEO SERP](https://dataforseo.com/apis/serp-api): Standard from $0.60/1,000 result pages; Live from $2/1,000; see [general pricing](https://dataforseo.com/pricing) | SerpApi private `api_key`, [Search API](https://serpapi.com/search-api). DataForSEO API login/password via [Basic Auth](https://docs.dataforseo.com/v3/auth/) | Limit claims to the dated, observed query, locale, device, and opened results; do not imply exhaustive or repeatable rank tracking |
| Keywords | First-party product language, GSC/user exports, Google Keyword Planner UI/CSV, and manually captured SERP headings; Trends is directional, not volume | Google Ads [Keyword Planning API](https://developers.google.com/google-ads/api/docs/keyword-planning/overview). [Ahrefs pricing](https://ahrefs.com/pricing): Starter $29, Lite $129, Standard $249, Advanced $449/month; [API v3](https://docs.ahrefs.com/en/api/docs/introduction). [DataForSEO Labs](https://dataforseo.com/apis/dataforseo-labs-api), method-dependent pay-as-you-go pricing | Google Ads manager account, OAuth 2.0, and [developer token](https://developers.google.com/google-ads/api/docs/api-policy/developer-token); Keyword Planner setup requirements are in [Google Ads Help](https://support.google.com/google-ads/answer/3022575). Ahrefs API key and eligible plan. DataForSEO Basic Auth | Leave volume, CPC, and keyword difficulty `NOT_AVAILABLE`; never estimate them from prose |
| GSC | User-provided Search Console CSV | The official Search Console API is [free subject to limits](https://developers.google.com/webmaster-tools/pricing) | OAuth 2.0 with `webmasters.readonly`; [authorization](https://developers.google.com/webmaster-tools/v1/how-tos/authorizing), [quotas](https://developers.google.com/webmaster-tools/limits), and [data caveats](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data) | No existing-query/cannibalization baseline or Google outcome measurement; retain `GSC_UNAVAILABLE`/pending |
| GA4 | User-provided CSV or Explore export | Standard GA4 is advertised [free of charge](https://marketingplatform.google.com/about/analytics/); use the [GA4 Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) | User OAuth or service account with `analytics.readonly`; [quickstart](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart) and [quotas](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1alpha/PropertyQuota) | Do not claim engagement or conversion lift; retain `PENDING_GA4` |
| Crawl / internal links | Bounded same-origin review of target URLs, sitemap, robots, status, canonical, headings, and links; follow Google's [robots.txt specification](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec) | [Screaming Frog pricing](https://www.screamingfrog.co.uk/seo-spider/pricing/): free to 500 URLs, paid £199/year; [CLI/headless guide](https://www.screamingfrog.co.uk/seo-spider/user-guide/general/). Ahrefs Site Audit when already licensed | Local application/license; a bounded local HTTP implementation needs no third-party API key | Report inspected URL count, depth, and rendered/non-rendered coverage; do not infer whole-site orphan or cannibalization findings from a partial crawl |
| CWV | Manual performance checklist; local [Lighthouse](https://developer.chrome.com/docs/lighthouse/overview) when explicitly available | [CrUX API](https://developer.chrome.com/docs/crux/api) is free and quota-limited; [PageSpeed Insights API](https://developers.google.com/speed/docs/insights/v5/get-started) can work without a key, though a key is recommended for automation | Lighthouse local, no key. CrUX Google Cloud API key. PSI optional API key | Use `CWV_NOT_MEASURED`; simple response time must not be labelled Core Web Vitals |
| Fact-check | Claim ledger plus manual primary-source verification. [Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/) public access; [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/) free within published rate limits | [Google Fact Check Tools API](https://developers.google.com/fact-check/tools/api/reference/rest/) searches existing ClaimReview records. [Tavily pricing](https://www.tavily.com/pricing): 1,000 credits/month free, pay-as-you-go $0.008/credit. [Brave Search API plans](https://api-dashboard.search.brave.com/app/plans): $5/1,000 requests with $5 monthly credit | Crossref public, polite `mailto`/User-Agent recommended. NCBI API key raises rate limit. Google Cloud, Tavily, or Brave API key/token for their services | Fact-checking remains mandatory: remove, qualify, or tag unsupported material claims; unresolved YMYL claims block editorial readiness |
| Images | User/brand-owned assets, owned screenshots, SVG diagrams, or an image brief with alt/caption/provenance fields | [Unsplash API](https://unsplash.com/documentation): demo 50 requests/hour and production 1,000/hour after approval. [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation) is usage-priced by model, size, quality, and input | Unsplash access key plus [license](https://unsplash.com/license), [API attribution](https://help.unsplash.com/en/articles/2511315-guideline-attribution), and [API terms](https://unsplash.com/api-terms). OpenAI bearer key; organization verification may be required | Return briefs and provenance requirements only; never invent a generated file, stock license, or URL |
| Charts | Sourced Markdown/HTML table or locally authored SVG specification | [Plotly](https://plotly.com/python/) and [Vega-Lite](https://vega.github.io/vega-lite/) are open-source local options. [Datawrapper pricing](https://www.datawrapper.de/pricing): free publishing with attribution; Pro $21/user/month; Business $39/user/month | Local Plotly/Vega needs no service credential. Datawrapper automation uses an account/API token | Do not draw a chart without source data; emit a table/spec with source, date, units, and method |
| CMS | CMS-neutral Markdown, sanitized HTML, metadata/JSON-LD, media/link manifests, and publish checklist | WordPress REST, [Ghost(Pro) pricing](https://ghost.org/pricing), or [Webflow pricing](https://webflow.com/pricing) | WordPress [`POST /wp/v2/posts`](https://developer.wordpress.org/rest-api/reference/posts/) and [Application Password/cookie auth](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/). Ghost Admin API key to short-lived JWT via [Admin API](https://docs.ghost.org/admin-api). Webflow site/workspace token or OAuth via [authentication docs](https://developers.webflow.com/data/reference/authentication) and [CMS API](https://developers.webflow.com/data/docs/working-with-the-cms) | Deliver an explicitly agreed portable package or stop at `content-ready`; never imply destination rendering or publication |

## Adapter boundary for later versions

Preflight does not implement provider clients. A future adapter must accept a
capability report plus task-specific inputs and return an evidence envelope:

```json
{
  "capability": "serp",
  "provider": "serpapi",
  "query_or_url": "example query",
  "locale": "en-US",
  "device": "desktop",
  "observed_at": "2026-08-29T12:00:00Z",
  "provenance": "measured",
  "records": [],
  "warnings": []
}
```

Required provenance values are `measured`, `user-provided`, or `estimated`.
`estimated` must never be silently promoted to measured data. The adapter must
also preserve provider/source, query or URL, locale/device where relevant,
observation time, input freshness, and truncation/quota warnings.

For CMS, the adapter contract has two explicit mutations: `create_draft` and
`publish`. `publish` is never implied by article generation, a stored token, or
preflight status. Success requires a post-mutation read of the public URL and
verification of HTTP status, canonical, robots directives, schema, links, and
media.
