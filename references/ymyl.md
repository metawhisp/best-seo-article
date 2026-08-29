# YMYL and High-Stakes Content

Apply this policy when content could materially affect health, safety, financial stability, legal rights, civic participation, employment, housing, or another high-impact decision. Classification runs before research and again after drafting because risk may emerge through the article's claims or recommendations.

## Classification

Treat the article as YMYL when it includes or could reasonably be read as:

- Medical, mental-health, diagnostic, treatment, medication, or safety guidance.
- Legal, regulatory, tax, immigration, benefits, compliance, or rights guidance.
- Investment, credit, debt, insurance, retirement, tax-planning, or material financial guidance.
- Emergency, physical-safety, cybersecurity-safety, or other harm-sensitive instructions.
- High-impact claims about elections, public services, employment, housing, or education decisions.

When classification is uncertain, apply the stricter research and review path until scope is clarified.

## Required context

Before producing prescriptive YMYL content, establish:

- Audience and intended use.
- Country, jurisdiction, and any relevant regulator or professional standard.
- `as_of` date and volatility of the governing information.
- Whether the article is general information, decision support, or professional advice.
- Available official or primary sources.
- The qualified reviewer required before publication.

If jurisdiction or intended use materially changes the answer and cannot be inferred safely, stop and ask a focused question.

## Evidence and writing rules

- Use current official, regulatory, primary clinical, or other domain-appropriate authoritative sources for load-bearing claims.
- Verify every material eligibility rule, threshold, risk, contraindication, exception, deadline, and recommended action.
- Separate established evidence, professional consensus, first-party information, and inference.
- State material uncertainty, limitations, alternatives, and risks in language appropriate to the audience.
- Do not diagnose an individual, prescribe treatment, guarantee an outcome, or present generalized information as personalized advice.
- Do not fabricate credentials, expert review, testing, patient or client experience, case outcomes, or regulatory approval.
- Verify bylines and credentials before using them as trust signals.
- Do not use testimonials as proof of safety, efficacy, legality, or expected financial results.
- Assign refresh triggers based on regulatory, clinical, product, or market volatility.
- Protect personal and sensitive information; include only data authorized for the article.

A disclaimer does not cure weak sourcing, an unsafe recommendation, missing exceptions, or absent expert review.

## Expert-review requirement

YMYL content cannot receive `publish-package-ready` without a qualified human reviewer appropriate to the topic and jurisdiction. Record:

```yaml
contract_version: review-binding-v1
run_id:
review_type: ymyl
review_required: true
status: pending | approved | needs-changes | rejected
reviewer:
credentials:
scope:
jurisdiction:
requested_at: # pending / needs-changes / rejected
reviewed_at:
sections_reviewed:
claims_requiring_review:
claims_reviewed: # required for approved; exact claim IDs
findings:
artifact_hashes:
  intake.json:
  drafts/final.md:
  claims.jsonl:
  research/sources.jsonl:
```

Use `requested_at` for a non-approved request record and `reviewed_at` for a
passed approval; both are timezone-aware. Do not fill an approval timestamp to
make a pending request look complete.

AI review, a generic editor, an author biography, or a disclaimer does not satisfy this requirement.

If qualified review is unavailable:

- Research and draft may continue when doing so is safe.
- Use `needs-expert-review` when all other content gates pass; otherwise retain `draft-only` or `needs-evidence` as applicable.
- Identify the exact canonical claim IDs the expert must review. Every ID must
  exist in the bound `claims.jsonl`, and the pending scope covers every
  load-bearing and supporting claim; free-form labels or invented IDs do not
  satisfy the handoff gate.
- Write the pending `reviews/ymyl.json` record with `review_required: true`, the topic and jurisdictional `scope`, and a non-empty `claims_requiring_review` list. Missing review evidence is not a review state.
- Bind even a pending request to the current run, current intake, and the three content artifacts with `review-binding-v1`, their SHA-256 values, and a timezone-aware `requested_at`. This defines exactly what the expert is being asked to review; it does not imply approval.
- Approved review records use typed, substantive strings for reviewer identity, credentials, scope, and jurisdiction. `sections_reviewed` must resolve to actual reader-visible headings or named claim locations in the bound draft, and `claims_reviewed` must contain every material claim ID in the bound ledger; invented sections, unknown IDs, or partial coverage do not pass. Minimum lengths require a meaningful number of Unicode letters or numbers in addition to visible length, so whitespace, zero-width controls, combining-only text, punctuation/symbol padding, or one real character padded with non-semantic characters cannot become qualification evidence. Truthy booleans, null list items, placeholders, and one-character tokens do not pass.
- At `content-ready`, an approved YMYL record hashes `intake.json`, `drafts/final.md`, `claims.jsonl`, and `research/sources.jsonl`. At `publish-package-ready` and above, approval additionally hashes the final `publish/publish-manifest.json`; package-level approval therefore follows package creation and precedes technical review and publication. Any change to a bound artifact reopens review.
- Do not publish automatically or describe the content as approved.

If current authoritative research is unavailable, limit output to a research plan, neutral outline, or clearly incomplete draft. Do not fill gaps from model memory.

## YMYL gates

| Finding | Severity |
|---|---|
| Fabricated authority, approval, credential, study, result, or source | `P0` |
| Advice likely to create material harm or unlawful action | `P0` |
| Missing qualified review for a package-ready claim | `P0` for publication readiness |
| Missing jurisdiction or `as_of` date where it changes the answer | `P1` |
| Material exception, risk, or uncertainty omitted | `P1`, or `P0` when omission creates likely harm |
| Reliance on a secondary source when a current primary authority is reasonably available | `P1` for a load-bearing claim |
| Analytics or optional supporting visual unavailable | `P2` |

## Publication and maintenance

- Default `publish_permission` remains `false`.
- Never auto-publish YMYL content.
- Preserve the source ledger, claim ledger, expert-review record, and article version associated with the approval.
- After publication, verify the live text matches the reviewed version.
- Reopen expert review when a material claim, recommendation, jurisdiction, source, or regulatory basis changes.

The review hash is an integrity link, not a digital signature or proof that the
named person has the stated credentials. Credential, scope, jurisdiction, and
reviewer identity evidence must be checked independently. Deterministic
validation also cannot prove medical, legal, financial, or safety truth.
