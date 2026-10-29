# Adaptive Solar entwickeln und prüfen

Stand: 29.10.2026. [Repositoryregeln](../../AGENTS.md), [Verträge](../technik/implementation-contract.md)
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
.venv/bin/python -m pytest -q --junitxml=artifacts/tests.xml \
    --cov=custom_components.adaptive_solar --cov-branch \
    --cov-report=term-missing:skip-covered \
    --cov-report=xml:artifacts/coverage.xml --cov-report=json:artifacts/coverage.json
```

Das ist derselbe Installationsumfang wie in [CI](../../.github/workflows/tests.yml).
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

`pytest-cov` gehört zum Testextra. Die Coveragekonfiguration in `pyproject.toml`
erfasst sämtliche Komponentenmodule einschließlich des HA-unabhängigen Kerns;
sie lässt keine neuen Module aus dem Scope. Der Gesamtwert kombiniert ausgeführte
Statements und Zweige. Das Gate verlangt zunächst 90,00 %, ohne feste Testanzahl.
XML und JSON berichten zusätzlich die getrennten Zeilen-/Zweigzahlen; CI lädt
JUnit- und Coverageberichte auch bei einem fehlgeschlagenen Lauf als Artefakte hoch.
Ein Coveragewert beweist weder korrekte fachliche Ergebnisse noch Forecastgüte.
Die endgültige Schwelle und der gemessene Entwicklungsstand müssen am stabilen
Quellstand gemeinsam abgeglichen werden; Paralleländerungen während eines Laufs
sind kein belastbarer Baselinebeleg.

Die native HA-Konfiguration nutzt pro Test die Pluginfixture `hass_tmp_config_dir`
über `hass_config_dir`. Echte Storeprüfungen schreiben so ausschließlich in die
temporäre Testkonfiguration und verändern keine installierten Pluginfixtures.
Coverage-Rohdaten liegen ebenfalls ignoriert unter `artifacts/`.
Für `adaptive_solar`-Stores schreibt die Testfixture native Dateien zusätzlich
zum Speicherabbild des HA-Testplugins. Restorefixtures legen vollständige echte
Store-Envelopes an; sie ersetzen das Laden nicht durch ein vorgefertigtes
`async_load`-Ergebnis. Verzögerte Datenfunktionen werden dabei genau einmal
ausgewertet, bevor derselbe eingefrorene Payload auf Platte und ins Speicherabbild
geht. Damit bleiben Korruptionsschutz, echte Schreibfehler, Rücklesen und
Migrationen unter den normalen Setup-/Close-Gates prüfbar.

## 2. Änderungen und Beiträge

Die HA-Schicht und ihre Servicetests importieren den Validator direkt als
`probatio as vol`. Die Gerätebereinigung liest die einzelne Eigentümerbindung
über `DeviceEntry.config_entry_id`; Geräte werden weiterhin nur bei passender
Integrationskennung und ohne verbliebene Entitäten entfernt. Der Referenzdienst
setzt `retrieved_at` direkt nach der Providerantwort vor deren Validierung.
Ohne Antwort erhält auch der Fehlerstatus einen eigenen UTC-Zeitstempel.

Vor Änderungen aktuellen Code und zugehörige Dokumentation lesen. Fehlerfälle mit
synthetischen Anlagen oder gemockten Providerantworten reproduzieren; echte private
Standorte/Entitäten nicht in Testfixtures übernehmen. Bei Prognoseänderungen Zeit-,
Mess- und Ausgabemessgrenzen erhalten; sinnvolle Verhaltenstests für Lücken, beide
DST-Wechsel und as-of-Verfügbarkeit ergänzen. Bei reinen Textkorrekturen genügen
Link-/Inhalts-/Darstellungsprüfungen.

Die neuen Datenverträge sind nach Themen getrennt:
[Messkontinuität und Endpunktfenster](../technik/measurement-learning.md),
[früher Bias ausschließlich im Shadow](../technik/early-bias-shadow.md),
[Physik-/Schatten-/Nowcastkandidaten](../technik/physics-learning-options.md),
[Fit-/Wetterfehler und Ressourcen](../technik/forecast-resilience.md) und
[prospektive Modellvergleichsarchive](../technik/model-comparison-archive.md).
Die bestehenden Residualgates bleiben aktiv; ein Kandidat oder größeres Archiv
ersetzt keine eingefrorene prospektive Vergleichsmessung.

Pull Requests beschreiben Problem, resultierendes Verhalten und Prüfungen. Zu
Versionsänderungen `pyproject.toml`, HA-Manifest und Releasebeschreibung abgleichen;
es gibt keine zweite unbenutzte Runtimeversionskonstante. Mindestversion in HACS
und die dokumentierte Testmatrix gemeinsam prüfen. Dokumentation auf Deutsch,
Codebezeichner und etablierte technische Begriffe beibehalten. Eigenständige fremde
Lizenzen erhalten; Projektlizenz ist [GPL-3.0-only](../../LICENSE).

## 3. Veröffentlichung und Nachweise

Der seit 0.2.16 veröffentlichte Archivzweig enthält
[`archive.py`, Wetter-/Messaufnahme und Replay](../archiv/archivbetrieb.md).
Für Änderungen daran sind Roundtrips, Abbruch-/Wiederanlauf, vollständige
Referenzen, Pin-/Retentionsregeln, native HA-Autorisierung, beide DST-Wechsel
und kausale Ensembleauswertung relevant. Die vollständige Suite enthält diese
Verhaltenstests; Live-Providerstichproben sind zusätzliche Schnittstellenproben
und keine Prognosegüteprüfung.

Paketbau, Installation, nativer Core-Import, qualifizierter ML-Fit und reale
Prognosegüte sind unterschiedliche Nachweise. Neue Tests oder Dokuänderungen
verlängern einen früheren Grok- oder Codex-Receipt nicht automatisch auf den neuen Quellstand.
Der [Reviewablauf](validierung.md#4-lokale-prüfung-und-review) in `scripts/review.py` unterstützt Grok 4.7
(`--reviewer grok`, Standard) sowie alternativ Codex mit
GPT-6.1-Sol und Effort `high` (`--reviewer codex`) und
benötigt eine Nutzerfreigabe für externe Übertragung. Für öffentliche
Repositoryquellen und nötige Grok-Nachreviews liegt seit 27.10.2026 die
dauerhafte [Freigabe in AGENTS.md](../../AGENTS.md#dauerhafte-grok-transferfreigabe)
vor; keine erneute Nachfrage je Payload-Hash. Private Daten und andere Empfänger
sind nicht umfasst. `--prepare-only` prüft lokal den
Exportumfang. Neue Codex-Aufrufe binden 800.000 angeforderte Kontexttokens in
Receipt und beiden Kontextflags; Grok bleibt bei 500.000. Nur die bekannten
vollständig gebundenen Codex-Referenzvarianten 500k/800k bleiben zulässig. Das
angeforderte Budget ist keine garantierte native Effektivkapazität und ersetzt
keinen vollständigen Audit ohne Compaction; [Details](validierung.md#4-lokale-prüfung-und-review).
Der aktuelle vollständige Scope benötigt dabei ausdrücklich
`--transport chunks`, da er die unveränderte Single-Bytegrenze überschreitet;
die Vorbereitung ist kein Kontext- oder Reviewnachweis. Geänderte Forschung kann
nicht über alte Forschungs-SHAs geerbt werden.

Vor Veröffentlichung versionierte Dateien auf private Daten prüfen, Paketinhalt und
Lizenzmitlieferung kontrollieren und abgeschlossene CI abwarten. Rohbelege können
privat bleiben; öffentliche Statusangaben nennen Version, Scope, Umgebung und Grenzen.
Ein fremder Betreiber muss die Anleitung allein aus öffentlichen Dateien verstehen
können. Reale Vergleichsaufnahmen folgen dem vorher eingefrorenen
[Messplan](validierung.md), keine nachträgliche Auswahl nur guter Tage.
