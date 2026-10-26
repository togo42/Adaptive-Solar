# Repository Guidelines

## Project Structure & Module Organization

This repository contains German-language research on solar forecasting, emphasizing resources free for private use, and the Adaptive Solar HA integration. The original research lives in root-level Markdown files:

- `solar-prognose-ml-recherche.md`: comprehensive overview and references.
- `solar-prognosemodelle-zusammenfassung.md`: forecasting tools and service comparison.
- `solar_ml_research.md`: machine-learning approaches.
- `ensemble_hybrid_solar_forecasting.md`: ensembles and hybrid models.
- `solarprognose_datenquellen_feature_engineering.md`: data sources and features.
- `solarstrahlungsprognose_recherche.md`: physical and NWP-based models.

The research documents remain in the root. The deployable HA integration lives in
`custom_components/adaptive_solar/`; its HA-independent physics, learning and
evaluation modules live in `core/`. Tests are in `tests/`, local command-line
helpers in `scripts/`, synthetic examples in `examples/`, and implementation and
validation documentation in `docs/`. `README.md` is the implementation entrypoint.
Embedded code in the older research documents still illustrates concepts and is
not itself the implementation.

## Build, Test, and Development Commands

A Python package and pytest suite are configured in `pyproject.toml`. Documentation
edits need no dependency installation. For implementation work use a local venv:

- `python3 -m venv .venv`
- `.venv/bin/python -m pip install '.[test,ha-test]' 'pvlib==0.16.1' 'scikit-learn==1.9.1'`: match the current HA manifest; see `docs/entwicklung.md` for automatic pin extraction.
- `.venv/bin/python -m pip check`
- `.venv/bin/python -m pytest -q`: includes tests with actual HA Core.
- `.venv/bin/ruff check custom_components tests scripts`
- `.venv/bin/python scripts/forecast.py --help`: explicit synthetic or live weather.
- `.venv/bin/python scripts/evaluate.py --help`: paired archived forecast evaluation.
- `.venv/bin/python scripts/capture_ha.py --help`: explicit read-only HA capture using private mappings.
- `.venv/bin/python scripts/capture_actuals.py --help`: Recorder change-energy capture with separate quality evidence.
- `.venv/bin/python scripts/review_grok.py --prepare-only`: freeze a local review package.

- `rg --files -g '*.md'`: list Markdown documents.
- `rg -n '^#{1,3} ' *.md`: inspect document headings.
- `rg -n 'Open-Meteo|pvlib' *.md`: locate related claims before editing.

Preview edited documents in a Markdown viewer to check tables, equations, code blocks, and navigation.

## Writing Style & Naming Conventions

Write research content in German and retain established technical terms. Use one descriptive H1, hierarchical headings, short paragraphs, and comparison tables where helpful. Follow each document's existing section numbering and update its table of contents when headings change.

Use descriptive lowercase `.md` filenames; existing names mix hyphens and underscores, so avoid cosmetic renames. Keep fenced code blocks language-tagged and use four-space indentation for Python examples. Ruff is configured for Python checks; no automatic Markdown formatter is configured.

## Validation Guidelines

Use meaningful behavioral pytest tests for forecast and HA changes. Do not treat
skipped HA tests as HA validation. Keep target intervals, forecast issue times,
actual measurement availability, units and curtailment explicit. Preserve missing
data, train only on prior archived inputs, and test both DST transitions. A passing
test suite or review is not evidence of superiority over other integrations.

Check changed research claims against primary sources, verify links and heading
anchors, and distinguish published results from local measurements and
recommendations. Recheck pricing, API limits and licenses before changing
availability claims; record the research date and reconcile overlapping summaries.

## Commit & Pull Request Guidelines

Use concise, scoped commit messages, for example
`docs: clarify forecast evaluation metrics`.

Commit relevant changes after appropriate validation, with one commit per
coherent change. Include its accompanying tests and documentation; preserve
unrelated work. Do not leave completed repository changes uncommitted. Stage
explicit file paths and keep private data, credentials and runtime artifacts
out of Git.

For review, describe changed documents, rationale, supporting sources, and validation performed. Link relevant issues when available; include screenshots only for rendering changes.

## Agent & Configuration Guidance

Use shared-memory scope `prognosemodelle`. Before substantial work, call `memory_search_with_global` and inspect current files; repository evidence takes precedence. Store only verified, durable decisions, avoiding duplicates. Never include credentials or private installation data in research examples or memories.

Keep runtime data and private mappings under ignored `data/`, generated artifacts
under `artifacts/`, and raw review payloads under `reviews/private/`. The requested
external reviewer is Grok 4.7; follow the hash-bound procedure in
`docs/validierung.md`, and respect external transfer approval. Creating or testing
the integration does not authorize modifying productive HA settings.
