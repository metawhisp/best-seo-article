# Article run artifact contract

Generate only applicable artifacts, but never omit an artifact required by the claimed delivery state.

```text
article-run/
├── manifest.json
├── intake.json
├── capabilities.json
├── baseline/
│   ├── original.md
│   └── snapshot.json
├── research/
│   ├── serp.json
│   ├── quality-gate.json
│   ├── query-decision.md
│   ├── intent-gap.md
│   ├── iteration-report.md
│   ├── source-plan.md
│   ├── sources.jsonl
│   └── audience-language.md
├── opportunity.md
├── brief.md
├── outline.md
├── claims.jsonl
├── drafts/
│   ├── baseline.md
│   └── final.md
├── reviews/
│   ├── verification.json
│   ├── editorial.json
│   ├── editorial.md
│   ├── ymyl.json
│   └── technical.json
├── publish/
│   ├── article.md
│   ├── metadata.json
│   ├── schema.json
│   ├── publish-manifest.json
│   └── assets/
├── media-manifest.json
├── dataset-manifest.json
├── diff-report.json
├── handoff.md
└── measurement/
    ├── baseline.json
    ├── evidence/
    │   └── <source-export>
    ├── snapshots/
    └── decisions.md
```

## Required by state

| State | Required artifacts |
|---|---|
| `draft-only` | `manifest.json`, `intake.json`, `drafts/final.md` |
| `needs-evidence` | Draft requirements plus `claims.jsonl`, `research/sources.jsonl` |
| `needs-expert-review` | Content-ready artifacts except an approved YMYL review; `reviews/ymyl.json` records the missing gate |
| `content-ready` | Draft requirements plus `capabilities.json`, `opportunity.md`, `brief.md`, `outline.md`, `research/serp.json`, `research/quality-gate.json`, `research/query-decision.md`, `research/intent-gap.md`, `research/source-plan.md`, source and claim ledgers, bound `reviews/verification.json`, bound `reviews/editorial.json`, human-readable `reviews/editorial.md` notes, and a `handoff.md` whose `Status:` exactly matches the manifest. Full work also requires `drafts/baseline.md` and the bound `research/iteration-report.md`. |
| `publish-package-ready` | Content-ready artifacts plus `publish/article.*`, metadata, schema decision, publish manifest, and technical review |
| `published-pending-verification` | Package requirements plus explicit publish permission, destination URL, and publish receipt/event |
| `verified-live` | Published requirements plus `reviews/live-verification.json` with URL, retrieval time, HTTP, rendered-content, canonical, indexability, schema, link, and asset results |
| `measured` | Verified-live requirements plus `measurement-v1` baseline and comparable post-publish snapshot records, checksummed evidence files under `measurement/evidence/`, limitations, and a decision |

`blocked` may occur at any stage. Keep the evidence that explains the blocker. A blocked run must not masquerade as a complete package.

## Manifest invariants

- `schema_version` identifies the artifact contract, currently `0.1`.
- `run_id` is stable for retries and repairs.
- `mode`, target, language, locale, site, YMYL state, permissions, and requested/actual status are explicit.
- `requested_status` is the run's maximum authorized delivery scope;
  `actual_status` cannot silently exceed it.
- `run_id`, target, and language are non-empty strings of the schema-defined minimum length. `risk.ymyl` is exactly JSON `true`, JSON `false`, or the string `"auto"`; look-alike values such as `1`, `0`, `"true"`, and `null` are invalid.
- `actual_status` is derived from passed gates; it is never copied blindly from the user's request.
- Tool availability uses `AVAILABLE`, `USER_EXPORT`, `FALLBACK`, or `UNAVAILABLE`.
- Every external mutation records actor, timestamp, destination, permission, and returned identifier.
- Warnings and waivers remain visible. P0 findings and truth, safety, rights, accessibility, or permission P1 findings cannot be waived.
- Rewrite and refresh manifests record whether protected elements were reviewed, why they were selected, and whether an intentionally empty selection was explicitly approved.
- At `content-ready` and above, writer, verifier, and editor identities are non-empty. The verification reviewer matches the verifier role; a writer/verifier identity collision may be disclosed only with `independence_degraded: true`.

## Bound review records

`reviews/verification.json`, `reviews/editorial.json`, `reviews/ymyl.json`, and
`reviews/technical.json` use `contract_version: "review-binding-v1"`. A passed
or approved record contains the current article `run_id`, its exact
`review_type`, the applicable reviewer identity and timezone-aware
`reviewed_at`, plus lowercase SHA-256 values in `artifact_hashes`.

The exact required bindings are:

