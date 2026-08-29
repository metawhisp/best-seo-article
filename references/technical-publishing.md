# Technical publishing and live verification

Read this reference when producing a destination package, creating a CMS draft, publishing, or checking a live URL.

## Package checks

- Build the actual destination format: Markdown, MDX, HTML, or the documented CMS fields.
- State whether the package is portable or destination-specific. Portable Markdown/MDX/HTML may be package-ready only when it is the agreed deliverable; it does not prove CMS rendering, canonical application, or live behavior.
- Preserve a single reader-visible H1 and a semantic heading hierarchy. When article schema is applicable, its `headline` must exactly equal that sole visible H1 after normalization; a phrase occurring elsewhere in the body is not correspondence.
- Keep title, description, CTA, author, dates, and structured data truthful and consistent with visible content.
- Treat title and meta-description lengths as preview concerns, not universal pass/fail character limits.
- Use a stable, approved URL. A rewrite or refresh does not change it without explicit permission and a redirect plan.
- Use a canonical ASCII DNS or IPv4 host. Raw Unicode, ambiguous numeric-host spellings, root-dot variants, port `0`, and IPv6 literals fail closed. Validated A-label support is optional and uses the free `idna` package; the portable schemas conservatively reject A-labels.
- Canonical must resolve to the intended indexable URL. Do not emit contradictory robots, canonical, hreflang, or sitemap signals.
- Add structured data only when applicable and visible. Validate syntax and destination behavior; never promise a rich result.
- Resolve all required internal links and assets. Temporary external-network failures may be warnings, but empty, unsafe, malformed, or required broken links are blocking.
- Resolve inline, full-reference, collapsed-reference, and shortcut Markdown links and images. Any image-like Markdown syntax that cannot be parsed safely is blocking; fenced and inline code examples are excluded from this scan.
- Record truthful `datePublished` and change `dateModified` only after a material update.
- Recompute package checksums, verify the packaged article matches the reviewed final draft, and list the article, metadata, schema decision, present adjacent media/dataset manifests, and every declared media output required by the package. Do not list arbitrary run evidence or active payloads as deliverables.
- Write `reviews/technical.json` only after the package manifest is final. Its `review-binding-v1` record binds `intake.json`, `drafts/final.md`, `claims.jsonl`, `research/sources.jsonl`, and `publish/publish-manifest.json` to the current run; its reviewer exactly matches `manifest.roles.technical_reviewer`. A later scope, permission, package, or content edit invalidates the approval.
- For a destination-specific URL or CMS, record passed `destination_build_available` and `destination_renderer_checked` checks. For transformed MDX or HTML, also record a passed `reviewed_content_correspondence` check against the approved draft. The validator additionally compares normalized visible text; the recorded check cannot override a mismatch.
- For multilingual content, check language parity and reciprocal hreflang where the destination uses it.

Record these core concepts as named structured checks: one logical H1 (`single_h1` or `single_logical_h1`), `metadata`, a schema decision (`schema`, `schema_decision`, or `structured_data_decision`), `links`, and `assets`. H1, metadata, and links are observable package properties and must be `passed`; they cannot be waived as `not-applicable`. Schema may be `not-applicable` only when `publish/schema.json` explicitly records `applicable: false` with a substantive string reason. Assets may be `not-applicable` only when the article and package contain no detected media references or files. Otherwise those checks must be `passed`. Every check has an explicit `status` plus substantive observation `evidence` containing real letters or numbers; bare booleans, punctuation/symbol padding, placeholder tokens, a restated outcome, explicit text saying the check did not occur, or arbitrary check names do not pass. The documented combined checks `local_links_and_assets` and `media_policy` are valid aliases where their evidence genuinely covers the concept.

