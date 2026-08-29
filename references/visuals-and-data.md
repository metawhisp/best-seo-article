# Visuals and data policy

Use this policy when an article may contain a hero image, screenshot, diagram,
table, chart, or video. Visuals are optional: there is no minimum count and no
SEO quota. Add one only when it helps a reader understand, verify, compare, or
complete something.

## Choose the smallest useful medium

| Medium | Use when | Do not use when |
| --- | --- | --- |
| Hero | The CMS, social preview, or Discover workflow needs a representative image, or the image materially frames the topic. | It would be generic decoration, a logo, or a text-heavy keyword banner. |
| Screenshot | A real interface state, procedure, or dated product observation needs to be shown. | A diagram or sentence is enough, or the interface would have to be invented. |
| Diagram | A process, hierarchy, architecture, or relationship is hard to understand linearly. | The idea has only one simple step or relationship. |
| HTML table | Readers need exact values or repeated-field comparisons. | A list communicates the same information. Never publish a data table only as an image. |
| Chart | A sourced trend, distribution, or relationship is the point. | There is no machine-readable source, the values are illustrative, or only one or two numbers need stating. |
| Video | Motion, timing, or interaction is essential to the task. | It would merely narrate the article or repeat static content. |

Every proposed asset must have a `purpose`. If removing it would not make the
article less useful, omit it.

Human-facing media evidence—purpose, creator/publisher, methodology and
transformation descriptions, required attribution, informative alt text,
redaction notes, and generated/synthetic disclosures—must contain at least one
Unicode letter or number. Punctuation, emoji, or invisible padding alone is not
evidence. Keep technical IDs, paths, MIME types, hashes, and symbol units such
as `%` under their dedicated machine-field rules.

## Required artifacts

Package visual work with:

- a media manifest conforming to `schemas/media-manifest.schema.json`;
- embedded dataset records conforming to the dataset definition in
  `schemas/dataset-manifest.schema.json`, or a standalone dataset manifest;
- immutable local snapshots for factual datasets and original screenshots;
- machine-readable transformation/spec files for charts;
- visible attribution wherever the applicable license requires it;
- text alternatives and responsive output metadata.

Run:

```bash
python3 <skill-root>/scripts/validate_media.py path/to/article-run

# Or validate an individual manifest explicitly:
python3 <skill-root>/scripts/validate_media.py path/to/media-manifest.json \
  --dataset-manifest path/to/dataset-manifest.json
```

When the positional input is a run directory, the validator reads
`media-manifest.json` and automatically includes a present
`dataset-manifest.json`; the run directory also becomes the asset root, so file
existence, byte size, SHA-256, MIME signatures, and static HTML/SVG safety are
checked. In run-directory mode it also compares the media `run_id` with the
article manifest and resolves every media `claim_id` against `claims.jsonl`.
The JSON report exposes a deterministic `identity` object with `run_id`, asset,
dataset, claim, and output-path lists so a parent validator can reconcile the
package without reparsing the manifest. `--dataset-manifest` is repeatable; its
datasets are merged with any embedded records and duplicate IDs fail. For
single-file mode, pass `--asset-root path/to/article-package` to enable the same
file checks. Local provenance and rights records cannot pass cleanly without an
asset root because the validator must inspect the exact file. HTML and SVG
cannot pass cleanly without an asset root because their content cannot otherwise
be inspected. Release validation always uses run-directory mode or an explicit
asset root; manifest-only validation checks the contract but does not claim that
unopened accessibility files are publishable. The JSON report is written to
stdout with stable ordering and no timestamps:

A standalone `dataset-manifest.json` remains valid when no visual asset exists;
the parent run validator invokes dataset-only validation instead of requiring a
fake media manifest. Conversely, every media path referenced by an article or
present as a declared publish output must live under `media/` or
`publish/assets/` and be claimed by a validated asset output or variant. A
checksum cannot promote an arbitrary file or raw dataset snapshot into the
publish deliverable set. Raw snapshots remain evidence unless an allowed,
declared media output is derived from them. An empty media manifest never
authorizes undeclared files. This reconciliation covers inline,
full-reference, collapsed-reference, and shortcut Markdown image forms plus raw
HTML media. Image syntax that the lightweight parser cannot resolve fails closed
instead of bypassing provenance; examples inside fenced or inline code remain inert.

- exit `0`: no hard failures;
- exit `1`: manifest, policy, rights, provenance, accessibility, or file failure;
- exit `2`: the validator itself is unavailable, incomplete, or cannot access a
  required validation resource. Exit `2` is never a pass.