| Review | Required current artifact hashes |
|---|---|
| Verification | `intake.json`, `drafts/final.md`, `claims.jsonl`, `research/sources.jsonl`, `research/quality-gate.json` |
| Editorial | `intake.json`, `drafts/final.md`, `claims.jsonl`, `research/sources.jsonl`, `research/quality-gate.json` |
| Pending YMYL request | The same intake plus four content artifacts, with `requested_at` |
| Approved YMYL at `content-ready` | The same intake plus four content artifacts |
| Approved YMYL at `publish-package-ready` or above | The intake and four content artifacts plus `publish/publish-manifest.json` |
| Technical | The intake and four content artifacts plus `publish/publish-manifest.json` |

The hash map must contain exactly the paths required for that review stage.
If any bound byte changes, regenerate downstream package checksums and obtain a
new applicable review; copying the old digest forward is not approval.
`reviews/editorial.md` stores readable findings and repair notes, while
`reviews/editorial.json` is the bound verdict consumed by the validator.

The quality gate separately binds the baseline and iteration report by their
literal paths and SHA-256 values. This makes the baseline-to-final comparison
reviewable without redefining an editorial approval as a second reviewer.

Every machine-gating review includes a `findings` array. Each finding has a
valid `severity` (`P0`-`P3`), substantive `message`, and `resolution` equal to
`open` or `resolved`. In a `passed` or `approved` verdict, every P0/P1 finding
must be `resolved`; `accepted`, `waived`, risk-accepted prose, or omission does
not create a clean verdict. P0 is never waivable. Open P2/P3 limitations may
remain, but they stay visible in the handoff.

SHA-256 here demonstrates that a recorded verdict refers to particular bytes.
It is not a digital signature and does not prove who reviewed the files,
whether a source entails a claim, whether prose is useful, or whether rights
and credentials are genuine. Those remain independent review responsibilities.

Review and release timestamps form one lifecycle. Run creation precedes
verification, editorial review, and applicable YMYL work; verification precedes
editorial review; editorial review precedes package creation; package creation
precedes package-level YMYL and technical approval; technical approval precedes
publication; publication precedes live verification; post-publication snapshots
follow both publication and live verification. A measurement baseline does not
postdate publication. Every completed event is non-future and no later than
`manifest.updated_at`.

## Intake invariants

- `intake.json` conforms to `schemas/intake.schema.json` from the initial `draft-only` scaffold onward.
- Its `schema_version`, `run_id`, `mode`, `target`, `language`, `locale`, `site`, and closed `destination` object are always present and exactly match `manifest.json`; the intake cannot be reused across runs or destinations by changing only its filename.
- `locale` and `site` may remain JSON `null` when they are genuinely unknown or inapplicable. Other optional prose fields may be JSON `null` or substantive strings, never blank or format/control-only placeholders.
- `approved_product_facts`, `constraints`, and `inferences_requiring_confirmation` are arrays of unique substantive strings. An empty array means no recorded item; it does not mean an unknown fact was approved.
- `schema_version` currently equals `0.1`. Migrate the artifact deliberately when this contract changes rather than silently accepting a mismatched version.

## Ledgers

Use one JSON object per line. IDs match `^[A-Za-z0-9._-]+$`, are unique, and remain stable across repair passes. ID arrays contain only matching strings; claim `source_ids` and source `supported_claim_ids` contain no duplicates. Do not silently replace a source or claim; update its resolution and retain the prior review artifact.

The source ledger records publisher, author when known, URL, dates, retrieval time, source class, locale/jurisdiction, access state, supported claim IDs, conflicts, and volatility.

The claim ledger records exact wording, article location, classification, source IDs, support status, verifier, freshness, and resolution. `load-bearing` means the reader's conclusion or decision materially depends on the claim.

At `content-ready` and above, both ledgers must contain at least one valid record. Human evidence text must contain at least one Unicode letter or number. Whitespace-only, format/control-only, combining-only, punctuation-only, emoji-only, and other symbol-only strings are invalid, including values padded with zero-width characters. Technical IDs, paths, MIME types, and units retain their field-specific contracts instead of this prose rule. Every material claim needs an allowed claim type, substantive exact supporting passage or data locator, a substantive verifier identity, current access state, and resolvable source IDs. Its exact claim wording must also occur in the current reader-visible draft; comments, fenced code, inline code, reference definitions, front matter, and hidden HTML do not count as published claim text. Media that carries evidence must share the article `run_id` and link its `claim_ids` to this ledger.

## Publish package

`publish/schema.json` may record `{"applicable": false, "reason": "..."}` when no structured data is appropriate. Do not generate irrelevant schema merely to satisfy file presence.

`publish/metadata.json` distinguishes recommendations from applied destination values. `publish-manifest.json` lists every allowed deliverable with a checksum when the package is handed to another system: the article, metadata, schema decision, present adjacent media/dataset manifests, and media outputs declared under `media/` or `publish/assets/`. A research export, review, source snapshot, script, or arbitrary extra publish file does not become a deliverable merely by being checksummed.

`publish-package-ready` has two explicit scopes:

