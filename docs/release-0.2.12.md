# Adaptive Solar 0.2.12

## Änderungen

- Neue Direktstrahl-Schattentabelle je AC-/DC-Ausgangsstufe und Sonnenstandsfenster.
  Sie lernt einen begrenzten Transmissionsfaktor aus gültiger Stufenleistung und
  gepaarter horizontaler Globalstrahlung. Diffuslicht bleibt erhalten; ein
  gemeinsamer Zähler liefert weiterhin keine getrennten Stringmessungen.
- Aufnahmen verlangen geeigneten Sonnenstand, Clearness, ausreichenden Direktanteil,
  vollständige Wetterreferenzen sowie gültige, nicht abgeregelte Messungen unterhalb
  der Stufengrenze. Gekappte GHI-Normalisierungen werden nicht dauerhaft gelernt.
- Die Schattenreferenz verwendet den vollen normierten GHI-Paar-Gain auch bei
  zulässig zeitversetzten Messungen. Der kurzlebige Leistungsnowcast behält seinen
  bisherigen Decay. Innerhalb des maximal fünfminütigen Paars wird ein konstanter
  normierter Strahlungsfaktor angenommen.
- Neue Schattenbaselines, Medianschwankungen, Residualanwendung und unabhängige
  Holdouts werden gemeinsam geprüft; ungeprüfte Fenster behalten Physik.
  Ausgangsgrenzen und die bei Ausgabe geltenden Rückfallregeln gelten auch für die
  interne Bewertung. Verspätete Labels dürfen frühere Prognoseentscheidungen nicht
  nachträglich verbessern.
- Speichergrenzen gelten auch bei Wetterausfällen und vor jedem Schreiben. Die
  Historienrevision wird zusammen mit dem Datensnapshot an den Worker übergeben.
  Abregelungswechsel innerhalb eines Ereignisbursts invalidieren die Zählerlinie.
- Recorder-Istwerte verfolgen Rohdatenempfang und Qualitätsrevision unabhängig.
  Eine alte positive Qualitätsmaske kann eine neuere Invalidierung nicht durch
  bloßes erneutes Abrufen überdecken.
- Der generische Reviewhelfer unterstützt Grok 4.7/high und alternativ Codex
  GPT-6.1-Sol/high. Fortschrittstext vor dem Codex-Abschluss-JSON wird getrennt
  behandelt; vollständige native Kontext- und Hashprüfungen bleiben Pflicht.

## Upgrade von 0.2.11

Runtimepins, Musl-Binärbasis, physikalische Messgrenzen, bestehende Optionen,
Sensor-IDs und Energy-Zuordnungen benötigen keine Änderung. Ein vorhandener
passender scikit-learn-Payload wird weiterverwendet. Nach dem HACS-Download ist ein
Core-Neustart erforderlich, um die neue Integration zu laden; Core selbst wird
nicht aktualisiert.

Der Featurevertrag wechselt von `atomic-ghi-cohort-centered-weather-v2` auf
`beam-shade-table-v1`. Alte Forecastfeatures und daraus abgeleitete Lerner werden
verworfen, damit Schattenverluste nicht doppelt korrigiert werden. **Passende
gemessene Energieintervalle und tatsächlich ausgegebene Tagesbeginn-Snapshots
bleiben innerhalb der bestehenden Provenienz- und Aufbewahrungsgrenzen erhalten.**
Die Schattentabelle startet leer und neutral mit Faktor 1; ein Fenster wird erst
nach fünf unterschiedlichen UTC-Viertelstunden freigegeben. Physikalische oder
Messquellenänderungen bleiben inkompatibel. Historische Betreiberbestätigungen
werden nicht nachträglich als technische Quellenzertifizierung umgedeutet.

Vor dem Update bisherigen Komponentenstand und die verwendeten Lernstores
sichern. Ein gezielter Rückweg ist die erneute Installation von `v0.2.11` und,
bei benötigtem altem Lernarchiv, die separat gesicherte Historie bei gestoppter
Integration. Eine vollständige HA-Wiederherstellung ist ein eigener Eingriff.
[Spezifikation](adaptive-solar-verschattung.md), [Bedienung](bedienung.md).

## Prüfstand und Grenzen

Geprüfte Implementierung: Commit `507ab4ecf5af0c205038ca15716f055def00a433`,
**978 Tests ohne Skips** unter Core **2026.10.4** / Testplugin **0.13.375**,
Ruff und Dependencycheck erfolgreich. Neuer vollständiger Grok-4.7/high-Textreview
über 100 Originaldateien: **mergeable, keine Findings**; native Kontext- und
Hashnachweise unabhängig erneut geprüft. [Reviewnachweis](review-findings.md).

Diese Releasevorbereitung ändert daran nur Versionsmetadaten und öffentliche
Status-/Releasehinweise. Die übrigen Integrationsdateien bleiben bytegleich zum
geprüften Stand. Releasepakete, CI und die tatsächliche HACS-Installation werden
separat geprüft und im [Entwicklungsstand](entwicklungsstand.md) dokumentiert.
Tests, Review und Installation belegen keinen realen Prognosevorsprung gegenüber
Helios oder Open-Meteo Solar. Qualifiziertes produktives Lernen und der prospektive
Vergleich bleiben eigenständige Nachweise.

## Veröffentlichung und Installation

Am 27.10.2026 aus Commit `7c2b4be` als `v0.2.12` veröffentlicht. Wheel, Quellpaket,
Integrations-ZIP und SHA256-Liste sind im GitHub-Release verfügbar; nach Download
bytegleich geprüft. Branch- und Tag-CI vor HACS-Download vollständig erfolgreich.
Nach verifizierter nativer Sicherung und genau einem Core-Neustart vier Einträge
mit Version 0.2.12 nativ bestätigt. 24 Dateien, 80 Entity-/Unique-IDs, vier Geräte,
Optionen, Energy-Zuordnungen, abgeschlossene Messintervalle und echte Tagesbeginn-
Snapshots zurückgelesen; Featuremigration erfolgreich, neue Schattentabellen neutral.
Alle vier Qualitätsanzeigen nach echten Quellenberichten bei Physik/kalt,
Konfiguration gültig und keine aktiven Repairs. [Nachweise](entwicklungsstand.md).
Dieser nachgetragene Abschnitt gehört nicht zum eingefrorenen Release-Tag oder
Reviewtext; ausgelieferte Implementierungsbytes und Tag bleiben unverändert.
