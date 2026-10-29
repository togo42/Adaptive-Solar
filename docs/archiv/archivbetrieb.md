# Originaldaten archivieren und Prognosen wiederholen

Stand: 29.10.2026, Funktionsumfang 0.2.18. [Versionshinweise](../releases/README.md)
und [historische Prüfstände](../entwicklung/pruefnachweise.md) ergänzen die Anleitung.
Der Archivhost wird unabhängig von HACS aktualisiert.
Die [Hostinstallation](archiv-host-installation.md) beschreibt Dienste, Timer,
verschlüsselte Zugangsdaten und die Platzüberwachung.
[Speichervertrag](archive-storage-contract.md), [Modellauswahl](../recherche/wettermodelle-und-prognosehorizonte.md)
und [Physikversuchsplan](../recherche/physikvergleich-und-archivierung.md) ergänzen diese Anleitung.
Die [Speicherentscheidung und der Transport](archiv-speicherung-und-transport.md)
beschreiben Originaldateien mit SQLite als ersten Schritt sowie PostgreSQL als
spätere Option für Abfragen.

## 1. Umfang und Voraussetzungen

HA erfasst die tatsächlich verwendeten Wetterantworten, normalisierten Eingaben,
Anlagenkonfiguration, Beobachtungen, Lern-/Schattenzustände und vollständigen
Prognoseausgaben. Ein eigener Exportpuffer schützt vor kurzen Verbindungsproblemen.
Der Archivhost sammelt diese Ereignisse, zusätzliche Wettermodelle einschließlich
echter Ensembles sowie Recorder-/Referenzaufnahmen. Aus eingefrorenen Originalen
können Baseline und spätere Kandidaten mit identischen Eingaben gerechnet werden.

Auf dem Host mit dem [Hostinstaller](archiv-host-installation.md) eine separate
HA-freie Python-Umgebung installieren. Quellcommit und Bibliotheksversionen zusammen mit
jedem Versuch sichern. Datenpins enthalten Originaldaten und Hashes, keine
vollständige Kopie der ausführbaren Softwareumgebung. Ein abweichender Codehash
kann explorativ gerechnet werden, besteht aber keine exakte Baseline-Abnahme.
Dasselbe gilt für eine abweichende HA-Versionsprovenienz: Nach der bewussten
Entfernung von HA Core auf dem Archivhost ist die formale Originalabnahme alter
HA-Aufnahmen nicht mehr quellen-/bibliotheksgleich, auch wenn die Numerik passt.
Die Herkunftsprüfung wird dafür nicht gelockert; [aktueller Runtimevertrag](archiv-runtime-ohne-ha.md).

Private Standortdateien, Zuordnungen, Ausgaben und Archive gehören unter
ignorierte `data/`-Pfade. Eine Standortdatei hat das Schema von
[examples/site.json](../../examples/site.json); für einen Anlagenvergleich müssen
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

Die Hosterweiterung nach 0.2.17 schreibt Originalpakete unter
`originals/<erste-zwei-Hashzeichen>/<vollständiger-Hash>.json.gz`.
Bestehende flache Archive bleiben lesbar. Migration, Rückweg und Kompatibilität
mit älteren Replayumgebungen beschreibt [Hashablage](archiv-hashablage.md).

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

Die bestehenden [Recorder-/Referenzzuordnungen](../entwicklung/benchmark-aufnahme.md) lassen sich
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

Im Entwicklungsstand ergänzt der
[Offline-Qualitätsadapter](istwert-qualitaetsadapter.md) diese Zuordnung:
Er prüft Originalintervalle gegen explizit belegte Quellenbindungen und erzeugt
Stundenmasken samt Ausschlussbericht. Ungeprüfte Bindungen liefern nur
Abdeckungsdiagnosen. Der Adapter ist noch nicht in den Timern aktiviert.

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

Replay-Ausgaben muessen ausserhalb des gelesenen Archivs liegen und duerfen
weder Anlagen-/Kalibrierungseingaben noch das ausgefuehrte Replay-Skript
ersetzen. Beide Replaywerkzeuge pruefen den Pfad vor dem Oeffnen des Archivs
und erneut vor der Veroeffentlichung. Aufgeloeste Pfade sowie bestehende
Symlink-/Hardlinkaliase werden geprueft; auch Pins, Index und Originalpakete
sind geschuetzt. Berichte werden in einer temporaeren Datei neben dem
Ausgabeziel geschrieben und erst nach erfolgreicher Berechnung und
abschliessender Eingangspruefung atomar ersetzt. Vorhandene unabhaengige
Berichte ausserhalb des Archivs duerfen weiterhin ersetzt werden.

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

