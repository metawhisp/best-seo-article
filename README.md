# Best SEO Article

An evidence-grounded workflow for researching, writing, rewriting, refreshing,
verifying, and packaging one SEO article. It produces a defensible article
package rather than a keyword-stuffed draft or a ranking promise.

The skill is portable: copy this complete directory into a supported Agent
Skills location. For Claude Code in one repository, use:

```text
.claude/skills/best-seo-article/
```

Then invoke `/best-seo-article`, or let the host select it when its description
matches the request.

## What it enforces

- Current SERP research is kept separate from factual sources.
- Query choice, search intent, competitor gap, and source plan are recorded as
  reviewable decisions rather than inferred from a keyword score.
- `content-ready` requires an article-quality gate: opened relevant SERP pages
  with observed format/length/gaps, a mapped reader path, information gain,
  an evidence-backed content shape, a reasoned visual/data decision, and—at
  Full competitive depth—a demonstrated reader advantage rather than a sourced
  summary alone.
- A passed editorial review must assess intent, truth, information gain,
  utility, clarity, and conversion; a handoff cannot disagree with the run's
  actual status.
- Material claims have a source and a verification trail.
- Keyword volume, difficulty, pricing, product capabilities, reviews, and
  publication state are never invented.
- Tables, charts, images, screenshots, and diagrams carry the required data,
  provenance, rights, and accessibility checks.
- Publication and post-publication verification require explicit permission.
- A generated file, CMS response, or checksum is never misrepresented as a
  ranking, a live page, or a proof of factual accuracy.

## Contents

- `SKILL.md` — the entry point and operating contract.
- `references/` — mode-specific research, editorial, media, publishing, and
  measurement rules, including the Lite/Full article methodology.
- `examples/` — a concise annotated run walkthrough; use it to understand the
  artifact order, never as evidence for a new article.
- `scripts/` — offline validators and a run initializer.
- `schemas/` — JSON Schema contracts for run artifacts.
- `evals/` — adversarial and regression tests.

## Test before using or changing it

Run from this directory:

```bash
python3 -m unittest discover -s evals -p 'test_*.py' -v
python3 evals/run_structural_evals.py
```

The first command exercises expected and unsafe inputs. The second validates
the artifact contracts, status transitions, review bindings, publication
package checks, and media protections.

For a quick metadata check, use the skill validator supplied by the host
environment, when available.

## Typical workflow

1. Start a run and record scope, permissions, locale, destination, and risk.
2. Record available providers or fallbacks without exposing credentials.
3. Select the query, capture current intent, document a real gap, and build a
   source plan before drafting.
4. Build the evidence-bound brief, then write the article and optional
   visual/data plan.
5. Run independent claim, editorial, media, technical, and qualified review
   where required.
6. Repair findings, package the final deliverables, and validate the run.
7. Publish only with recorded permission; verify the live URL separately.

See `SKILL.md` for routing and `references/` for the detailed contracts.