The validator is intentionally offline and standard-library-only. Raster and
video files must match a per-asset MIME/extension allowlist and known file
signature. HTML is limited to a static table-element allowlist. SVG is limited
to static drawing elements and local fragment references; scripts, event
handlers, imported styles, entities, foreign objects, and external URLs fail.
Network
crawlability, factual interpretation, fair use, model/property releases, visual
relevance, misleading crops, and editorial judgment remain explicit human or
post-publish review gates.

## Rights and provenance

Record the source landing page or local origin record, creator or publisher,
retrieval time, license identifier, license URL or local rights evidence, usage
basis, attribution requirement, transformation rights, and release status. A
search result, hotlinked image URL, or `royalty-free` label is not proof of
permission. Owned and user-provided media may use an internal evidence record;
do not invent a public license URL merely to satisfy a field.

The same honest alternative applies to first-party and user-export datasets:
record either `source_url` or `source_path`, and either `license_url` or the
local `license.evidence_path`. The immutable `snapshot_path` remains required;
it does not by itself explain ownership or permitted reuse.

Every local provenance or rights record is a non-empty regular file inside the
article-run boundary. Its path uses literal canonical POSIX spelling, must not
traverse a symlink, and is paired
with the corresponding SHA-256 field (`source_path_sha256`,
`license_evidence_sha256`, or `license.evidence_sha256`). A path string, empty
placeholder, directory, named pipe, or checksum-free internal note is not
evidence. This keeps first-party and user-provided workflows free and local
without weakening the release gate.

`manual_review_status: approved` is never sufficient by itself. Add a
`manual_review` record with a substantive reviewer identity, timezone-aware
`reviewed_at`, substantive observation evidence, and explicit scopes. Evidence
that explicitly says the review was not performed is not approval. Recognizable people
require the `model_release` scope; protected property requires
`property_release`. If the evidence is also stored locally, bind its path to
`evidence_sha256` and inspect it under the same no-symlink rule.

Hard-block publication when:

- rights status is not `verified`;
- commercial use is disallowed for a commercial article;
- an asset was modified while modification is disallowed;
- required attribution is empty or contains no letter or number;
- an asset is editorial-only in a commercial or promotional context;
- recognizable people or protected property require review and that review is
  not approved;
- the license or source is unknown.

Keep an asset-page URL and receipt/license evidence for paid stock. Openverse and
Wikimedia Commons do not provide one blanket license: verify the license on each
file page. Treat CC BY attribution as mandatory, CC BY-SA as a manual
share-alike compatibility review, CC BY-ND as non-editable, and CC BY-NC as
blocked for commercial projects.

For current provider terms, check the official pages at acquisition time:

- Unsplash: <https://unsplash.com/license>
- Pexels: <https://www.pexels.com/legal-pages/license>
- Pixabay: <https://pixabay.com/service/license-summary/>
- Wikimedia Commons reuse: <https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia/en>
- Adobe Stock: <https://stock.adobe.com/license-terms>
- Shutterstock: <https://www.shutterstock.com/license>

Do not hard-code prices or assume that a free tier, subscription, or paid asset
removes trademark, likeness, privacy, or endorsement restrictions.

## Data and charts

A factual chart must resolve to one `dataset_id`. Preserve the source snapshot,
SHA-256, publisher, retrieval date, license, units, timeframe, field definitions,
methodology, and every transformation used. Chart `field_names` and
`transform_id` must exist in that dataset record. Its `spec_path`,
`spec_sha256`, and `transform_output_sha256` must exactly match the selected
transformation; a transform name alone is not provenance.

Never:

- type unsourced values directly into a chart;
- imply causation from correlation;
- hide units, denominator, timeframe, sample, or missing-data caveats;
- add more numeric precision than the source supports;
- use synthetic or illustrative data as factual evidence.

Synthetic data is allowed only for a clearly labeled example. Set `synthetic` to
`true`, include an on-visual/caption disclosure, and set `evidence_use` to
`false`. If verified data is unavailable, fall back to an HTML table or prose;
do not manufacture a chart.

Publish a chart with a concise alt, a long description, and an accessible HTML
table containing its values. Encode series with labels, shapes, or line styles
as well as color.

## Screenshots

A screenshot must be an actual capture, not a generated or reconstructed UI.
Record its source URL, capture time, viewport, locale, authentication state,
original file and hash, redactions, and PII review status. Preserve the original
uncropped capture when annotations or crops are used.