- A portable package is allowed only when Markdown, MDX, or HTML is itself the requested delivery format. Record a CMS-neutral destination scope, keep unknown canonical/byline fields null, and disclose that rendering and live-site checks remain pending.
- A destination-specific package names its URL or CMS and must match that destination's canonical, format, and renderer checks. A generic Markdown file cannot masquerade as a CMS-validated package.

The validator recomputes SHA-256 for every listed file, requires every applicable allowlisted deliverable, rejects undeclared files in the publish tree, confirms that the packaged article is the reviewed final draft, and requires an applicable schema headline to exactly match the sole reader-visible H1.

Run artifacts and package files must be regular files inside the run boundary. Symlinked manifests, ledgers, articles, media directories, and checksummed package files fail closed so validation never imports hidden content from another path. Relative artifact paths use exact canonical POSIX spelling, not a spelling that only becomes valid after stripping a slash, collapsing dot or empty segments, interpreting a platform backslash, or applying URL decoding. Optional `publish/article.*` and `publish/publish-manifest.json` paths are also inspected when present, even before package-ready status; making an optional path a symlink cannot bypass validation.

Media release validation applies the same boundary to every referenced file.
Local source and rights evidence must be non-empty regular files, traverse no
symlink component, and carry a matching SHA-256 in the media or dataset
manifest. A manual rights approval is a structured reviewer, timezone-aware
review time, substantive evidence, and explicit review scopes; a bare
`approved` token is not a release. AI media uses one provenance-and-rights
record per input/reference asset (or an explicit empty input list), never a
single aggregate boolean. Long descriptions, accessible chart tables, captions,
transcripts, and visual descriptions are checksum-bound and content-inspected
when the run is validated; mere path existence does not satisfy accessibility.

The technical review names and evidences the core H1, metadata, schema-decision,
link, and asset checks. H1, metadata, and links must be observed as `passed`;
schema and assets may be `not-applicable` only with real scope evidence.
Arbitrary check names, bare outcome tokens, and evidence that says an observation
did not occur do not satisfy those gates.

## Measurement records

`measurement/baseline.json` and every JSON record in
`measurement/snapshots/` use `contract_version: "measurement-v1"` and bind to
the same `run_id`, page, and article mode. Each record contains:

- the current `package_manifest_sha256`; a snapshot additionally contains
  `live_verification_sha256` for the exact live record it follows;
- a timezone-aware `measured_at`;
- a half-open `comparison_window` with `start`, `end_exclusive`, valid IANA
  `timezone`, and `grain`;
- one or more `source_evidence` records naming `gsc` or `ga4`, the selected
  provider, extraction time, in-run path under `measurement/evidence/`, and
  matching SHA-256;
- one or more finite numeric metrics, each with `unit`, `aggregation`,
  `source_system`, `evidence_id`, `entity`, `channel`, `domain`, `filters`, and
  `segments`;
- explicit `data_limitations`, which may be an empty array only when none are
  known.

Evidence files are regular, non-empty, non-symlink files inside the run. Their
recorded paths use the same literal canonical POSIX spelling. Their
provider must still be backed by a current `AVAILABLE` or `USER_EXPORT` GSC/GA4
capability. A previously observed `USER_EXPORT` that has been moved, emptied,
or replaced by a symlink is stale and cannot support `measured`.

Baseline and post-publication windows have equal duration, timezone, and grain.
The baseline window ends no later than the publication day; a snapshot window
starts after that day. At least one metric ID must retain the exact provider,
unit, aggregation, entity, channel, domain, filters, and segments across both
records and bind to the exact article page URL. A page metric has exactly
`entity` and `value` in `domain`, requires a matching canonical `filters.page`,
and uses only the schema's closed page filter/segment keys; URL aliases cannot
carry a second page identity. Broader site or cluster metrics
are supplemental, not sufficient by themselves.
Equal names with different semantics are not comparable. These checks support
measurement integrity, not causal attribution.

A successful `publish/publish-receipt.json` records `status: published`, destination `url`, timezone-aware `published_at`, the publishing `actor`, `permission_confirmed: true`, and `package_manifest_sha256`. `reviews/live-verification.json` separately records the matching URL, `checked_at`, the same package hash, `publish_receipt_sha256`, and structured status-plus-evidence observations for HTTP, rendered content, canonical, indexability, schema, links, and assets. A present receipt or live record is still validated even if someone later lowers `manifest.actual_status`; status downgrade cannot erase evidence of an external mutation. Bare success tokens or prose saying a check was unavailable do not demonstrate a live check. URL hostnames use canonical ASCII DNS or IPv4. Raw Unicode, ambiguous numeric aliases, root-dot spellings, port `0`, and IPv6 literals fail closed. Runtime accepts an A-label only after free optional `idna` validation; portable schemas conservatively reject A-labels.