Datasetexporte verwenden ebenfalls die Hashablage. Für ältere, quellenidentische
Replayumgebungen beim Export `--layout flat` ergänzen. Eine geänderte
Host-Speicherbibliothek verändert den erfassten Quellhash; für die exakte Abnahme
alter HA-Aufnahmen deshalb die ursprüngliche Software auf dieser flachen
Arbeitskopie ausführen. Die Hashprüfung wird nicht gelockert.

Standard ist der jüngste passende `forecast_issued`; `--event-id` wählt eine
bestimmte Ausgabe, `--as-of` begrenzt die damalige Verfügbarkeit. Die numerische
Toleranz beträgt standardmäßig `--tolerance-w 0.000001`. Exakte Abnahme verlangt
zusätzlich übereinstimmende Quell- und Bibliotheksprovenienz. Aktive Lernmodelle
werden aus den tatsächlich verwendeten Fitzeilen am ursprünglichen Fit-Cutoff
rekonstruiert; spätere Beobachtungen sind nicht zulässig.

Seit 0.2.17 werden benannte berechnete Gleitkomma-Zwischenwerte mit der festen
Policy `computed-float-roundoff-v1` verglichen (absolut/relativ jeweils `1e-12`).
So führen kleinste Laufzeit-Rundungsunterschiede bei Sonnenstand/Jahreszyklus
nicht allein zum Fehlschlag. Originaldaten, Zeitunterstützung, Konfiguration,
Gateentscheidungen und Provenienz bleiben streng; die Leistungstoleranz wird
nicht erweitert. Die vollständige Allowlist steht im [Datenvertrag](archive-storage-contract.md).
Ein altes 0.2.16-Archiv wird dadurch nicht automatisch ein quellenidentischer
0.2.17-Datensatz; alte fehlgeschlagene Abnahmen bleiben als solche erhalten.

`--physics-ablation` vergleicht zusätzlich den NWP-Physikpfad ohne lokale
Beobachtungs-/Lernkorrekturen. `Candidate`/`ReplayInputs` in `core/replay.py`
erlauben eigene versionierte Kandidaten auf frisch rekonstruierten identischen
Eingaben. Die seit 0.2.15 verfügbaren Zeitintegrations-/IAM-Parameter können in
einem ausdrücklich versionierten Physikkandidaten verglichen werden; die CLI
aktiviert sie nicht automatisch als zusätzliche Arme.
Ein gelungener Replay ist ein Reproduzierbarkeitsnachweis, kein Genauigkeitsgewinn.

### 5.1 Schattenlernen chronologisch vergleichen

Bei aktiviertem Export werden jetzt zusätzlich die tatsächlichen HA-Berichte
aller konfigurierten Leistungs-, GHI-, Temperatur- und Windquellen erfasst.
Auch unveränderte Werte, `unknown`, `unavailable`, entfernte Zustände und
`restored`-Markierungen bleiben mit Originalzeitstempeln erhalten. Das sind
passive Beobachtungen: Die Integration erzwingt keine Sensoraktualisierung.
Der bestehende Zähler-/Gültigkeits-/Abregelungspfad bleibt erhalten.

Jede erfolgreiche Wetter-/Prognoseberechnung erfasst den Rohzustand aller
konfigurierten Eingänge am Cutoff und jeden Schattenlernversuch: angenommene
und abgelehnte Eingaben, normalisierte Leistung/GHI, Quellzeiten, Qualitätsgründe,
Sonnenstand, Referenzleistungen ohne/mit Direktanteil, berechneten Faktor und
Lernregelversion samt Parametern. Die Schattentabelle vor und nach dem Schritt
bleibt nachvollziehbar. Eine angenommene Messung bedeutet nicht automatisch,
dass das Sonnenstandsfenster schon genug Stützung zur Freigabe hat.

Eine Sitzung beginnt je Coordinator-Instanz neu. Fortlaufende Schrittnummern und
Verweise auf den Vorgänger machen fehlende Exporte sichtbar, auch wenn ein
ausgelassener Schritt keine Tabellenänderung verursacht hätte. Ein unterbrochener
Lernverlauf wird nicht still aus einem späteren Tabellenstand fortgesetzt.

