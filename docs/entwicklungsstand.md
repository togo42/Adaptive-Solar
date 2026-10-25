# Entwicklungsstand und offene Nachweise

Stand: 25.10.2026, Betriebsnachweise bis09:24 UTC. **0.2.7 installiert; drei freigegebene Entries liefern Prognosen.** Produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch drei Subagenten mit hohem Aufwand.

Je **752 Tests bestanden**, null übersprungen: HA2026.10.2/Plugin0.13.373 und HA2026.10.3/Plugin0.13.374, Python3.14.4, normale Wheel-Installation. JUnit: `artifacts/tests-0.2.7-ha-2026.10.2.xml`/`.3.xml`. Sieben Kernmodule unverändert zu0.2.6; dessen231 Musl-Kerntests sind über `artifacts/core-compatibility-0.2.7.json` gebunden, kein neuer Musl-Lauf. Je73 gezielte AC-/DC-/Filtertests ergänzen dies. Ruff/Dependency-/Paket-/Importprüfungen bestanden; GitHub-Workflow hier nicht ausgeführt. Historische Details liegen im lokalen Archiv `artifacts/releases/0.2.7-reviewed/source/docs/entwicklungsstand.md`.

**Lokaler Korrekturstand0.2.8:** je758 Tests bestanden, null übersprungen, HA2026.10.2 in77,74s und .3 in77,76s. JUnit: `artifacts/tests-0.2.8-ha-2026.10.2.xml`/`.3.xml`. Enger As-of-Join-Fix mit zusätzlichen Grenz-/Duplikat-/Diagnostikfällen; Messgates und Fit-Filter unverändert. Frische normale Wheel-Installation; sieben Modellkernmodule unverändert. Installation weiterhin0.2.7.

## 2. Live-Stand und Grenzen

Freigegebenes Update: frisches verschlüsseltes Konfigurations-/App-Backup ohne Recorder-Datenbank,21 neue/21 aufbewahrte alte Integrationsdateien und1.342 unveränderte Abhängigkeitsdateien per Hash zurückgelesen, genau ein zusätzlicher Core-Neustart.

HA2026.10.2/Python3.14.6: drei Entries geladen,60 Sensoren/sechs Geräte. Wetter, Prognosekurven, Resttag/Folgetage, GHI-Anwendung, Persistenz und gespeicherte Optionen geprüft. Optionskorrektur nur mit Entry-Reload. Konfiguration gültig, null aktive Repairs. Verwaltungsoberfläche visuell nicht belegt. Ersttags-Tagesbeginnsnapshot fehlt korrekt.

Lernbindungen leer: Import der Lernbibliotheken im Forecast-Lifecycle belegt keinen produktiven Fit. Messquellenqualifikation und nötige Abregelungsevidenz bleiben offen; Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage.

Keine Energy-Umschaltung/kein laufender Vergleichsjob. Private Parameter/Belege bleiben außerhalb Git/Review. Referenzparameter vor fairer Kohorte angleichen, Fremdeinstellungen nur gesondert freigegeben. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo werden unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereitgestellt. Die Veröffentlichung ändert keine produktive HA-Installation und ersetzt den ausstehenden Vollreview nicht.

Frische lokale Vorprüfung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
