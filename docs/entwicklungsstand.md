# Entwicklungsstand und offene Nachweise

Stand: 25.10.2026. **Nach dem Betreiberupdate auf Core 2026.10.4 geprüft: Adaptive Solar 0.2.7, vier geladene Anlageneinträge mit Prognosekurven.** Lokale Kompatibilität des Entwicklungsstands 0.2.9 und sein gebundener Grok-4.7/high-Implementierungsreview sind geprüft. Produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch Subagenten mit hohem Aufwand.

**Lokaler Kandidat 0.2.9:** optionaler generischer Messgültigkeitseingang für jede AC-/DC-Stufe. Ohne Bindung bleiben alte JSON-Daten und Fingerprints erhalten; gesetzte Quellen trennen die Messprovenienz. Physik und Umweltdaten bleiben bei Messausfällen verfügbar. [Messgültigkeitsvertrag und Grenzen](measurement-validity.md).

| HA Core | Testplugin | Bestandene Tests | Laufzeit |
|---|---|---:|---:|
| 2026.10.2 | 0.13.373 | 852 | 92,17 s |
| 2026.10.3 | 0.13.374 | 852 | 92,15 s |
| 2026.10.4 | 0.13.375 | 852 | 92,70 s |

Null Fehler/Skips; Python 3.14.4/glibc, normale 0.2.9-Wheel-Installation in getrennten Kopien der geprüften Umgebungen. Isolierter Import außerhalb des Repositories, alle 21 installierten Paketdateien und `pip check` je Umgebung geprüft; frühere Umgebungen erhalten. JUnit und Versions-/Hashbelege: `artifacts/compatibility-ha-2026.10.2-0.2.9/` (entsprechend .3/.4). Testextra nun Core .4/Plugin .375. Ruff grün.

26 neue Messgültigkeitsfälle; acht zusätzliche unabhängige native HA-.3-Gegenfälle ohne zwingende Findings. Zwölf native HA-.4-Integrator-/Template-Fälle umfassen elf normale Sicherheitsfälle und einen ausdrücklich reproduzierten `update_entity`-Gegenfall. Ein bestandener Gegenfalltest belegt die dokumentierte Grenze, keine Sicherheit dieses Pollpfads. Lokale Belege: `data/measurement-quality-audit-20261025/`, `data/integrated-source-validity-20261025/`. Kein produktiver Eingriff/Ausfalltest.

Von sieben Kernmodulen ändert sich nur die Datenklasse um das optionale Feld; Physik-/Lernalgorithmen und Binärabhängigkeiten bleiben unverändert. ZIP und Wheel sind mit allen 21 Komponenten verglichen (`artifacts/package-source-validation-0.2.9.json`). Buildbackend setuptools 84.2.1 in isolierter Umgebung. Kein neuer Musl-Lauf und kein nativer produktiver 0.2.9-Fit behauptet. Grok-4.7/high-Implementierungsreview ohne Findings im gebundenen Commit `38c05d5`: 79 vollständige Originale und sechs unveränderte Forschungsreferenzen, keine Kontextkürzung; [Nachweis](review-findings.md).

Historische Stände bleiben getrennt: 0.2.8 je 814 Tests und positiver Implementierungsreview im gebundenen Commit `0285445`; 0.2.7 je 752 Tests und installierter Stand. Der ursprüngliche 231er-Musl-Nachweis betrifft die damalige Kernfassung, nicht die neue Datenklasse. Unveränderliche Quellen/Belege unter `artifacts/releases/0.2.7-reviewed/` und `artifacts/releases/0.2.8-implementation-20261025T132350Z/`.

## 2. Live-Stand und Grenzen

Freigegebenes Update: frisches verschlüsseltes Konfigurations-/App-Backup ohne Recorder-Datenbank,21 neue/21 aufbewahrte alte Integrationsdateien und1.342 unveränderte Abhängigkeitsdateien per Hash zurückgelesen, genau ein zusätzlicher Core-Neustart.

Vor dem angekündigten Core-Update: HA2026.10.2/Python3.14.6, drei Entries geladen,60 Sensoren/sechs Geräte. Wetter, Prognosekurven, Resttag/Folgetage, GHI-Anwendung, Persistenz und gespeicherte Optionen geprüft. Optionskorrektur nur mit Entry-Reload. Konfiguration gültig, null aktive Repairs. Verwaltungsoberfläche visuell nicht belegt. Ersttags-Tagesbeginnsnapshot fehlt korrekt. Das freigegebene generische Abregelungssignal ist ausschließlich dem DC-Eintrag zugeordnet.

Nach dem Betreiberupdate: Core 2026.10.4/Python 3.14.9, System gesund, Konfiguration gültig, null aktive Repairs. Die drei zuvor installierten Einträge und ein inzwischen vorhandener zusätzlicher Eintrag sind geladen. Je 154 Prognosepunkte, vollständige Resttagsabdeckung und keine Wetterproviderfehler; Temperatur, Wind und GHI sind gültig. Die GHI-Korrektur wird zum aktuellen Ausgabezeitpunkt wegen einer zu schwachen Referenzstrahlung korrekt ausgelassen. Alle 21 produktiven Integrationsdateien entsprechen weiterhin 0.2.7. Dies belegt aktuellen Forecast-Betrieb, keinen nativen qualifizierten ML-Fit.

Lernbindungen leer: Import der Lernbibliotheken im Forecast-Lifecycle belegt keinen produktiven Fit. Messquellenqualifikation und nötige Abregelungsevidenz bleiben offen; Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage.

Keine Energy-Umschaltung und kein dauerhafter Vergleichsjob. Die gesondert freigegebenen West-Referenzen wurden auf dieselbe Ausgangsgrenze angeglichen. Ein erster prospektiver Einmal-Capture enthält ausschließlich künftig vollständige gemeinsame Stunden; er gehört nicht zur vorab festgelegten Hauptkohorte. Ein lokaler90-Tage-Walk-forward mit60 Tagen Anlauf und30 Auswertungstagen ist abgeschlossen. Er verwendet nachträglich beschaffte ursprüngliche Wetterläufe und angenommene Verfügbarkeitszeiten; Messqualifikation und vollständige lernende Helios-Referenz fehlen. Er ist bedingte historische Diagnose, kein produktiver oder prospektiver Genauigkeitsnachweis. Private Parameter/Ergebnisse bleiben außerhalb Git/Review. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo werden unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereitgestellt. Die Veröffentlichung ändert keine produktive HA-Installation. Der anschließend gültig abgeschlossene Implementierungsreview bindet Commit `0285445`, 76 vollständige Originale und sechs unveränderte Forschungsreferenzen; Umfang und Grenzen stehen im [Reviewnachweis](review-findings.md).

Frische lokale Vorprüfung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
