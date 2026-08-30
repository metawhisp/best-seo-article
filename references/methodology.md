# Article methodology

Use this reference for a `new`, `rewrite`, `refresh`, or `external` article.
It turns a topic into a defensible reader decision. It does not predict rankings
or turn a checklist into proof of usefulness.

## 1. Pick the smallest justified operating depth

| Use | Depth | What is deliberately small |
|---|---|---|
| Low-risk informational answer with one clear reader job and no major product, health, legal, financial, or comparison claim | Lite | A bounded SERP sample, one query decision, one intent-gap note, the sources needed for retained claims, and a human editorial review. |
| Commercial, comparison, pillar, linkable, migration, YMYL, high-traffic, first-party-data, or multi-intent work | Full | Candidate-query decision, site-overlap review, opened competitor matrix, source plan and snapshots, internal-link map, visual/data plan, and a deeper independent review. |

Lite must still preserve the same non-negotiables: current intent evidence,
claim-level support, no invented experience, a distinct answer, and a human
editorial verdict. Full is required when a missing artifact could change the
recommendation, safety, conversion, or publication decision.

## Competitive standard: do not confuse a sourced summary with a SERP contender

Use `competitive_standard: serp-competitive` for Full work. It means the page
must give the reader something decision-relevant that the opened SERP does not
already provide as a generic summary. It does **not** mean that a ranking,
traffic outcome, or a fixed word count is guaranteed.

The quality gate records this as `reader_advantage`. One of these evidence paths
is required:

| Advantage | What must be recorded | Suitable use |
|---|---|---|
| `original-test` | Protocol, date, setup, results, limitations, source/claim IDs, and a visible article section | A product, workflow, tool, or migration comparison where hands-on behaviour changes the choice. |
| `original-data` | Dataset or export, collection method, scope, calculations, limitations, source/claim IDs, and a visible article section | A benchmark, survey, usage analysis, or audited first-party result. |
| `expert-input` | Named qualified input, scope, date, disclosure/permission, limitations, source/claim IDs, and a visible article section | A consequential or specialist decision where an expert can add real judgment. |
| `decision-framework` | A usable, bounded decision aid with inputs, steps, outputs, limitations, source/claim IDs, and a visible article section | A comparison, guide, or how-to where a reader needs to choose among documented trade-offs. |
| `serp-synthesis` | A source-bound explanation of the intent, recurring questions, conflicts, and a specific unserved decision | A page that resolves a real SERP coverage gap without claiming original experimental results. |

An empirical advantage (`original-test`, `original-data`, or `expert-input`) is
required only when the article claims testable outcomes such as accuracy, speed,
reliability, security, or compatibility. For ordinary scalable SEO production,
the advantage may instead be a source-bound `serp-synthesis` or
`decision-framework`. A vendor-feature table, copied competitor outline, or
generic "try both" checklist does not qualify because it does not resolve a
specific reader decision or coverage gap.

## 2. Start with the minimum useful input

Do not hold a normal article hostage for a perfect brief. Record unknowns and
use conservative defaults. Ask only for an input that would materially change
the page or the truth of a claim.

| Input | What it decides | If absent |
|---|---|---|
| Topic, question, or seed query | What problem to investigate | Required. |
| Site/domain and known existing URLs | Cannibalization, internal links, product facts | Do a bounded public review; disclose incomplete site coverage. |
| Reader and country/language | Intent, terminology, examples, legal context | Infer cautiously from the request and SERP; mark the inference. |
| Business outcome and permitted CTA | The next action after the answer | Answer the reader first; use no product promise or hard-sell CTA. |
| Verified product facts, first-party data, screenshots, or case studies | What the article may claim or show | Omit the claim, use a primary public source, or label the gap. |
| Analytics, GSC, Ahrefs, crawl, or keyword export | Opportunity selection and measurement | Use free public research; never fabricate volume, difficulty, ranking, traffic, or sitewide coverage. |
| Destination and publication permission | Package format and external actions | Produce Markdown only; no CMS draft or publication. |

Record the target, locale, permissions, and unknowns in `intake.json` before
research. Record user-supplied facts separately from observed evidence.

## 3. Select a query by decision evidence, not a keyword metric

Create `research/query-decision.md`. Start with one to three plausible queries
or questions. For each, write one short evidence-backed row:

