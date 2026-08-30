# Editorial Contract

The editorial contract separates creation from approval. A fluent draft is not evidence of accuracy, usefulness, originality, or publication readiness.

## Role boundaries

| Role | Owns | Must not certify |
|---|---|---|
| Researcher | Search-intent snapshot, source discovery, conflicts, provenance | Final prose or publish readiness |
| Strategist | User job, page opportunity, brief, angle, acceptance criteria | Claim accuracy |
| Writer | A clear draft grounded in the brief and evidence packet | Its own factual or editorial approval |
| Claim verifier | Claim-source entailment, dates, numbers, quotes, contradictions | Style preference or target-score compliance |
| Editorial reviewer | Usefulness, answer quality, voice, clarity, originality, conversion fit | Unsupported claims for the sake of readability |
| SEO reviewer | Intent fit, information architecture, internal journey, metadata | Keyword-density or word-count targets as quality evidence |
| Technical reviewer | Destination build, links, canonical, visible-content/schema consistency, accessibility | Factual truth |
| Qualified YMYL reviewer | Domain risk, jurisdiction, primary evidence, safe framing | Credentials or authority it does not possess |

The writer cannot approve its own factual, editorial, or YMYL verdict. Actor
identities are compared after NFKC, case, whitespace, and default-ignorable
format-control normalization; a visually disguised alias is still the same
reviewer. Prefer an independent subagent or human with fresh context. If only
one agent is available, run a separate verification pass without the writer's
self-score or desired verdict and record `independence_degraded: true`. This
does not replace qualified human review for YMYL content.

## Approval evidence and version binding

A reviewer approves an exact version, not a mutable filename. Verification and
editorial verdicts use `review-binding-v1` JSON records:

```json
{
  "contract_version": "review-binding-v1",
  "run_id": "<article run id>",
  "review_type": "editorial",
  "status": "passed",
  "reviewer": "<same identity as manifest.roles.editor>",
  "reviewed_at": "<timezone-aware timestamp>",
  "artifact_hashes": {
    "intake.json": "<lowercase SHA-256>",
    "drafts/final.md": "<lowercase SHA-256>",
    "claims.jsonl": "<lowercase SHA-256>",
    "research/sources.jsonl": "<lowercase SHA-256>"
  }
}
```

Use `review_type: "verification"` and the verifier role for the independent
claim pass. The required hash map contains exactly the current intake plus the
four content artifacts: final draft, claim ledger, source ledger, and
`research/quality-gate.json`. `reviews/editorial.json` is the machine-verifiable editorial verdict;
`reviews/editorial.md` is the human-readable rationale, findings, and repair
history. Notes alone do not approve the article.

Any edit to the intake, draft, either ledger, or quality gate invalidates both content approvals.
Repair the affected material, rerun verification and editorial review in
lifecycle order, and record new hashes and timestamps. A SHA-256 match proves
only that the record points to the same bytes. It does not authenticate the
reviewer, prove claim entailment, establish semantic quality, or act as a
digital signature.

## Adaptive editorial requirements

- Answer the primary user job clearly and early enough to be useful.
- Use the structure needed by the topic and intent; do not copy a competitor outline mechanically.
- Include only claims supported by the research and claim ledgers.
- Distinguish facts, first-party evidence, opinion, and inference.
- For a named comparison, audit parity before approving the reader path: every
  decisive criterion must be investigated for each named option at the same
  level of detail, or the missing side must be marked unknown. A partial
  competitor description cannot support a product recommendation.
- Preserve brand voice without sacrificing clarity, truth, or required risk language.
- Use natural terminology and entities. Do not calculate keyword density.
- Let coverage determine length. Do not target a fixed word count.
- Add FAQ, media, tables, schema, or summaries only when they improve the task or destination.
- Never invent first-hand experience, tests, interviews, customer stories, data, or product behavior.
- Avoid close paraphrasing and reproduce only short necessary quotations.
- Make metadata accurately represent the page instead of optimizing for a fixed character quota.
- For rewrites and refreshes, review the semantic diff and protected elements before approval.

## Human quality rubric

Review usefulness before calling a draft editorially passed. In
`reviews/editorial.md`, record a concise, evidence-based `pass` or `repair`
verdict for each of these dimensions:

| Dimension | Pass condition |
|---|---|
| Answer and intent | The article answers the primary reader job early and preserves the conditions needed to make the answer true. |
| Truth and boundaries | Material claims are entailed, uncertainty is visible, and product or first-party assertions are not overstated. |
| Information gain | The reader gets a real decision aid, evidence path, method, or constraint not achieved merely by longer coverage. |
| Practical utility | Steps, criteria, examples, or comparisons let a reader act without hidden assumptions. |
| Clarity and voice | The wording is specific, readable, original, and consistent with the verified brand voice or neutral fallback. |
| Journey and conversion | Internal links and CTA appear after the answer, help the next reader action, and make no unsupported promise. |

