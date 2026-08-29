# Post-Publication Measurement

Measurement determines whether the page achieved its declared user and business goals. It does not retroactively prove that a claim was true or that the article caused every observed change.

## Define success before publication

Record the primary user job, business outcome, target page and query set, locale, comparison period, known confounders, and decision the measurement should support.

Use the smallest set of metrics that answers that decision:

| Dimension | Examples |
|---|---|
| Live integrity | HTTP status, rendered content, canonical, structured data, assets, indexability |
| Search visibility | Impressions, query discovery, query distribution, country/device mix, search features |
| Search acquisition | Clicks and CTR interpreted with position, query, device, and brand context |
| On-page usefulness | Engaged sessions, task completion, meaningful scroll or interaction when instrumented |
| Business outcome | Approved CTA, signup, lead, qualified visit, sale, or assisted conversion |
| Maintenance | Broken sources, stale claims, product changes, intent shifts, cannibalization |

Do not use average position, traffic, a generic content score, or AI visibility as a standalone success verdict.

## `measurement-v1` baseline and snapshots

Capture the best available pre-change evidence before publication or update.
Both `measurement/baseline.json` and each
`measurement/snapshots/<date>.json` use this closed contract:

```json
{
  "contract_version": "measurement-v1",
  "run_id": "<article run id>",
  "record_type": "baseline",
  "page": "https://example.com/article",
  "mode": "rewrite",
  "package_manifest_sha256": "<SHA-256 of publish/publish-manifest.json>",
  "measured_at": "<timezone-aware extraction record time>",
  "comparison_window": {
    "start": "2026-07-01",
    "end_exclusive": "2026-07-29",
    "timezone": "Europe/Belgrade",
    "grain": "day"
  },
  "source_evidence": [
    {
      "evidence_id": "gsc-baseline-export",
      "source_system": "gsc",
      "provider": "<selected capability provider>",
      "path": "measurement/evidence/gsc-baseline.csv",
      "sha256": "<lowercase SHA-256>",
      "extracted_at": "<timezone-aware timestamp>"
    }
  ],
  "metrics": {
    "clicks": {
      "value": 120,
      "unit": "count",
      "aggregation": "sum",
      "source_system": "gsc",
      "evidence_id": "gsc-baseline-export",
      "entity": "page",
      "channel": "organic-search",
      "domain": {
        "entity": "page",
        "value": "https://example.com/article"
      },
      "filters": {"page": "https://example.com/article"},
      "segments": {"country": "all", "device": "all"}
    }
  },
  "data_limitations": ["Search Console data may be delayed and aggregated."]
}
```

Every baseline binds `package_manifest_sha256` to the exact package whose
pre-publication evidence it describes. A snapshot carries the same field plus
`live_verification_sha256`, binding it to the exact live observation record.
Neither field is copied as decoration: both hashes are recomputed against the
current run. A package or live-record change invalidates the dependent
measurement record.

`comparison_window` is half-open: `start` is included and `end_exclusive` is
not. This removes overlap ambiguity at the boundary. Baseline and snapshot use
equal durations, the same valid IANA timezone, and the same grain. The baseline
window ends no later than the local publication day; the post window starts
after that day. The baseline itself cannot postdate publication, and a snapshot
is later than the baseline, publication, and live verification. Extraction and
measurement times are timezone-aware, non-future, and ordered within the run.

Every source is materialized as a regular, non-empty, non-symlink file under
`measurement/evidence/` and is bound by SHA-256. `source_system` is `gsc` or
`ga4`; its `provider` must exactly match the currently selected provider in an
`AVAILABLE` or `USER_EXPORT` capability. Preflight discovery is not permanent:
a `USER_EXPORT` is recorded with the canonical absolute path observed during
preflight and checked again during run validation. If it is unreadable,
deleted, emptied, moved, rebound through a relative path, or replaced by a
symlink, measurement fails until a current export is supplied and the record
is rebuilt.

Every metric value is a finite number, never a boolean, NaN, or infinity.
Counts are non-negative integers; percentages are from 0 to 100 and ratios from
0 to 1. Metric IDs and machine descriptor tokens use canonical lowercase
`[a-z][a-z0-9:_-]*` spelling, so `count` and `COUNT` cannot bypass value rules
or become ambiguous aliases. Baseline and snapshot need at least one shared metric ID whose provider,
unit, aggregation, entity, channel, domain, filters, and segments match exactly. A
metric named `clicks` is not comparable if one record is filtered differently,
uses another provider, or changes from a sum to an average. Each metric's
`evidence_id` must resolve to source evidence from the same source system.
At least one exactly comparable metric must be page-scoped: `entity` and
`domain.entity` are `page`; `domain` contains only `entity` and `value`;
`domain.value` matches the record and destination URL by parsed URL components;
and the required canonical `filters.page` matches it too. Page metric filters
and segments are closed, flat maps: use only the documented GSC/GA4 dimension
keys from the schema, with finite scalar values. Do not add aliases such as
`landing_page`, `page_url`, `page_path`, or `url`; normalize the page dimension
to `filters.page`. Arbitrary trailing slash sequences are not collapsed. Site
or cluster metrics may be supplemental, but cannot by themselves earn
`measured`. Measurement and evidence extraction timestamps cannot predate the
run.