Before approval, check for names, email addresses, avatars, customer records,
tokens, API keys, browser tabs, notifications, analytics identifiers, and other
private data. A validator can require `pii_review_status: approved`; it cannot
prove that the review was correct.

If a real capture cannot be used, create a schematic mockup labeled as a mockup,
or omit the visual. Never use a mockup as evidence of shipped functionality.

## Generated media

Generated media may illustrate an abstract concept, but it is never factual
evidence. Record provider, model/version, generation time, prompt hash, input
references and their rights, and retained provenance metadata. Do not remove
C2PA or IPTC digital-source metadata.

Use `ai.input_assets: []` only when generation truly used no reference asset.
Otherwise add one record per reference image, source asset, mask, or control
image. Each record has a stable input ID, kind, creator, retrieval time, content
hash, origin URL or local file, verified usage basis, reuse/modification flags,
and its own rights-evidence URL or checksum-bound local record. A single
`input_rights_verified` boolean is not accepted because it cannot identify which
inputs were reviewed.

Do not generate a real product screenshot, testimonial, event, person, dashboard,
scientific result, or medical/financial/legal evidence. Do not imply that a
generated person uses or endorses the product. Human review is required for
likenesses, trademarks, sensitive domains, and reference-image rights.

Provider terms can change. Recheck them at generation time. For example, OpenAI
states that output may be inaccurate or non-unique, while Adobe's commercial-use
and indemnification conditions depend on the exact Firefly feature and agreement:

- <https://openai.com/policies/terms-of-use/>
- <https://www.adobe.com/legal/licenses-terms/adobe-gen-ai-user-guidelines.html>

## Accessibility

- Decorative images use `alt=""` and do not carry evidence.
- Informative images use concise contextual alt text containing real words or
  numbers; punctuation, emoji, or invisible characters alone do not count.
- Functional images describe the action or destination.
- Charts and diagrams also need a checksum-bound long-description file with
  substantive readable content; charts need a checksum-bound static HTML table
  with a table element, headers, data cells, substantive values, and a caption
  or table `aria-label`.
- Video with meaningful audio needs checksum-bound reviewed captions and a
  substantive transcript. Caption timing headers alone do not count. Add a
  checksum-bound substantive visual description when important information is
  not present in the audio.
- Do not convey distinctions by color alone. Target WCAG AA: 4.5:1 for normal
  text, 3:1 for large text, and 3:1 for essential graphical objects.

References:

- W3C image decision tree: <https://www.w3.org/WAI/tutorials/images/decision-tree/>
- W3C complex images: <https://www.w3.org/WAI/tutorials/images/complex/>
- W3C media accessibility: <https://www.w3.org/WAI/media/av/>
- WCAG 2.2: <https://www.w3.org/TR/WCAG22/>

## Performance and search presentation

Use standard `<img>`/`<picture>` markup with stable crawlable URLs, descriptive
filenames, contextual alt text, intrinsic width and height, and responsive
variants. The probable LCP/hero image must be discoverable in initial HTML, must
not be lazy-loaded, and may use `fetchpriority="high"`. Lazy-load below-fold
images. Project-configured byte budgets are engineering limits, not Google
ranking rules.

When Discover support is explicitly requested, use a relevant high-resolution
hero at least 1200 px wide and more than 300,000 total pixels, provide a safe
landscape crop, and enable `max-image-preview:large`. Do not apply this as a
universal article requirement.

Preserve critical rights metadata during optimization. Google supports image
license metadata, IPTC digital-source types, and C2PA details; structured data
must describe the actual published asset and must not claim rights the publisher
does not hold.

Primary references:

- Google Images best practices: <https://developers.google.com/search/docs/appearance/google-images>
- Google image-license metadata: <https://developers.google.com/search/docs/appearance/structured-data/image-license-metadata>
- Google Discover: <https://developers.google.com/search/docs/appearance/google-discover>
- web.dev LCP: <https://web.dev/articles/optimize-lcp>
- Google Video SEO: <https://developers.google.com/search/docs/appearance/video>

## Fallbacks

- Hero: approved first-party asset -> correctly licensed stock -> clearly
  conceptual branded illustration -> omit.
- Screenshot: real redacted capture -> official approved media -> labeled
  schematic -> omit.
- Chart: verified dataset -> semantic table -> prose.
- Diagram: authored accessible SVG -> structured list.
- Video: owned recording -> screenshot sequence and transcript -> omit.

Omission is a valid outcome. Never relax evidence, privacy, accessibility, or
rights gates merely to satisfy a visual plan.