Portable MDX v0.1 is a static subset: ESM imports/exports (including valid tokenization without whitespace after the keyword), expressions, custom components, and active embedded HTML are blocked. Leading Unicode format/control characters do not conceal an ESM declaration; forbidden controls are rejected or canonicalized before active-content detection. Markdown URI autolinks, inline links, and reference definitions are checked for unsafe schemes after HTML/CommonMark character-reference decoding, so an encoded `javascript:` or equivalent scheme remains unsafe. HTML packages block scripts, refresh/navigation directives, forms, styles, external style/base mutation, inline event handlers, active URI schemes, and embedded SVG. HTML robot meta tags, Markdown front matter, and `publish/metadata.json` containing `noindex`, `nofollow`, `none`, boolean `noindex: true`/`index: false`, or equivalent nested, flow-style, quoted-key, or folded index-disabled directives contradict package readiness and fail. YAML aliases, anchors, tags, explicit keys, merge keys, block scalars, escaped scalars, and other advanced front-matter forms that the offline gate cannot resolve safely fail closed; simplify them or validate through the destination renderer. Use a destination-owned renderer after this offline gate; do not weaken the package to carry executable content.

All required and present optional publish paths must remain regular files inside
the run. Validation rejects symlinked `publish/article.*` and
`publish/publish-manifest.json` even before the run claims package-ready status,
as well as symlinked package directories or listed files. Manifest paths use
their literal canonical POSIX spelling: no trailing file slash, dot-segment or
double-slash alias, platform backslash, or normalization-by-consumer. Local
article links also reject percent-encoded path semantics and protocol-relative
hosts. A local link must resolve to a checksum-listed regular-file deliverable;
a directory, trailing-slash alias, undeclared file, or external run artifact is
not a valid package target. Optional presence is not permission to import bytes
from outside the run boundary.

## Media checks

- Informative images need contextual alt; decorative images use empty alt.
- Charts and complex diagrams need a visible explanation or equivalent accessible data table.
- Preserve width and height, responsive candidates, crawlable URLs, and a fallback format where applicable.
- Do not lazy-load the likely LCP/hero image. Lazy-load eligible below-fold media.
- Never let optimization remove required credit, rights metadata, or provenance.

## Mutation boundary

- A file export needs no CMS permission.
- Creating a CMS draft requires authorization for that destination and defaults to non-public state.
- Scheduling or publishing requires explicit user authorization for the exact article/destination.
- Never store CMS tokens in the skill or article run.
- Record every mutation in `publish/publish-manifest.json`.
- On successful publication, record a separate receipt with `status`, final `url`, timezone-aware `published_at`, publishing `actor`, `permission_confirmed`, and `package_manifest_sha256`. A requested write or an empty API response is not a successful receipt. Live verification then binds both that package hash and `publish_receipt_sha256`; a downgraded status field does not erase a present mutation receipt or live record.
- Keep lifecycle time ordered: run creation precedes bound verification and editorial reviews; those precede package creation; package-level YMYL review, when applicable, and technical review follow the final package; technical review precedes publication; and live verification does not predate publication. No lifecycle timestamp may be materially future-dated, and `manifest.updated_at` must cover the latest completed event.

SHA-256 binds a technical verdict to package bytes but is not a reviewer
signature and does not prove factual truth, renderer equivalence, source
licensing, or live deployment. Those claims require their own evidence.

## Live verification

After an authorized publication, fetch and render the real URL. Record:

- successful final HTTP response and redirect chain;
- expected article identity and meaningful text in the DOM;
- title, H1, description, canonical, robots and hreflang;
- structured-data syntax and correspondence to visible content;
- required links and assets with correct URLs and MIME types;
- mobile rendering and critical accessibility defects;
- whether a crawl/indexing request was made, without treating the request as indexing proof.

Use `published-pending-verification` until these checks pass. Use `verified-live` only for the observed URL and timestamp. Search indexing and ranking are later external states.

The live record carries `package_manifest_sha256` and `publish_receipt_sha256`, then a `checks` object with entries for `http`, `rendered_content`, `canonical`, `indexability`, `schema`, `links`, and `assets`. Every entry records an explicit `status` and substantive observation `evidence` containing real letters or numbers; a bare boolean, punctuation-only string, `"passed"` string, or prose admitting the observation was unavailable is not proof. `schema` may use `not-applicable` only for a valid non-applicable package decision, and `assets` only when no media work exists. Absence is not success.
