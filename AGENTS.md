# Repository Guidelines

## Project Structure & Module Organization

This repository contains German-language research on solar forecasting, emphasizing resources free for private use. All content currently lives in root-level Markdown files:

- `solar-prognose-ml-recherche.md`: comprehensive overview and references.
- `solar-prognosemodelle-zusammenfassung.md`: forecasting tools and service comparison.
- `solar_ml_research.md`: machine-learning approaches.
- `ensemble_hybrid_solar_forecasting.md`: ensembles and hybrid models.
- `solarprognose_datenquellen_feature_engineering.md`: data sources and features.
- `solarstrahlungsprognose_recherche.md`: physical and NWP-based models.

There are no application source, test, or asset directories. Embedded code illustrates research concepts; it is not a packaged implementation.

## Build, Test, and Development Commands

No build system, dependency manifest, local application runner, or automated test suite is configured. Documentation edits need no dependency installation.

- `rg --files -g '*.md'`: list Markdown documents.
- `rg -n '^#{1,3} ' *.md`: inspect document headings.
- `rg -n 'Open-Meteo|pvlib' *.md`: locate related claims before editing.

Preview edited documents in a Markdown viewer to check tables, equations, code blocks, and navigation.

## Writing Style & Naming Conventions

Write research content in German and retain established technical terms. Use one descriptive H1, hierarchical headings, short paragraphs, and comparison tables where helpful. Follow each document's existing section numbering and update its table of contents when headings change.

Use descriptive lowercase `.md` filenames; existing names mix hyphens and underscores, so avoid cosmetic renames. Keep fenced code blocks language-tagged and use four-space indentation for Python examples. No formatter or linter is configured.

## Validation Guidelines

There is no test framework or coverage threshold. Check changed claims against primary sources, verify links and heading anchors, and keep units, forecast horizons, datasets, and metrics explicit. Distinguish published results from local measurements and recommendations. Recheck pricing, API limits, and licenses before changing availability claims; record the research date. Reconcile overlapping summaries when conclusions change.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so no commit convention can be confirmed. Suggested messages are concise and scoped, for example `docs: clarify forecast evaluation metrics`.

For review, describe changed documents, rationale, supporting sources, and validation performed. Link relevant issues when available; include screenshots only for rendering changes.

## Agent & Configuration Guidance

Use shared-memory scope `prognosemodelle`. Before substantial work, call `memory_search_with_global` and inspect current files; repository evidence takes precedence. Store only verified, durable decisions, avoiding duplicates. Never include credentials or private installation data in research examples or memories.
