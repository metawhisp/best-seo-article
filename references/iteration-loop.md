# Iterative article improvement loop

Use this reference for every Full article and whenever a writer is asked to
improve a draft until it is genuinely more useful. The loop improves a reader
decision; it does not chase a larger word count, a keyword score, or a merely
more human-sounding surface.

## The loop

1. **Freeze a baseline.** Save the first complete, evidence-led draft as
   `drafts/baseline.md`. It is a comparison point, not a publishable version.
2. **Find the smallest material gap.** Use the SERP matrix, brief, source plan,
   claim ledger, and prior review findings. Name the reader question, missing
   constraint, unsupported premise, or unclear step that would change a real
   decision.
3. **Repair with evidence.** Add, narrow, reorder, or remove only the affected
   content. Expanding coverage is justified only when it answers an in-scope
   reader question. Keep secondary intents, broad category guides, and product
   lists as separate pages when they need a different answer or evidence set.
4. **Run the final voice pass.** Apply the available humanization capability
   (for example `de-ai`) only after the factual repair. Preserve source meaning,
   citations, qualifiers, terminology, and the reader's decision boundary. Do
   not use humanization to evade AI detection, fabricate lived experience, or
   make a weak claim sound certain.
5. **Revalidate the final bytes.** A style edit can change meaning. Rerun claim
   verification, then the independent editorial review, against the exact final
   draft and current ledgers.
6. **Compare, do not merely declare success.** Write
   `research/iteration-report.md` and bind it from `research/quality-gate.json`.
   Record what improved, what stayed unchanged, every regression, and the next
   evidence-backed action.

## Definition of done by gate

| Gate | It is done only when | It must not be substituted with |
| --- | --- | --- |
| Scope | One primary reader job, page type, locale, and no-go condition are recorded. Existing-page overlap is checked to the available site scope. | A broad topic label or a volume estimate. |
| Intent and coverage | Opened results establish the dominant intent, required answer shape, and a specific unserved decision. Full work has the required deeper matrix. | Copying headings, length, or a competitor's recommendation. |
| Evidence | Every load-bearing premise has direct support or is removed, narrowed, or labelled inference. Comparison criteria have parity. | Snippets, authority by association, or a competitor page as factual proof. |
| Reader path | The first screen answers the primary job; criteria, exceptions, limits, and next action let the reader act. | A generic introduction, a universal winner, or a CTA before the answer. |
| Visual and package | A table, image, chart, FAQ, schema, or video demonstrably reduces reader work and passes its applicable rights, data, and technical checks. | A media, FAQ, schema, or word-count quota. |
| Humanization | The final prose is specific and readable while all evidence, claims, qualifiers, links, and required disclosures retain their meaning. | Detector evasion, invented voice, or a factual rewrite without a new review. |
| Independent review | Claim and editorial reviews pass against the final bound artifacts; all P0/P1 defects are resolved. | A self-score, a grammar pass, or a green schema alone. |
| Iteration decision | Baseline-to-final comparison shows no unresolved P0/P1 regression and gives the next smallest action or an honest stop reason. | "Looks better" or an aggregate SEO score. |

## What the comparison must cover

For a Full run, assess these dimensions in the machine-readable
`iteration_assessment`:

- `intent_and_coverage`: Does the page answer the selected job completely
  enough, without swallowing a different page type or reader job?
- `truth_and_evidence`: Did every new or changed material premise retain direct
  support and required qualifiers?
- `reader_utility`: Can a reader make the promised decision or complete the
  task without hidden steps?
- `clarity_and_voice`: Is the final prose direct, original, and appropriate to
  the verified audience without sounding formulaic?

For each dimension use `improved`, `unchanged`, `regressed`, or
`not-applicable`, plus concrete evidence. A regression is not hidden: put it in
`unresolved_regressions` with severity and a repair or stop action. A
`content-ready` Full run cannot carry an unresolved P0 or P1 regression.

## Stopping rule

One evidence-led improvement loop is required for Full work. Continue only
when a new finding can be repaired safely with available evidence. Stop at the
highest honest lower state when the next repair needs a source, paid access,
authoritative product test, qualified reviewer, destination access, or user
decision. Do not make cosmetic rewrites merely to produce another iteration.

The loop does not promise a rank, traffic, AI answer citation, or universal
reader satisfaction. Its result is a reviewable final article package and a
clear next decision.
