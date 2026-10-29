# Repository Guidelines

## Project Structure & Module Organization

This repository contains the Adaptive Solar HA integration and German-language
research on solar forecasting. Documentation starts at `docs/README.md`:

- `docs/recherche/solar-prognose-ml-recherche.md`: comprehensive overview and references.
- `docs/recherche/solar-prognosemodelle-zusammenfassung.md`: forecasting tools and service comparison.
- `docs/recherche/solar_ml_research.md`: machine-learning approaches.
- `docs/recherche/ensemble_hybrid_solar_forecasting.md`: ensembles and hybrid models.
- `docs/recherche/solarprognose_datenquellen_feature_engineering.md`: data sources and features.
- `docs/recherche/solarstrahlungsprognose_recherche.md`: physical and NWP-based models.

Research documents live in `docs/recherche/`, user guides in `docs/anwendung/`,
data contracts in `docs/technik/`, reusable archive operations in `docs/archiv/`,
development and validation guides in `docs/entwicklung/`, release notes in
`docs/releases/`, and historical implementation plans in `docs/historie/`.
Private installation logs and operator-specific evidence belong under ignored
`data/docs/betrieb/`; public documentation must not require these files.
Before removing a worktree, preserve its private documentation in the main
checkout's ignored data directory. Record the archive location and source commit
in project shared memory without copying private operational contents there.
The deployable HA integration lives in `custom_components/adaptive_solar/`;
its HA-independent physics, learning and evaluation modules live in
`custom_components/adaptive_solar/core/`. Tests are in `tests/`, local command-line
helpers in `scripts/`, and synthetic examples in `examples/`.
`README.md` is the implementation entrypoint.
Embedded code in the older research documents still illustrates concepts and is
not itself the implementation.

## Build, Test, and Development Commands

A Python package and pytest suite are configured in `pyproject.toml`. Documentation
edits need no dependency installation. For implementation work use a local venv:

- `python3.14 -m venv .venv`: use Python 3.14 for native HA tests.
- `.venv/bin/python -m pip install '.[test,ha-test]' 'pvlib==0.16.1' 'scikit-learn==1.9.1'`: match the current HA manifest; see `docs/entwicklung/entwicklung.md` for automatic pin extraction.
- `.venv/bin/python -m pip check`
- `.venv/bin/python -m pytest -q`: includes tests with actual HA Core.
- `.venv/bin/ruff check custom_components tests scripts`
- `.venv/bin/python scripts/forecast.py --help`: explicit synthetic or live weather.
- `.venv/bin/python scripts/evaluate.py --help`: paired archived forecast evaluation.
- `.venv/bin/python scripts/capture_ha.py --help`: explicit read-only HA capture using private mappings.
- `.venv/bin/python scripts/capture_actuals.py --help`: Recorder change-energy capture with separate quality evidence.
- `.venv/bin/python scripts/review.py --transport chunks --prepare-only`: freeze a local review package for the current full source scope (default Grok 4.7; pass `--reviewer codex` for Codex GPT-6.1-Sol). The default `single` transport rejects payloads above 1,250,000 bytes; see `docs/entwicklung/validierung.md` for scope and context-audit requirements.

- `rg --files -g '*.md'`: list Markdown documents.
- `rg -n '^#{1,3} ' README.md docs -g '*.md'`: inspect document headings.
- `rg -n 'Open-Meteo|pvlib' README.md docs -g '*.md'`: locate related claims before editing.

Preview edited documents in a Markdown viewer to check tables, equations, code blocks, and navigation.

## Writing Style & Naming Conventions

Write research content in German and retain established technical terms. Use one descriptive H1, hierarchical headings, short paragraphs, and comparison tables where helpful. Follow each document's existing section numbering and update its table of contents when headings change.

Use descriptive lowercase `.md` filenames; existing names mix hyphens and underscores, so avoid cosmetic renames. Keep fenced code blocks language-tagged and use four-space indentation for Python examples. Ruff is configured for Python checks; no automatic Markdown formatter is configured.

## Documentation Required for Every Change

Bei jeder Änderung müssen die betroffenen Dokumentationsstellen geprüft und im
selben Arbeitsauftrag auf den resultierenden Stand gebracht werden. Das gilt für
Code, Konfiguration, Abhängigkeiten, CLI-Befehle und Entwicklungs-/Reviewabläufe.
Insbesondere README, Anwender- und Installationsanleitungen, Datenverträge und
aktuelle Statusangaben müssen mit der Implementierung übereinstimmen; historische
Nachweise bleiben ausdrücklich als historisch gekennzeichnet.

Eine Änderung ist erst abgeschlossen, wenn die erforderlichen Dokuaktualisierungen
mitgeprüft und zusammen mit der Änderung oder in einem unmittelbar zugehörigen
Dokumentationscommit eingecheckt sind. Falls keine veröffentlichte Beschreibung
betroffen ist, im Commit- oder PR-Text kurz begründen, warum keine Textanpassung
nötig war. Keine rein kosmetische Dokuänderung als Ersatz für diesen Abgleich.

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
external reviewer is Grok 4.7 (`grok-4.7`, effort `high`) or alternatively Codex
with GPT-6.1-Sol (`gpt-6.1-sol`, effort `high`); follow the hash-bound procedure in
`docs/entwicklung/validierung.md`, and respect external transfer approval. Creating or testing
the integration does not authorize modifying productive HA settings.

### Dauerhafte Grok-Transferfreigabe

Explizite Nutzerfreigabe vom 27.10.2026: Der öffentliche Quellumfang dieses
Repositories darf für Reviews und nötige Nachreviews nach Befundkorrekturen
an Grok 4.7/high über den konfigurierten Grok-CLI-Reviewhelfer übertragen werden.
Das gilt auch für künftige Änderungen dieses öffentlichen Projektumfangs;
keine erneute Einzelfreigabe je Payload-Hash anfordern. Private
Installationsdaten, Zugangsdaten, Secrets, sachfremde Daten und andere Empfänger
sind nicht umfasst. Hashbindung, vollständiger Kontextaudit und aktiver
Self-Review bleiben Pflicht. Diese Transferfreigabe allein autorisiert keine
produktiven HA-Änderungen; dafür gilt der jeweils konkrete Nutzerauftrag.
