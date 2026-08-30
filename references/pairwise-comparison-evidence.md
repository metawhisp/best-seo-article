# Pairwise comparison evidence

Use this reference for a Full comparison when the article could make a reader
choose one product, workflow, service, or configuration over another. Its job is
to turn "we tested it" into a reviewable packet. It does not create permission
to buy a plan, use private data, install software, publish results, or claim a
universal winner.

## Choose the right evidence path

Use one of these only when it can answer the reader's actual decision:

| Path | Use when | Minimum artifact |
| --- | --- | --- |
| Controlled pairwise test | Product behaviour in a defined setup changes the choice. | Protocol, run log, reference input, raw outputs, scoring method, limitations, and source/claim records. |
| Original dataset | A collected export, survey, support sample, or audit can answer the decision. | Rights-cleared source data, field definitions, transformation, aggregate results, limitations, and source/claim records. |
| Qualified expert input | A specialist judgment is necessary and the expert is genuinely qualified for that exact question. | Identity/qualification, question set, dated responses, disclosure/permission, limitations, and source/claim records. |

Do not treat public reviews, competitor pages, sales demos, a few unsourced
anecdotes, or an unrepeatable personal impression as an empirical comparison.
They may inform intent, questions, or a `needs-evidence` draft.

## Controlled-pairwise protocol

Write `research/pairwise-test-protocol.md` before running the test. The packet
must contain these fields in substantive prose or structured data:

| Field | Record | Why it matters |
| --- | --- | --- |
| Decision question | The exact reader decision the test can settle. | Stops a benchmark from becoming a generic feature tour. |
| Products and versions | Product, plan, version/build, and configuration for each side. | Product behaviour and pricing can change. |
| Environment | Hardware, OS/browser/runtime version, locale, network state when relevant, and peripherals. | Makes the outcome scoped and reproducible. |
| Input corpus | Rights-cleared inputs, source, language, sample size, inclusion/exclusion rules, and reference answer where applicable. | Prevents cherry-picking and hidden private data. |
| Procedure | Same starting state, order/randomization, repetitions, operator actions, and failure handling. | Reduces a one-off or order-effect result. |
| Measures | Reader-relevant measures and exactly how they are computed. | Stops vague "felt faster" or "more accurate" claims. |
| Raw and transformed output | Preserve both when a product cleans, summarizes, reformats, or post-processes output. | A polished output must not hide an input-recognition error. |
| Results | Per-run observations before aggregation, plus formulas and units. | Lets reviewers see variance and outliers. |
| Limitations | Sample, setup, operator, incentives, missing cases, and generalization boundary. | Prevents one setup from becoming a universal verdict. |
| Disclosure | First-party relationship, payment, access, sponsorship, or product ownership. | Readers can weight the result honestly. |

## Test only criteria that can change the choice

Start from three to five criteria. A dictation comparison might use transcription
corrections against a reference text, time from trigger to usable output, number
of manual repair actions, insertion outcome in named target apps, and explicitly
chosen data-handling mode. A database comparison might instead use query
correctness, tail latency, operating cost, recovery behaviour, and migration
effort.

Each metric needs a definition, unit, collection method, and interpretation
rule. Do not aggregate incomparable measurements into an invented score. When a
metric is subjective, use a predeclared rubric and preserve the individual
ratings rather than calling it objective.

## How the article uses the packet

1. Add the evidence packet to `research/sources.jsonl` as a `user-provided`,
   `primary`, or disclosed `first-party` source with a clear locator.
2. Add each reported result as a claim with exact support. Do not cite the
   protocol as if it were a result.
3. State the setup and material limitations in the article near the result.
4. Give the reader the data or a concise per-run table when rights and space
   allow; a chart is useful only with a source dataset and an accessible table.
5. Bind the finished test source and result claims in `reader_advantage` with
   `kind: original-test` or `original-data`.
6. Rerun claim verification and editorial review after results are added. A
   changed draft, ledger, or protocol invalidates previous approvals.

## Stop conditions

Do not begin an endless rewrite loop. Lower the article to `needs-evidence`
when a required product, plan, environment, permission, source corpus, or
qualified reviewer is unavailable. Record the smallest next input that would
unlock the decision. For example: "Raycast Pro access on the same Mac and a
predeclared rights-cleared corpus covering English, mixed-language speech, and
the reader's jargon." State the planned sample size and why it suits the claim;
do not treat a small pilot as universal proof. Do not fill the gap with made-up
results, screenshots, ratings, or a model's simulated test.
