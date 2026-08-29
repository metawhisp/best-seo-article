# New, Rewrite, and Refresh Modes

Select one primary mode for each run. Apply the common evidence and editorial contracts in every mode. Recommend a mode change when the evidence supports it, but do not switch the user's requested operation silently.

## Mode selection

| Situation | Recommended mode |
|---|---|
| No suitable page exists for the target user job | `new` |
| An existing page targets the right opportunity but needs substantial structural, evidence, or positioning work | `rewrite` |
| An existing page remains useful but contains stale facts, links, product details, examples, or search-intent assumptions | `refresh` |
| A proposed new page would materially overlap an existing page | Recommend `rewrite` or `refresh`; do not create a duplicate without an explicit decision. |

## Shared workflow

Every mode must:

1. Normalize the user job, audience, locale, business goal, and evidence constraints.
2. Inspect relevant existing site coverage when access is available.
3. Research current search intent and authoritative evidence.
4. Build an evidence-bound brief and planned claim set.
5. Draft without inventing experience, product facts, quotes, results, or examples presented as real.
6. Run independent claim, editorial, SEO, and applicable technical checks.
7. Report the resulting status, open warnings, and unverified assumptions.

## `new`

Goal: create a distinct page that satisfies an unmet user job.

Required work:

- Check whether the site already has a page serving the same intent.
- Distinguish the proposed page by user job, audience, format, product stage, locale, or evidence contribution.
- Use current search results to understand intent and expected task shape, not to copy a consensus outline.
- Identify the page's verifiable information gain: first-party evidence, original analysis, a useful synthesis, a worked example, or clearer decision support.
- Define internal-link entry and exit points when a site corpus is available.

Block clean `publish-package-ready` when the proposed page is an unresolved duplicate or would create material cannibalization. The user may still request a standalone exploratory draft, which remains `draft-only`.

## `rewrite`

Goal: make substantial improvements while preserving valuable existing equity and truthful content.

Capture a baseline before editing:

- Original content, URL, title, headings, metadata, structured data, links, and assets.
- Publication and modification dates.
- Ranking queries, landing-page metrics, conversions, and internal-link relationships when available.
- Unique examples, first-party evidence, attributed quotes, and sections the user marks as protected.

Create a change plan that labels each major section as `keep`, `repair`, `expand`, `merge`, `move`, or `remove`, with a reason and evidence. Do not change the URL without explicit approval and a redirect plan.

Represent that redirect plan as a structured `redirect_plan` object in `diff-report.json`:

```json
{
  "source_url": "https://example.com/old-path",
  "target_url": "https://example.com/new-path",
  "status_code": 301,
  "owner": "Web platform team"
}
```

`source_url` must match the immutable baseline URL, `target_url` must match the manifest destination URL, `status_code` must be `301` or `308`, and `owner` must name the responsible person or team with substantive, control-free text. A boolean, prose string, invisible/control-only owner, or unbound plan is not approval and does not satisfy the gate.

Record the protected-element review in `manifest.json`. Set `protected.reviewed=true`, give a substantive `rationale`, and list headings and links that must survive. If nothing is worth preserving, set `empty_selection_approved=true` explicitly and explain why; empty arrays by themselves are not evidence that the baseline was reviewed.

A rewrite may alter structure, angle, and language, but it must not:

- Remove a high-value or protected section without documenting the tradeoff.
- Replace verified specifics with generic prose.
- Manufacture first-hand experience or customer evidence.
- Reset dates merely to appear fresh.
- Hide changed factual claims from the final diff.

The final handoff must include a semantic diff covering claims, headings, links, metadata, and removed material, not only a line-by-line text diff.

## `refresh`

Goal: restore current accuracy and usefulness with the smallest justified change set.

Refresh work includes:

- Revalidate volatile claims, dates, prices, product behavior, regulations, named roles, and external links.
- Recheck whether search intent or terminology materially changed.
- Replace or qualify stale evidence and retain relevant historical context.
- Repair examples, screenshots, UI steps, links, and schema affected by substantive changes.
- Review nearby sections when one corrected fact changes their conclusions.

Do not turn a refresh into a full rewrite for stylistic preference. Preserve the URL, successful structure, useful language, and existing link relationships unless evidence supports a change.

Change `dateModified` only after a substantive content update. Record every `material_changes` item as a substantive, control-free string; truthy booleans, objects, nulls, or invisible text are not change evidence. A new date is not a substitute for new verification.

## Mode-specific artifacts

| Artifact | `new` | `rewrite` | `refresh` |
|---|---:|---:|---:|
| Opportunity and overlap analysis | Required when site access exists | Recommended | Recommended |
| Original-page snapshot | Not applicable | Required | Required |
| Performance baseline | Optional | Strongly recommended | Strongly recommended |
| Protected-elements list | Not applicable; record an explicitly reviewed empty selection | Required | Required |
| Claim and source ledger | Required | Required | Required |
| Semantic diff | Not applicable | Required | Required |
| Update rationale | Brief | Detailed | Detailed and section-specific |

If a baseline capability is unavailable, continue only when safe, state what could not be protected or measured, and lower the readiness status accordingly.
