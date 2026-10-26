# Entwicklungsstand und offene Nachweise

Stand: 26.10.2026. **Adaptive Solar 0.2.10 ist implementiert und lokal validiert; letzter bestätigter produktiver Stand ist 0.2.9 unter Core 2026.10.4.** Der gebundene Grok-4.7/high-Review ist ohne Findings abgeschlossen. Veröffentlichung und HACS-Aktivierung der neuen Version folgen separat. Ein qualifizierter produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## Update 0.2.10

Morgen-/Abenddämpfungen sind pro String in Modell und Einrichtung ergänzt, mit neutralen Altdefaults und Anwendung vor gemeinsamer AC-/DC-Begrenzung. Das bestehende Horizontmodell bleibt je String konfigurierbar. [AS-UI-001](geplante-updates.md) ist umgesetzt: neue Einträge mit einer Ausgangsstufe erzeugen ein Gerät; bestehende Gesamt-Sensoren bleiben unter ihren IDs als ausgeblendete Kompatibilitätsanzeigen am Einzelgerät erhalten. Mehrere Ausgangsstufen behalten Einzel- und Gesamtanzeigen. [Versionsinformationen](release-0.2.10.md).

Je **893 Tests ohne Fehler oder Skips** bestanden mit Core **2026.10.2/.3/.4**, Testplugins **0.13.373/.374/.375**, Python 3.14.4/glibc. Laufzeiten: **95,96 / 93,99 / 94,61 Sekunden**. Drei Kopien der bestehenden Prüfumgebungen wurden regulär mit demselben 0.2.10-Wheel installiert; ursprüngliche Umgebungen blieben unverändert. Isolierter Paketimport und sämtliche **22 Paketdateien einschließlich Markenbild** wurden außerhalb des Repositorypfads gegen den Wheel geprüft; `pip check` jeweils erfolgreich. Belege: `artifacts/compatibility-ha-2026.10.2-0.2.10-r2/` und entsprechend .3/.4.

Die Migrationstests prüfen AC/DC, mehrere Strings je Stufe, stabile Entity-/Unique-IDs und Benutzeranpassungen, native Energy-Ausgaben und unveränderte Messhistorie nach Reload sowie wiederholte Einzel-/Mehrfachstufenwechsel. Die Physiktests prüfen Dämpfungsgrenzen, Neutraldefaults, Zeitumstellungen, Mitternacht überschreitende Sonnentage, Polartag/-nacht und die Reihenfolge vor dem gemeinsamen Clip. Diese Nachweise ersetzen keine reale Genauigkeitsauswertung.

Die folgenden Abschnitte dokumentieren den historischen Stand 0.2.9 und dessen getrennte Nachweise.

Der erste vollständige Implementierungsreview der neuen Version fand zwei behebungsbedürftige Punkte: restaurierte Umweltsensor-/Leistungswerte im Nowcast und zusammengefasste Ablehnungsgründe kurzer beziehungsweise nicht prospektiver Trainingszellen. Beide sind in `8b40414` korrigiert und durch Regressionen abgedeckt. Der Featurevertrag v2 verwirft ältere unqualifizierbare Archivfeatures, erhält aber separat geprüfte Messintervalle und ausgegebene Tagesbeginn-Snapshots. Der erneute gebundene Grok-Review ist auf Commit `5a7da69` ohne Findings abgeschlossen; [Umfang und Hashbindung](review-findings.md).

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch Subagenten mit hohem Aufwand.

**Implementierung 0.2.9:** optionaler generischer Messgültigkeitseingang für jede AC-/DC-Stufe. Ohne Bindung bleiben alte JSON-Daten und Fingerprints erhalten; gesetzte Quellen trennen die Messprovenienz. Physik und Umweltdaten bleiben bei Messausfällen verfügbar. [Messgültigkeitsvertrag und Grenzen](measurement-validity.md).

| HA Core | Testplugin | Bestandene Tests | Laufzeit |
|---|---|---:|---:|
| 2026.10.2 | 0.13.373 | 852 | 92,17 s |
| 2026.10.3 | 0.13.374 | 852 | 92,15 s |
| 2026.10.4 | 0.13.375 | 852 | 92,70 s |

Null Fehler/Skips; Python 3.14.4/glibc, normale 0.2.9-Wheel-Installation in getrennten Kopien der geprüften Umgebungen. Isolierter Import außerhalb des Repositories, alle 21 installierten Paketdateien und `pip check` je Umgebung geprüft; frühere Umgebungen erhalten. JUnit und Versions-/Hashbelege: `artifacts/compatibility-ha-2026.10.2-0.2.9/` (entsprechend .3/.4). Testextra nun Core .4/Plugin .375. Ruff grün.

26 neue Messgültigkeitsfälle; acht zusätzliche unabhängige native HA-.3-Gegenfälle ohne zwingende Findings. Zwölf native HA-.4-Integrator-/Template-Fälle umfassen elf normale Sicherheitsfälle und einen ausdrücklich reproduzierten `update_entity`-Gegenfall. Ein bestandener Gegenfalltest belegt die dokumentierte Grenze, keine Sicherheit dieses Pollpfads. Lokale Belege: `data/measurement-quality-audit-20261025/`, `data/integrated-source-validity-20261025/`. Keine produktive Ausfallinjektion.