Use canonical ASCII DNS or IPv4 hosts. Raw Unicode, numeric host aliases,
root-dot spellings, port `0`, and IPv6 literals fail closed. A punycode A-label
is accepted by runtime only after the free optional `idna` package validates an
IDNA2008/UTS-46 round trip; otherwise it fails closed. Portable JSON Schemas
reject A-labels because regex validation cannot establish their browser identity.

For a new page, record relevant site, cluster, and query baselines rather than inventing page history. For rewrite or refresh, preserve the original page's query, traffic, conversion, and link context when access exists.

## Measurement phases

Use evidence availability rather than a fixed calendar quota.

1. **Live verification:** confirm that the authorized publication matches the approved artifact and that critical technical elements work.
2. **Post-crawl check:** confirm discovery, indexability, canonical selection, and initial query appearance after the site has had a reasonable opportunity to be crawled.
3. **Visibility review:** wait for enough impressions to interpret query and CTR patterns without overreacting to sparse data.
4. **Outcome review:** wait for enough relevant sessions or conversions to evaluate the declared business goal.
5. **Maintenance review:** monitor material source changes, broken links, product changes, query-intent shifts, and cannibalization.

Suggested dates may be included for project planning, but crawl frequency, traffic, seasonality, and decision cost determine when evidence is sufficient.

## Interpretation guardrails

- Search and analytics data may lag, sample, aggregate, or change retrospectively.
- Before-and-after movement alone does not establish causality.
- Account for seasonality, algorithm changes, migrations, sitewide releases, promotions, brand demand, and tracking changes.
- Segment by query intent, country, device, and branded versus non-branded demand when relevant.
- Do not optimize from a small number of impressions or isolated rank checks.
- Prefer one major testable content change at a time when practical and preserve a change log.
- AI citation checks are noisy and prompt-dependent. Treat them as exploratory observations unless the project has a reproducible protocol.
- A ranking gain does not excuse factual, safety, copyright, or accessibility defects.

## Decision patterns

| Observation | Investigate before changing content |
|---|---|
| Page is not indexed | Crawl access, indexability, canonical selection, rendering, duplication, and site quality |
| Impressions appear but clicks do not | Query intent, position distribution, snippet promise, title clarity, device, and brand context |
| Clicks rise but useful engagement falls | Mismatch between search promise and page answer, UX, performance, or audience quality |
| Engagement is healthy but conversion is weak | User stage, CTA, offer, trust, attribution, and whether conversion was the right goal |
| Rewrite or refresh loses visibility | Semantic diff, removed sections, changed intent, internal links, technical regression, and external changes |
| Multiple pages gain the same queries | Cannibalization, distinct user jobs, consolidation, and internal-link signals |
| Performance is unchanged | Whether the sample is sufficient and whether the change addressed the actual constraint |

Do not automatically rewrite, redirect, unpublish, or roll back from measurement alone. Present the evidence, competing explanations, expected risk, and recommended next test for user approval.

## Measurement artifacts and status

Store checksummed evidence, immutable dated records, and a decision log:

```text
measurement/
├── baseline.json
├── evidence/
│   ├── gsc-baseline.csv
│   └── gsc-snapshot.csv
├── snapshots/
│   └── <date>.json
└── decisions.md
```

Each snapshot records source evidence, extraction time, exact metric
descriptors, comparison window, and missing data. `verified-live` requires live
technical checks; `measured` additionally requires at least one comparable
outcome snapshot. Missing analytics is a disclosed limitation, not fabricated
evidence and not automatically a content failure.

`measurement/decisions.md` must state a substantive evidence-led decision and its limitations. If comparable metrics are unavailable, keep the run at `verified-live` and provide a measurement plan instead of promoting it to `measured`.

The local validators can verify structure, checksums, capability freshness,
descriptor equality, and chronology. They cannot prove that the provider's data
is complete, that tracking is correct, that a sample is decision-sufficient, or
that the article caused the observed change. Those remain analytical judgments.