| Criterion | What to inspect | Decision rule |
|---|---|---|
| Reader job | The concrete outcome, question, or friction | Reject a query that cannot be stated as a useful reader job. |
| Intent fit | Current results, query wording, and search features | Reject or split a query whose dominant intent conflicts with the page's job. |
| Site overlap | Existing URLs, sitemap/crawl, or bounded public site search | Recommend `rewrite`/`refresh` when an existing page already serves the same job. |
| Evidence advantage | A real first-party proof, better primary source, worked method, or decision aid | Do not choose a page merely because it can have more words or headings. |
| Business and reader fit | The product can help after the answer without distorting it | Reject an artificial product tie-in. |
| Feasibility | Available sources, reviewer expertise, risk, and time sensitivity | Hold the topic if the load-bearing answer cannot be verified. |

Use `selected`, `hold`, or `recommend-rewrite` as the outcome. A qualitative
decision is valid; an unobserved volume, difficulty, traffic potential, or
"easy to rank" score is not. If a paid or user-provided export exists, preserve
its date, provider, scope, and caveats beside the decision rather than merging
it with observed facts.

## 4. Determine intent and the gap before outlining

Create `research/intent-gap.md` from a dated SERP snapshot. Record query,
locale, device, date, result features, and at least the leading relevant pages
that were actually opened. Lite normally opens enough results to establish a
stable pattern; Full requires five or more relevant opened results before the
article can become `content-ready`.

For each opened competitor, capture only observations needed for the decision:

| Page | Reader job/intent | Format and decisive sections | Evidence type | Missing, weak, stale, or unsafe element |
|---|---|---|---|---|
| URL and title | What it helps a reader do | Guide, comparison, tool, category, etc. | Official source, test, opinion, unspecified | Observation, not a copied outline |

Use this compact SERP research matrix for every Full article. It is the
repeatable core of the workflow; none of its fields asks the writer to guess a
keyword score or a ranking outcome.

| Signal | Record | Why it changes the article |
|---|---|---|
| Query context | Exact query, locale, device, date/time, acquisition method | Intent and results change by market and over time. |
| Result shape | Observed rank, title/URL, page type, result feature, video/community presence | Prevents writing the wrong format for the actual SERP. |
| Coverage | Reader job, main-content word count and method, key sections/entities, freshness | Reveals what has already been answered; word count is context, never a quota. |
| Evidence quality | Whether the page is official, primary, editorial, opinion, product-led, or unknown | Competitors reveal coverage; they do not automatically prove facts. |
| Unserved decision | One reader question, constraint, contradiction, or missing implementation step | Becomes the article's information gain and acceptance criterion. |
| Optional SEO data | Dated provider/export, scope, volume, difficulty, ranking, links, GSC performance | Use only when supplied or permitted. Mark unavailable data; never fabricate it. |

Search public video and community discussions when they expose recurring
reader questions, terminology, objections, or a format Google visibly serves.
Treat them as demand/coverage signals, not proof of a product or performance
claim unless the underlying assertion is independently sourced.

Then write these five conclusions in plain language:

1. **Dominant intent:** informational, commercial investigation, transactional,
   navigational, or a justified mixed intent.
2. **Reader stage:** learn, choose, configure, troubleshoot, compare, or act.
3. **Minimum answer:** the question a good page must answer first.
4. **Real information gain:** an auditable improvement such as an official
   source path, a disclosed first-party method, a decision tree, a tested setup,
   a useful boundary, or a missing reader constraint. For Full competitive work,
   record the specific `reader_advantage` described above; a source list alone
   is not sufficient.
5. **No-go condition:** what would make this page a duplicate, a weak rewrite,
   or a claim we cannot support.

More sections, a different adjective, or repeating a competitor's advice is
not information gain. A competitor is evidence of search intent and coverage,
not a source for factual product claims and never a template to paraphrase.

Before approval, create `research/quality-gate.json`. For every relevant SERP
page it records the URL, observed position, format, reader job, main-content
word count and method, and a concrete gap. It also records the target article's
reader path, decision criteria, mapped headings/claims, observed word count
and SERP-length context, information gain, and a reasoned visual/data choice.
This is evidence for editorial judgment, not a fixed word-count target or an
automatic quality score.

## 5. Plan evidence and first-party proof

Create `research/source-plan.md` before drafting load-bearing sections. For
each intended assertion, name the claim, why it matters, best source type,
source owner, volatility, required snapshot, and what to do if the source does
not support it. Then populate the machine-readable source and claim ledgers.

Use sources in this order when they fit the claim: official or primary source;
authorized first-party evidence; reputable secondary explanation; then a
clearly labelled opinion or inference. Save the exact support location or a
permitted immutable snapshot for claims whose wording, product state, numbers,
or availability could later change.

First-party experience earns trust only when it is specific and auditable:

