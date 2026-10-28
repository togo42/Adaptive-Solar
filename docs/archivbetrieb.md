# Originaldaten archivieren und Prognosen wiederholen

Stand: 28.10.2026, unveröffentlichter Entwicklungsbranch `codex/archive-ensembles`.
Die Werkzeuge sind implementiert. HA-Export, Host-Timer und private Zuordnungen
sind damit noch nicht auf einer produktiven Installation aktiviert.
[Speichervertrag](archive-storage-contract.md), [Modellauswahl](wettermodelle-und-prognosehorizonte.md)
und [Physikversuchsplan](physikvergleich-und-archivierung.md) ergänzen diese Anleitung.

## 1. Umfang und Voraussetzungen

HA erfasst die tatsächlich verwendeten Wetterantworten, normalisierten Eingaben,
Anlagenkonfiguration, Beobachtungen, Lern-/Schattenzustände und vollständigen
Prognoseausgaben. Ein eigener Exportpuffer schützt vor kurzen Verbindungsproblemen.
Der Archivhost sammelt diese Ereignisse, zusätzliche Wettermodelle einschließlich
echter Ensembles sowie Recorder-/Referenzaufnahmen. Aus eingefrorenen Originalen
können Baseline und spätere Kandidaten mit identischen Eingaben gerechnet werden.

Auf dem Host denselben Repositorycommit und die Laufzeitpins in einer separaten
Python-Umgebung installieren; [Entwicklung](entwicklung.md) beschreibt die
reproduzierbare Installation. Quellcommit und Bibliotheksversionen zusammen mit
jedem Versuch sichern. Datenpins enthalten Originaldaten und Hashes, keine
vollständige Kopie der ausführbaren Softwareumgebung. Ein abweichender Codehash
kann explorativ gerechnet werden, besteht aber keine exakte Baseline-Abnahme.

Private Standortdateien, Zuordnungen, Ausgaben und Archive gehören unter
ignorierte `data/`-Pfade. Eine Standortdatei hat das Schema von
[examples/site.json](../examples/site.json); für einen Anlagenvergleich müssen
Geometrie, Ausgabestufen und Messgrenzen der tatsächlichen Anlage entsprechen.
Konkrete Hostnamen, Pfade und Sensorzuordnungen gehören in den privaten Betriebsplan.

## 2. HA-Export und dauerhafte Übernahme

Je Eintrag **Originaleingaben archivieren (privater Exportpuffer)** (`archive_export`)
einschalten. Standard ist aus. Die Option verändert weder den physikalischen
Konfigurationsfingerprint noch die bestehende Lernhistorie. Das Journal beginnt
erst nach erfolgreicher Einrichtung; seine Arbeit läuft außerhalb des HA-Loops.

Der native Administratordienst `adaptive_solar.export_archive` liefert begrenzte
Seiten mit Cursor, Generation, Prüfsummen und Lückenstatus. Er löst keinen neuen
Wetterabruf aus. Der Collector benötigt einen entsprechend berechtigten HA-Zugang;
`HA_URL` und `HA_TOKEN` kommen ausschließlich aus der Prozessumgebung.
Zugangsdaten nicht in Konfigurationsdateien, Git oder Kommandozeilenargumente schreiben.

```bash
.venv/bin/python scripts/archive.py --root data/archive collect \
    --source ha-example --entry-id PRIVATE_ENTRY_ID
.venv/bin/python scripts/archive.py --root data/archive verify
.venv/bin/python scripts/archive.py --root data/archive stats
```

Für jeden HA-Eintrag eine eindeutige dauerhafte `--source` verwenden. Den Quellnamen
nicht später einem anderen Eintrag zuweisen. Ein Neustart setzt den Cursor nicht
zurück. Erst das dauerhaft gespeicherte Original erlaubt dessen Fortschreiben;
Wiederholungen sind idempotent. Bei einer neuen Journalgeneration oder verdrängten
Ereignissen meldet der Collector eine Lücke. Sie wird nicht durch Nullwerte ersetzt.

Das Journal begrenzt beim Schreiben auf 72 Stunden, 10.000 Ereignisse und 64 MiB
serialisierten Ereignisinhalt; die zuerst erreichte Grenze gilt. Ohne weitere
Schreibvorgänge werden alte Inhalte nicht automatisch gelöscht. SQLite benötigt zusätzliche
Datei-/Transaktionsreserve, siehe [physische Grenzen](archive-storage-contract.md).
Die HA-Warteschlange begrenzt ausstehende und laufende Arbeit zusammen auf 64
Ereignisse/8 MiB. Große Lernzustände können den nutzbaren Zeitraum erheblich
verkürzen. Der Pilot muss Datenrate, Ausfälle und Überläufe messen, bevor eine
bestimmte Ausfallüberbrückung zugesagt wird.

