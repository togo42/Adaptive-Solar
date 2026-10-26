# Adaptive Solar entwickeln und prüfen

Stand: 26.10.2026. [Repositoryregeln](../AGENTS.md), [Verträge](implementation-contract.md)
und [Validierungsgrenzen](validierung.md) ergänzen diesen Einstieg.

## 1. Prüfumgebung reproduzieren

Python 3.14 für native HA-Tests verwenden; Python ab 3.13 gilt für den HA-freien Kern.
Eine frische Umgebung verhindert Altlasten im HA-Testplugin. Reguläre Paketinstallation
verwenden: PEP660-Editable kann HAs Namespace-Erkennung stören.

```bash
python3.14 -m venv .venv
.venv/bin/python - <<'PY'
import json
from pathlib import Path
import subprocess
import sys

requirements = json.loads(Path("custom_components/adaptive_solar/manifest.json").read_text())["requirements"]
subprocess.check_call([sys.executable, "-m", "pip", "install", ".[test,ha-test]", *requirements])
PY
.venv/bin/python -m pip check
.venv/bin/ruff check custom_components tests scripts
.venv/bin/python -m pytest -q --junitxml=artifacts/tests.xml
```

Das ist derselbe Installationsumfang wie in [CI](../.github/workflows/tests.yml).
Das Extra `ha-test` bindet aktuell Core 2026.10.4 und Plugin 0.13.375; das Manifest
bindet die HA-Runtimepins. Die breiteren normalen Paketabhängigkeiten allein sind
kein Nachweis dieser konkreten Laufzeit. Andere Matrixarme benötigen eigene Venvs:

| Core | Testplugin |
| --- | --- |
| 2026.10.2 | 0.13.373 |
| 2026.10.3 | 0.13.374 |
| 2026.10.4 | 0.13.375 |

Für Core .2 wurde NumPy 2.3.2 mit Pandas 2.3.3 verwendet. Matrixprüfungen jeweils
mit passender expliziter Core-/Pluginauflösung und `pip check` beginnen. Ein einzelner
Lauf prüft seine tatsächliche Umgebung, nicht automatisch alle drei Matrixarme.

## 2. Änderungen und Beiträge

Vor Änderungen aktuellen Code und zugehörige Dokumentation lesen. Fehlerfälle mit
synthetischen Anlagen oder gemockten Providerantworten reproduzieren; echte private
Standorte/Entitäten nicht in Testfixtures übernehmen. Bei Prognoseänderungen Zeit-,
Mess- und Ausgabemessgrenzen erhalten; sinnvolle Verhaltenstests für Lücken, beide
DST-Wechsel und as-of-Verfügbarkeit ergänzen. Bei reinen Textkorrekturen genügen
Link-/Inhalts-/Darstellungsprüfungen.

Pull Requests beschreiben Problem, resultierendes Verhalten und Prüfungen. Zu
Versionsänderungen `pyproject.toml`, HA-Manifest und Releasebeschreibung abgleichen;
es gibt keine zweite unbenutzte Runtimeversionskonstante. Mindestversion in HACS
und die dokumentierte Testmatrix gemeinsam prüfen. Dokumentation auf Deutsch,
Codebezeichner und etablierte technische Begriffe beibehalten. Eigenständige fremde
Lizenzen erhalten; Projektlizenz ist [GPL-3.0-only](../LICENSE).

## 3. Veröffentlichung und Nachweise

Paketbau, Installation, nativer Core-Import, qualifizierter ML-Fit und reale
Prognosegüte sind unterschiedliche Nachweise. Neue Tests oder Dokuänderungen
verlängern einen früheren Grok- oder Codex-Receipt nicht automatisch auf den neuen Quellstand.
Der [Reviewablauf](validierung.md#4-lokale-prüfung-und-review) in `scripts/review.py` unterstützt Grok 4.7
(`--reviewer grok`, Standard) sowie alternativ Codex mit
GPT-6.1-Sol und Effort `high` (`--reviewer codex`) und
benötigt eine gesonderte Freigabe für externe Übertragung. `--prepare-only` prüft lokal den
Exportumfang; geänderte Forschung kann nicht über alte Forschungs-SHAs geerbt werden.

Vor Veröffentlichung versionierte Dateien auf private Daten prüfen, Paketinhalt und
Lizenzmitlieferung kontrollieren und abgeschlossene CI abwarten. Rohbelege können
privat bleiben; öffentliche Statusangaben nennen Version, Scope, Umgebung und Grenzen.
Ein fremder Betreiber muss die Anleitung allein aus öffentlichen Dateien verstehen
können. Reale Vergleichsaufnahmen folgen dem vorher eingefrorenen
[Messplan](validierung.md), keine nachträgliche Auswahl nur guter Tage.