- name what was observed or tested, when, by whom, with what scope and method;
- state material limitations and incentives; and
- obtain disclosure permission before publishing private data, screenshots,
  customer stories, or results.

Do not manufacture E-E-A-T by adding a fictional author, credential, benchmark,
testimonial, client, experiment, or "we tested" sentence. A real author bio is
useful only when its claimed expertise is verified and relevant. For YMYL work,
follow the qualified-reviewer gate in `ymyl.md`.

## 6. Build the reader path before prose

The brief must state one primary reader job, intended reader, answer, decision
criteria, exclusions, information gain, internal entry/exit path, conversion
action, and acceptance criteria. The outline maps every material section to a
reader need and evidence.

Use this default shape only when it fits the intent:

1. Give the direct, qualified answer early.
2. Explain the criteria or mechanism needed to trust and apply it.
3. Give the sequence, comparison, or decision path the reader came for.
4. Surface limitations, costs, exceptions, and "not for you" cases before the
   CTA.
5. Offer a truthful next action: continue learning, compare, download, or ask
   for help. The CTA cannot promise an outcome the evidence does not support.

For an existing site, add an internal link only when it is the best next reader
step. Record source page, anchor concept, destination, reader purpose, and
validation state. If no crawl/corpus was available, do not invent site URLs;
leave a visible P2 limitation.

## 7. Write for extraction without writing for a machine

Search, assistants, and readers can all benefit from a clear answer. The goal
is not to chase citations by a model.

- Use a direct answer under the H1 when the question has one; preserve important
  conditions and uncertainty instead of oversimplifying it.
- Use descriptive headings that match real subquestions. Put definitions,
  steps, and comparison criteria near their answer.
- Make lists, tables, and examples do actual work. Do not add an FAQ, schema,
  summary, or "people also ask" block merely because another page has one.
- Quote sources sparingly and synthesize in original wording. Do not copy a
  winning page's order, examples, or phrasing.
- Treat AI-answer visibility, featured snippets, rich results, and rankings as
  external outcomes, never promises or acceptance criteria.

## 8. Choose tables and images only when they reduce reader work

Read `visuals-and-data.md` for rights and validation mechanics. Use the smallest
medium that resolves a real decision:

| Need | Use | Do not use when |
|---|---|---|
| Repeated field comparison | Accessible HTML/Markdown table | A short list says the same thing. |
| Trend, distribution, or numeric relationship | Chart plus source data, method, and table fallback | The data is missing or not comparable. |
| A real interface state or verification step | Owned/current screenshot with provenance | It would be recreated, generated, stale, or private without permission. |
| A process or architecture that prose obscures | Diagram with accessible long description | A paragraph or table is clearer. |
| Mood, social, or CMS presentation | Rights-cleared hero image | It is generic decoration or a text-heavy keyword banner. |

There is no image, table, chart, or graph quota. An honest zero-visual article
is better than an unverified visual. Data visuals require the dataset manifest;
product screenshots require a real capture and permission; generated media must
not impersonate product UI, results, people, or testimonials.

## 9. Review with a human rubric, then bind the verdict

The independent editorial reviewer records a short rationale for each dimension
in `reviews/editorial.md` and writes the bound JSON decision only after the
claim verifier passes. Use `pass`, `repair`, or a P0-P3 finding with evidence;
do not convert this into an automatic aggregate score.

| Dimension | Reviewer asks |
|---|---|
| Answer and intent | Does the opening answer the actual reader job with the needed conditions? |
| Truth and boundaries | Are material claims entailed, current enough, and clearly qualified? |
| Information gain | Does the page add a real decision aid, evidence path, or useful constraint beyond the opened results? |
| Practical utility | Can the reader follow the steps, criteria, or comparison without hidden leaps? |
| Clarity and voice | Is it readable, specific, original, and appropriate for the verified brand voice? |
| Journey and conversion | Do internal links and CTA follow naturally after value, without bait, pressure, or invented promises? |

`content-ready` requires a passed, bound review for all six dimensions and no
unresolved P0/P1 issue. The reviewer must state whether independence was
degraded; an isolated pass is a disclosed limitation, not independent approval.
An editor may accept an open P2/P3 limitation only if it is explicit in the
handoff. A rubric cannot override an unsupported claim, missing qualified
review, broken package, or missing publication permission.

## 10. Learn after publication, not before it

Only an explicitly authorised publication may move beyond a content package.
Verify the live page separately. If GSC, analytics, or rank data is available,
compare like-for-like windows and state competing causes; a before/after change
does not prove that the article caused it. Use the outcome to decide whether to
refresh evidence, improve the reader path, consolidate overlapping pages, or
stop investing in the topic.