`archive_export` in Diagnose und Qualitätsattributen zeigt Zustand, Belegung und
Fehler. Archivprobleme stoppen die Prognose nicht. Große Wetter-, Zustands- und
Prognoseobjekte werden komprimiert in referenzierte Teile zerlegt; alle Teile
müssen für einen Replay vorhanden sein. Ein Datenpin allein garantiert dies nicht.

## 3. Zusätzliche Wettermodelle und Ensembles

```bash
.venv/bin/python scripts/capture_weather.py --archive data/archive \
    --source weather-example --site-json data/site.json --hours 193
```

Der einmalige Abruf ist für einen Host-Timer vorgesehen. Er speichert Originalbytes,
Request, tatsächlichen Empfang, fehlgeschlagene Antworten, Mitgliedsabdeckung,
Softwarehashes und dokumentierte Feldherkunft. Einen nicht vom Endpoint gelieferten
Modelllaufzeitpunkt lässt er ausdrücklich unbekannt. GHI/DNI/DHI können aus
Providerableitungen stammen; ungeklärte Ensemblefelder bleiben entsprechend markiert.

| Standardgruppe | Produkte |
| --- | --- |
| Deterministische Vergleichsarme | `best_match`, `icon_d2`, `icon_eu`, `ecmwf_ifs`, `gfs_global` |
| Echte Ensemblemitglieder | `dwd_icon_d2_eps` (20), `ecmwf_ifs_europe_ensemble` (51), `ecmwf_ifs025_ensemble` (51) |

`--deterministic` und `--ensembles` akzeptieren kommaseparierte Kennungen;
eine leere Zeichenkette schaltet die jeweilige Gruppe aus. Zusätzliche regionale
Deterministen müssen am Standort geprüft werden. Eine abgefragte Dauer ist keine
garantierte Abdeckung. Auch kurze, unvollständige oder fehlgeschlagene Antworten
bleiben nachvollziehbar. Der Collector fragt einen vorherigen Umgebungspunkt ab;
Strahlung am API-Endpunkt bezeichnet weiterhin die vorangegangene Stunde.

Der HA-Wetterabruf verwendet ebenfalls ein Stundenfenster mit Randreserve, damit
ICON-D2 nicht bereits durch zwei Kalendertage abgeschnitten wird. Die Ausgabe
bleibt auf die eingestellten lokalen Prognosetage beschränkt. Die Host-Aufnahme
ändert weder die HA-Modellauswahl noch deren deterministische Gleichgewichtung.

## 4. Istenergie und Referenzprognosen

Die bestehenden [Recorder-/Referenzzuordnungen](benchmark-aufnahme.md) lassen sich
mit einem gemeinsamen lokalen Archiv verwenden:

```bash
.venv/bin/python scripts/archive_observations.py --archive data/archive \
    --source measurements-example --actual-config data/actual-mapping.json \
    --reference-config data/reference-mapping.json --lookback-hours 72 --lag-minutes 10
```

Istaufnahmen wiederholen die letzten 72 vollständigen UTC-Stunden mit zehn Minuten
Veröffentlichungsreserve. Das erhält spätere Recorderrevisionen mit ihrem eigenen
Empfangszeitpunkt; 72 Stunden sind auch an beiden DST-Wechseln 72 echte Stunden.
Für andere Korrekturfristen den Rückblick ausdrücklich anpassen. Quellen heißen
`measurements-example:actuals` und `measurements-example:references`.

Ohne `--quality data/quality.json` bleibt die Rohenergie gespeichert, gilt aber
wegen fehlender Intervallqualifikation nicht als Trainingswahrheit. Das Format und
die Anforderungen an Abregelung, Abdeckung, Resets und Verfügbarkeit beschreibt
der Aufnahmeleitfaden. Ein aktueller Status ersetzt keinen Nachweis über das ganze
Intervall. HA-Quellberichte und qualifizierte Intervalle werden zusätzlich im
HA-Export bewahrt; ihre Zuordnung zu externen Recorder-Messgrenzen muss der
Vergleich ausdrücklich prüfen.

Referenzfristen mit `--cutoff ISO_ZEIT_MIT_OFFSET` vorgeben. Der tatsächliche
Gruppenempfang entscheidet über Rechtzeitigkeit. Zu spät gelieferte Daten werden
aufbewahrt und als spät gemeldet. Für regelmäßige feste Entscheidungszeitpunkte
die Frist pro Lauf berechnen und den Abruf ausreichend vorher beginnen.