The reviewer must explain every `repair` verdict and escalate it as P0-P3 when
it affects truth, safety, user intent, packaging, or an honest delivery status.
Do not turn these dimensions into a keyword-density, word-count, or automatic
aggregate-score gate. Read `methodology.md` for query, gap, E-E-A-T,
answer-engine, and visual decisions.

## Severity gates

Each finding must record its severity, evidence, affected artifact, required resolution, owner, and final state.

| Severity | Effect | Examples |
|---|---|---|
| `P0` | Non-waivable block | Fabricated or misattributed source, quote, number, credential, experience, case, or result; citation that contradicts a load-bearing claim; plagiarism; unsafe YMYL guidance; unauthorized external publication. |
| `P1` | Blocks clean `publish-package-ready` | Primary user job is unanswered; material contradiction is unresolved; current research is absent while claiming current SEO readiness; broken final canonical, link, asset, or structured data; rewrite removes protected value without a decision. |
| `P2` | Warning with residual risk | Analytics, site corpus, optional destination preview, or secondary-intent coverage is unavailable. |
| `P3` | Optional enhancement | A useful additional example, visual, secondary internal link, or nonessential clarification. |

P0 findings cannot be bypassed. A user decision to proceed despite an unresolved P1 must remain visible in the handoff and cannot produce a clean `publish-package-ready` status. P2 and P3 findings do not block delivery when their impact is disclosed.

For machine-gating review JSON, each finding records `severity`, a substantive
`message`, and `resolution: open | resolved`. A `passed` or `approved` review
may retain a P0/P1 finding only after it is actually `resolved`. Values such as
`accepted`, `waived`, or `risk-accepted` are not valid resolutions; P0 is never
waivable. Open P2/P3 items are allowed only as visible limitations.

## Review sequence

1. **Scope and mode:** confirm that the draft performs the approved `new`, `rewrite`, or `refresh` task.
2. **Evidence:** resolve P0/P1 claim and citation findings, then write the bound `reviews/verification.json` verdict.
3. **Intent and answer quality:** compare the draft with the brief's user job and acceptance criteria.
4. **Editorial quality:** review clarity, organization, voice, originality, examples, and conversion fit; preserve rationale in `reviews/editorial.md`.
5. **SEO quality:** review search-intent alignment, page differentiation, internal journey, metadata accuracy, and cannibalization risk.
6. **Editorial verdict:** write `reviews/editorial.json` after verification, binding it to the same current draft, ledgers, and quality gate. It must contain passed, evidence-bearing checks for `answer_and_intent`, `truth_and_boundaries`, `information_gain`, `practical_utility`, `clarity_and_voice`, and `journey_and_conversion`, plus `independence_degraded: true|false`.
7. **Destination quality:** validate the actual target format, links, assets, canonical, accessibility, and structured data when applicable.
8. **Mode preservation:** inspect the semantic diff for rewrite or refresh work.
9. **Final verdict:** assign the highest honest status and list every unresolved warning or pending live check.

Semantic defects should be reviewed by an independent agent or person. Mechanical checks may use deterministic scripts, but regex counts and aggregate scores must not decide publication readiness.

Keep the lifecycle monotonic: neither review may predate run creation;
verification does not follow editorial approval; package creation follows the
content reviews; and all completed review times are covered by
`manifest.updated_at`. Future-dated records do not create readiness.

## Iteration and stopping

The orchestrator owns a bounded revision loop. Route each failed gate back to the role able to fix it, then rerun affected downstream checks. Do not let sub-skills create independent retry loops.

For Full work, the loop starts from a preserved `drafts/baseline.md` and ends
with a quality-gate-bound `research/iteration-report.md`. The report compares
baseline and final across intent/coverage, truth/evidence, reader utility, and
clarity/voice; it names both improvements and regressions. The last prose pass
may use an available humanization capability, but it is an editorial operation:
facts, citations, qualifiers, disclosures, and claim boundaries remain intact,
then verification and editorial review rerun against the final bytes. A claim
that the draft "sounds human" is neither an editorial verdict nor a substitute
for this comparison.

Stop and assign the applicable lower status (`blocked`, `draft-only`, `needs-evidence`, or `needs-expert-review`) when:

- The same material defect remains without new evidence or a safe correction.
- Fixing it requires user input, qualified expert review, unavailable authority, or external permission.
- Further rewriting would hide uncertainty rather than resolve it.

Preserve the latest draft, review findings, and specific next action. The user should receive the diagnostic, not a falsely approved article.

## Final handoff

Report:

- Mode, target, language, locale, and `as_of` date.
- Final status and the checks that support it.
- Source and claim-ledger completion.
- P0-P3 findings, including resolved and open items.
- Research, analytics, build, and reviewer limitations.
- Semantic changes for rewrite or refresh work.
- Whether publication occurred, who authorized it, and whether the live page was verified.
- The next measurable decision, not a generic SEO score.