Von sieben Kernmodulen ändert sich nur die Datenklasse um das optionale Feld; Physik-/Lernalgorithmen und Binärabhängigkeiten bleiben unverändert. ZIP und Wheel sind mit allen 21 Komponenten verglichen (`artifacts/package-source-validation-0.2.9.json`). Buildbackend setuptools 84.2.1 in isolierter Umgebung. Kein neuer Musl-Lauf und kein nativer produktiver 0.2.9-Fit behauptet. Grok-4.7/high-Implementierungsreview ohne Findings im gebundenen Commit `38c05d5`: 79 vollständige Originale und sechs unveränderte Forschungsreferenzen, keine Kontextkürzung; [Nachweis](review-findings.md).

Historische Stände bleiben getrennt: 0.2.8 je 814 Tests und positiver Implementierungsreview im gebundenen Commit `0285445`; 0.2.7 je 752 Tests und zuvor installierter Stand. Der ursprüngliche 231er-Musl-Nachweis betrifft die damalige Kernfassung, nicht die neue Datenklasse. Unveränderliche Quellen/Belege unter `artifacts/releases/0.2.7-reviewed/` und `artifacts/releases/0.2.8-implementation-20261025T132350Z/`.

## 2. Live-Stand und Grenzen

Freigegebene Aktivierung von 0.2.9: frisches geschütztes Konfigurations-/App-Backup ohne Recorder-Datenbank vollständig gelesen und gehasht; alle 21 neuen Integrationsdateien und drei betroffenen Konfigurationsdateien zurückgelesen. Altcode und ursprüngliche Timerdatei liegen außerhalb der aktiven HA-Lader. Binärabhängigkeiten wurden nicht ersetzt. Genau ein Core-Neustart, anschließend native Subentry-/Optionsflows mit Eintragsreloads.

Core 2026.10.4/Python 3.14.9, Konfiguration gültig, null aktive Repairs und vier geladene Entries mit Prognosekurven. Der vollständige unabhängige Readback umfasst 75 Prüfungen: vier erhaltene Sites, exakt neun erlaubte Bindungsänderungen, 21 Codehashes, drei Quellenhashes und zwei native MQTT-Gültigkeitskonfigurationen. Temperatur, Wind und Globalstrahlung werden verarbeitet; bei niedrigem Sonnenstand bleibt die GHI-Korrektur aus. Der Abregelungseingang bleibt erhalten. Eine visuelle Prüfung der Verwaltungsoberfläche ist damit nicht belegt.

Zwei Paket-Leistungskopien mit genau zwei Recorder-Ausnahmen und zwei Gültigkeitssignale sind aktiv. Für die Originalintegrale ist eine Minute als maximales Teilintervall konfiguriert; fortschreitende Berichtszeiten bei unveränderten Nachtwerten und angenommene Null-Deltas sind nativ beobachtet. Die tatsächlichen Timer unterliegen der HA-Ereignisplanung. Der lokale Konfigurationsreview durch Grok 4.7/high hat nach drei Dokumentationskorrekturen im Kandidaten `439373b` keine Findings. Empfangs-TTL, Retain-/Cachepoll-Grenzen und bestehender Quellendrift bleiben dokumentierte Betriebsannahmen; dies ist keine physikalische Vollqualifikation.

Die freigegebenen Lernquellen sammeln neue Originalintervalle. Ein bewusst nur mit Leistung angebundener Eintrag erhält keine Energielabels. Alle Modelle benötigen weiterhin ausreichende qualifizierte Historie; es ist kein produktiver ML-Fit oder Genauigkeitsvorsprung belegt. Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage. Die aktuellen privaten Aktivierungs-/Readbackbelege liegen unter `data/activation-0.2.9-20261025/` und werden nicht veröffentlicht. Dieser Statusnachtrag ergänzt die geprüften Quellstände um aktuelle Betriebsnachweise und verändert keinen Modellcode.

Keine Energy-Umschaltung und kein dauerhafter Vergleichsjob. Die gesondert freigegebenen West-Referenzen wurden auf dieselbe Ausgangsgrenze angeglichen. Ein erster prospektiver Einmal-Capture enthält ausschließlich künftig vollständige gemeinsame Stunden; er gehört nicht zur vorab festgelegten Hauptkohorte. Ein lokaler90-Tage-Walk-forward mit60 Tagen Anlauf und30 Auswertungstagen ist abgeschlossen. Er verwendet nachträglich beschaffte ursprüngliche Wetterläufe und angenommene Verfügbarkeitszeiten; Messqualifikation und vollständige lernende Helios-Referenz fehlen. Er ist bedingte historische Diagnose, kein produktiver oder prospektiver Genauigkeitsnachweis. Private Parameter/Ergebnisse bleiben außerhalb Git/Review. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Die dokumentierte Erstveröffentlichung stellte Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereit. Sie änderte keine produktive HA-Installation. Der anschließend gültig abgeschlossene Implementierungsreview bindet Commit `0285445`, 76 vollständige Originale und sechs unveränderte Forschungsreferenzen; Umfang und Grenzen stehen im [Reviewnachweis](review-findings.md). Die lokale Aktivierung von 0.2.9 ist keine neue Veröffentlichung.

Vorprüfung dieser Erstveröffentlichung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