```bash
.venv/bin/python scripts/archive.py --root data/archive export-observations \
    --source measurements-example:actuals --kind actuals --output data/actuals.jsonl
```

Für Referenzen `:references` und `--kind references` einsetzen. Der Export
überschreibt kein bestehendes Ziel. Original-Captureobjekte einschließlich Rohdaten,
Revisionen und Qualitätsausschlüssen bleiben für die bestehenden Auswerter erhalten.

## 5. Eingefrorene Daten und exakter Replay

```bash
.venv/bin/python scripts/archive.py --root data/archive pin pilot-01
.venv/bin/python scripts/archive.py --root data/archive export-dataset \
    pilot-01 data/pilot-01
.venv/bin/python scripts/replay_archive.py --archive data/pilot-01 \
    --source ha-example --dataset pilot-01 --output data/baseline-replay.json
```

Ein Pin ist unveränderlich. Ohne Quellenfilter erfasst er alle bis dahin vorhandenen
Originale. Er bewahrt sie über die rollierende Aufbewahrung hinaus. Der Replay prüft
Originalprüfsummen, referenzierte Wetterantworten, erneut geparste Normalisierung,
Zustandsteile, Konfiguration und Zeitverfügbarkeit. Fehlende, fremde oder geänderte
Originale führen zum Abbruch. Ausgabezeit/Cutoff, Ende der Berechnung und spätere
Archivübernahme sind verschiedene Zeitpunkte.

Standard ist der jüngste passende `forecast_issued`; `--event-id` wählt eine
bestimmte Ausgabe, `--as-of` begrenzt die damalige Verfügbarkeit. Die numerische
Toleranz beträgt standardmäßig `--tolerance-w 0.000001`. Exakte Abnahme verlangt
zusätzlich übereinstimmende Quell- und Bibliotheksprovenienz. Aktive Lernmodelle
werden aus den tatsächlich verwendeten Fitzeilen am ursprünglichen Fit-Cutoff
rekonstruiert; spätere Beobachtungen sind nicht zulässig.

`--physics-ablation` vergleicht zusätzlich den NWP-Physikpfad ohne lokale
Beobachtungs-/Lernkorrekturen. `Candidate`/`ReplayInputs` in `core/replay.py`
erlauben eigene versionierte Kandidaten auf frisch rekonstruierten identischen
Eingaben. Feinere Zeitintegration und IAM sind noch keine implementierten Arme.
Ein gelungener Replay ist ein Reproduzierbarkeitsnachweis, kein Genauigkeitsgewinn.

## 6. Energiequantile für 24/48 Stunden

Fiktives Zeitfenster durch eine zum Archiv passende künftige Entscheidung ersetzen:

```bash
.venv/bin/python scripts/replay_archive.py --archive data/archive \
    --source weather-example --probabilities --site-json data/site.json \
    --as-of 2026-11-01T10:00:00Z --start 2026-11-01T10:00:00Z \
    --end 2026-11-02T10:00:00Z --threshold-kwh 5 --threshold-kwh 10 \
    --output data/probabilities-24h.json
```

Jedes Mitglied durchläuft die gemeinsame PV-Physik und Ausgangsbegrenzung.
Zeitintervalle und Ausgabestufen werden zuerst innerhalb desselben Mitglieds
summiert. Erst aus diesen vollständigen Energieszenarien entstehen Q10/Q50/Q90
und `probability_below` für **Energie strikt kleiner als** die jeweilige Schwelle.
Der Gegenanteil beschreibt Energie mindestens gleich der Schwelle. Ein Q10 ist
eine untere Ertragsquantile; es ist keine Niederschlagswahrscheinlichkeit.

Standard `--quorum 1.0` verlangt alle erwarteten Mitglieder über das ganze Fenster.
Eine bewusst geringere Schwelle verändert die Kohorte und wird ausgewiesen;
sie belegt keine gleichwertige Wahrscheinlichkeit. Pro Produkt zählt nur der
jüngste bis zum Cutoff eingegangene Abruf. Ein neuer fehlgeschlagener Abruf wird
nicht unbemerkt durch einen älteren ersetzt.

