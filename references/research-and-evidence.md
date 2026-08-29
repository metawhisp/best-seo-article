# Research and Evidence

Research exists to understand the user job and support the article's claims. Search rankings, competitor repetition, and model confidence are not evidence of truth.

## Research packet

Record enough context to reproduce important findings:

- Query or user question, language, locale, device context when relevant, and retrieval time.
- Observed result types, recurring intent patterns, useful omissions, and competing interpretations.
- Existing site coverage, internal-link candidates, and potential cannibalization when available.
- Audience vocabulary and real questions without treating community posts as authoritative evidence.
- Official, primary, first-party, and reputable secondary sources relevant to planned claims.
- Conflicts, source limitations, access failures, and information likely to change.

Use search results and competitor pages for intent and coverage analysis. Follow facts to the best available direct source rather than citing a search snippet or copying the ranking page's wording.

## Source ledger

Maintain one record per source:

```yaml
source_id:
title:
locator:
publisher:
author:
published_at:
updated_at:
retrieved_at:
source_type: official | primary | first-party | user-provided | secondary | competitor
acquisition: agent-web | user-provided
locale:
jurisdiction:
access_status: accessible | partial | archived | unavailable
supported_claim_ids: []
known_conflicts: []
snapshot:
notes:
```

Source authority is claim-specific. An official product page may be authoritative for its current specifications but not for an independent performance comparison. A recent secondary source may summarize a topic well but should not replace an accessible primary study for a load-bearing scientific claim.

Observed provenance and review times must be timezone-aware and cannot be materially future-dated. A planned retrieval, scheduled review, or future `as_of` date is not evidence. `acquisition` records how bytes entered the run, independently of source authority: an official document supplied by the user remains `source_type: official` with `acquisition: user-provided`. Agent browser/search retrieval requires `permissions.web_research=true`; never relabel it after the fact.

Do not apply a universal source-age limit. Match source freshness to volatility and the article's `as_of` date. The current-intent SERP artifact is a separate operational exception: content-ready status requires it to be no more than 31 days old, and volatile queries should be refreshed sooner.

Ledger IDs use only ASCII letters, digits, `.`, `_`, and `-`. `supported_claim_ids` is an array of unique claim-ID strings; nulls, numbers, objects, and duplicate entries are invalid. Keep an empty array when a captured source was reviewed but supports no retained claim.
Every evidence edge is reciprocal: each ID in `claim.source_ids` must name a source whose `supported_claim_ids` contains that claim, and each ID in `source.supported_claim_ids` must name a claim whose `source_ids` contains that source. Missing, unknown, or one-sided links block readiness.

## Claim ledger

Maintain one record for each material factual claim and recommendation premise:

```yaml
claim_id:
text:
location:
classification: load-bearing | supporting | opinion | inference
claim_type: factual | numeric | quote | experience | opinion | inference
source_ids: []
support_status: verified | qualified | partial | contradicted | unsupported | pending | not-applicable
freshness_status: current | stale | unknown | not-applicable
exact_support:
verifier:
resolution:
as_of:
```

Definitions:

- `load-bearing`: changing or removing the claim would change the article's answer, recommendation, comparison, safety, or conclusion.
- `supporting`: useful factual context that does not determine the main conclusion.
- `opinion`: a clearly attributed judgment, not presented as consensus fact.
- `inference`: a reasoned conclusion from named evidence; label it as an inference and preserve uncertainty.

`claim_type` and `classification` are a locked pair, not interchangeable labels. `factual`, `numeric`, `quote`, and `experience` types must be `load-bearing` or `supporting` and pass material-evidence gates. An `opinion` type must use the `opinion` classification; an `inference` type must use the `inference` classification. Re-labeling a factual claim as opinion or inference never removes its evidence obligation.

Represent a first-party claim through its factual classification and a `first-party` source record. It still requires traceable authorized evidence.

`source_ids` is an array of unique source-ID strings. Source `title`, `locator`, `publisher`, supplied `author`, `notes`, and conflict notes, plus claim `text`, `location`, `resolution`, `exact_support`, and `verifier`, must contain at least one Unicode letter or number. Whitespace, control characters, U+200B zero-width space, combining marks without a visible base, punctuation-only values, emoji-only values, and other symbol-only values do not satisfy the contract. Truthy objects, arrays, numbers, and booleans never satisfy text fields either. Ledger IDs remain governed by the ASCII identifier rule above.

## Evidence rules

- Every load-bearing claim must be supported by evidence that entails the wording used.
- A live URL, citation count, publisher reputation, or matching keyword does not prove entailment.
- Numbers, quotes, dates, named studies, legal requirements, product behavior, and comparative claims require direct verification.
- First-party results need provenance, measurement context, and permission to disclose.
- Do not invent personal use, interviews, tests, customers, credentials, or outcomes.
- Represent material disagreement and explain why one source is weighted more heavily.
- Remove, narrow, or qualify unsupported claims. Do not preserve them for rhetorical flow.
- Use only short necessary quotations; prefer original synthesis and avoid close paraphrasing.
- Do not cite a competitor merely because its page ranks. Cite it only when it is itself the appropriate source for the fact.

## Evidence workflow

1. Define the user question, likely answer types, and volatile claim categories.
2. Capture a dated search-intent snapshot where current search access exists, mark it `agent-web` or `user-provided`, and respect the recorded web-research permission.
3. Create the initial source ledger before drafting conclusions.
4. Build the brief and outline from observed user needs and supported evidence.
5. Create planned claim records for assertions that will carry the answer.
6. Draft from the approved research packet; add new claims to the ledger as they appear.
7. Have an independent verifier inspect the article, claim ledger, and actual sources.
8. Resolve unsupported, partial, stale, or contradictory claims before editorial approval.

The verifier must not rely on the writer's confidence or a target score. It should record the exact source location or reasoning that supports each decision.

Run `scripts/validate_claims.py RUN_DIR` even when the full run validator is not available. The claims validator independently checks `run_id`, `target`, `language`, and `risk.ymyl`; only JSON `true`, JSON `false`, and the exact string `"auto"` are valid YMYL states.

## Missing or conflicting evidence

| Condition | Required response |
|---|---|
| Current search evidence unavailable | State the research date and limitation; do not claim current SERP alignment. |
| Direct source unavailable | Find a reliable independent copy or narrow/remove the claim; do not cite only the snippet. |
| Sources materially disagree | Present the disagreement or narrow the conclusion; do not select silently. |
| First-party claim lacks documentation | Mark unsupported and request evidence or remove it. |
| Claim is inherently subjective | State the evaluation criteria and attribution. |
| Claim is time-sensitive | Include the relevant date and assign a refresh trigger. |

Research limitations affect readiness. A source-limited draft may be useful, but it cannot become `publish-package-ready` until its load-bearing claims and current-intent assumptions pass the applicable gates.