```bash
.venv/bin/python scripts/replay_shading.py --archive data/pilot-01 \
    --source ha-example --dataset pilot-01 --initial-state empty \
    --candidate-min-clearness 0.8 --output data/shade-comparison.jsonl
```

Der Pflichtparameter `--dataset` bindet die Auswertung an einen unveränderlichen
Pin. Für längere Auswertungen eine mit `export-dataset` erstellte Arbeitskopie
verwenden: Die erste Archivdurchsicht hält den Leselock und kann sonst den
Collector aufhalten. Bei mehreren Sitzungen oder alten Aufnahmen ohne den neuen
Vertrag ist `--session-id` ausdrücklich zu setzen; die Fehlermeldung erzwingt
diese Auswahl. Jede ausgewählte Sitzung muss mit Schritt 1 beginnen und bis
zum gewählten Ende lückenlos sein. Neustarts oder Konfigurationsänderungen werden
nicht automatisch zu einer durchgehenden Trainingshistorie verbunden.

Der ursprüngliche Lernverlauf wird aus seinem aufgezeichneten Ausgangszustand
Schritt für Schritt nachgerechnet und gegen Entscheidungen, Folgezustände und
Originalprognosen geprüft. Dieser Ausgangszustand kann schon vor Archivbeginn
gelernt worden sein; er bleibt als nicht nachgewiesene Vorgeschichte markiert.
Die Vergleichsarme besitzen jeweils eine eigene Tabelle:

- `--initial-state empty` lässt beide Arme ab Beginn der erfassten Sitzung neu
  lernen. Das ist kein Nachweis vollständiger Lerndaten vor diesem Beginn.
- `--initial-state recorded` übernimmt für beide Arme denselben damaligen
  Ausgangszustand. Dies ist der Standard und ein bedingter Vergleich ab diesem
  Zustand, kein vollständig neues Training der Vorgeschichte.
- `shade_control` verwendet die ursprünglichen Lernregeln; `clearness_candidate`
  verwendet den expliziten Klarhimmelsanteil als veränderte Aufnahmeschwelle.
  Standardvergleich ist 0,6 gegen 0,8. Das ist ein Versuch, keine empfohlene neue
  produktive Schwelle. `ShadeCandidate` kann außerdem eine eigene versionierte
  Schrittfunktion erhalten.

Die Kandidatenprognosen verwenden dieselben Wetterdaten und Anlagenparameter,
jeweils ihre eigene gelernte Tabelle und reine PV-Physik. Die bisherige
Residualkorrektur und der Beobachtungs-Nowcast werden dabei nicht übernommen.
So stammen Unterschiede zwischen den beiden Armen aus ihrem Schattenlernen.
Ein separater Replay prüft weiterhin die vollständige ursprüngliche Prognose.

Ausgabe ist JSONL mit einem Datensatz je Schritt und einem abschließenden
`summary`. Erst nach erfolgreicher Verarbeitung und abschließender Pinprüfung
wird die Datei veröffentlicht; ein struktureller Fehler hinterlässt kein
scheinbar vollständiges Teilergebnis. Ein numerischer/Software-Baselinefehler
wird im Ergebnis und mit Fehlercode ausgewiesen. Standardmäßig sind höchstens
256 MiB deklarierte dekomprimierte/serialisierte Eingaben je Schritt erlaubt
(`--max-decoded-mib`). Das begrenzt keine Python-Spitzen-RAM-Belegung. Es werden
keine vollständigen historischen Fit- oder Ergebnisreihen im RAM gesammelt;
Tabellen, Identitäten und Auswahlmetadaten bleiben erforderlich.

Der Replay arbeitet an den ursprünglichen Berechnungszeitpunkten. Für ein
Verfahren mit anderer Lerntaktung braucht es einen zusätzlichen Treiber auf
den jetzt vorhandenen Rohberichten. Ein akzeptierter Replay an den ursprünglichen
Cutoffs bestätigt nicht automatisch die Lückenlosigkeit aller Rohberichte
dazwischen; dafür sind Exportlücken und Quellenabdeckung zusätzlich zu prüfen.
Eine echte Genauigkeitsbewertung benötigt
spätere, qualifizierte Istwerte auf gemeinsamen Zielintervallen; der Bericht
kennzeichnet sie derzeit als `unevaluated:no_qualified_paired_actuals`.

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