Für die IFS-Familie wird Europe bevorzugt, IFS025 ist Rückfall. Beide gehen nicht
doppelt in die Familienmischung ein. ICON und IFS erhalten gleiche Familiengewichte,
unabhängig von ihren 20 bzw. 51 Mitgliedern. Reicht ICON-D2 nicht über das gesamte
48-Stunden-Fenster, bleibt für dieses Fenster nur ein vollständiger längerer Arm.
Für das kürzere 24-Stunden-Fenster kann ICON weiterhin teilnehmen. Es werden keine
ICON-Mitgliedsnummern an gleichnamige IFS-Mitglieder angehängt.

Die Ausgabe bezeichnet die Verteilung als **unkalibriert**. Optional bewertet
`--actual-kwh` einen ausdrücklich qualifizierten späteren Istwert mit CRPS,
Pinball-Loss, Brier-Score und 80-%-Intervallabdeckung/-breite. Es ersetzt keinen
chronologischen Test über viele unabhängige Tage.

`--calibration-json` erlaubt derzeit nur eine Median-Biaskorrektur, standardmäßig
ab 20 eindeutigen früheren Zielzeitfenstern derselben Familie, desselben Produkts,
derselben Dauer und Vorlaufklasse. Jeder Fall enthält `issued_at`, `target_start`,
`target_end`, `available_at`, `predicted_median_kwh`, `actual_kwh`, `family`,
`product` und `qualified: true`. Zeiten benötigen Offsets. Spätere oder doppelte
Fenster werden verworfen/abgelehnt. Der Status
`empirical_median_bias_corrected_spread_unvalidated` sagt ausdrücklich: Die Breite
und Schwellenzuverlässigkeit wurden noch nicht lokal kalibriert und geprüft.

Für „Akku voll halten oder Platz schaffen“ fehlen außerdem Verbrauchsszenarien,
SoC, Lade-/Entladegrenzen und eine vorab fixierte Entscheidungsregel. Die Werkzeuge
liefern die Datenbasis; sie senden keine Akku- oder HA-Regelbefehle.

## 7. Zeitplanung, Aufbewahrung und Pilot

| Aufgabe | Startvorschlag |
| --- | --- |
| HA-Export je Eintrag abholen | Alle fünf Minuten |
| Zusätzliche Wetter-/Ensembleaufnahme | Stündlich; Providerquoten und Modellupdates im Pilot prüfen |
| Recorderrevisionen und Referenzen | Stündlich; Referenzfristen zusätzlich passend zur Auswertung |
| Archiv prüfen / Speicherstatus erfassen | Täglich |
| Rollierende Wartung | Täglich nach erfolgreicher Prüfung |
| Speicherbedarf neu bewerten | Nach drei und sechs Monaten ab Aufnahmestart |

Die Befehle sind einmalige Läufe für systemd-Timer oder einen vorhandenen Scheduler.
Arbeitsverzeichnis und Pythonpfad müssen zum festgehaltenen Checkout gehören.
Je Quelle nur einen laufenden Produzenten zulassen; Timerstarts derselben
systemd-Serviceeinheit überlappen nicht. Fehlercodes und Lücken müssen überwacht
werden. Zugangsdaten über den vorhandenen geschützten Laufzeitmechanismus in die
Umgebung geben; eine `EnvironmentFile` mit hineinkopiertem HA-Token ist kein
Bestandteil dieser Anleitung. Die konkrete Hostinstallation wird getrennt vorbereitet.

```bash
.venv/bin/python scripts/archive.py --root data/archive verify
.venv/bin/python scripts/archive.py --root data/archive stats
.venv/bin/python scripts/archive.py --root data/archive maintain
```

`maintain` löscht ungepinnte Originalpakete nach 24 Kalendermonaten seit Aufnahme
auf dem Host. Je Quelle bleibt die letzte Cursorseite zusätzlich erhalten;
eingefrorene Vergleichsdaten bleiben bis zu einer eigenen Aufbewahrungsentscheidung.
`stats` zeigt komprimierte Raten, Indexgröße, Hochrechnung und die Termine nach
drei/sechs Monaten. Die Prüfung muss auch Staging, temporäre Daten, eingefrorene
Kopien und Backups berücksichtigen. Ein einzelner Wetterabruf reicht nicht für
eine belastbare 24-Monats-Kapazitätsplanung.

Der Index kann mit `rebuild-index` aus den Originalen erneuert werden.
Fehlende gepinnte Originale bleiben auch dabei ein Fehler. Eine Sicherung gilt
erst nach Wiederherstellung, Prüfsummenprüfung und mindestens einem vollständigen
Replay aus dem wiederhergestellten Stand als erprobt. Pin und zweite Kopie auf
derselben Platte ersetzen kein separates Backup.
