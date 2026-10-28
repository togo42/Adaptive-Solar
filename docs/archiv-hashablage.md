# Hierarchische Originalablage nach Prüfsumme

Stand: 28.10.2026. Hosterweiterung auf Basis von 0.2.17; keine neue veröffentlichte
HA-Version. Die Umstellung betrifft die Archivdateien, nicht deren Datenformat,
Messauflösung, Aufbewahrungsfrist oder Prognoseverfahren.

## Ablage und Kompatibilität

Neue Originalpakete liegen unter
`originals/<erste-zwei-Hashzeichen>/<vollständiger-Hash>.json.gz`. Die bis zu
256 Unterverzeichnisse entstehen bei Bedarf mit privaten Verzeichnisrechten.
Der Hash bezeichnet unverändert den unkomprimierten Originalwrapper. Datum,
Quelle und Sequenz bleiben im Original und im wiederaufbaubaren SQLite-Index.

Leser, Indexwiederaufbau, Referenzauflösung, Pins, Retention und Datasetexport
unterstützen flache und hierarchische Archive sowie gemischte Bestände. Pins,
Dateinamen und komprimierte Originalbytes ändern sich durch die Migration nicht.
Die globale Dateiliste wird weiterhin beim Öffnen und vor einer Aufnahme
abgeglichen. Die Hierarchie begrenzt die Dateien je Verzeichnis, beseitigt aber
nicht diesen mit der Gesamtdateizahl wachsenden Aufwand.

## Migration und Rückweg

Vor der Umstellung die Archivtimer stoppen, laufende Archivdienste auslaufen
lassen, den gemeinsamen Runnerlock exklusiv halten und eine geprüfte lokale
Kopie des Archivs einschließlich Index und Pins sichern. Die folgenden Befehle
mit der neuen Software und dem tatsächlichen privaten Archivpfad ausführen:

```bash
.venv/bin/python scripts/archive.py --root data/archive verify
.venv/bin/python scripts/archive.py --root data/archive migrate-layout
.venv/bin/python scripts/archive.py --root data/archive verify
```

Die Migration prüft vor der ersten Verschiebung alle Originale. Ein Hardlink
veröffentlicht die vorhandenen Bytes ohne Überschreiben; erst nach erfolgreicher
Synchronisation des Zielverzeichnisses wird der alte Name entfernt. Beide Namen
liegen im selben Dateisystem. Ein unterbrochener Lauf lässt sich wiederholen;
fehlende oder beschädigte Daten werden nicht durch eine Migration repariert.
Beim Auslaufen der Retention werden beide möglichen Pfade berücksichtigt.

Für einen Rollback zuerst wieder Timer stoppen und Schreiber abwarten. Dann
mit der neuen Software `migrate-layout --layout flat` und `verify` ausführen,
erst danach den bisherigen Releasepfad aktivieren. Leere Präfixverzeichnisse
dürfen bleiben. Die vorherige Software kann hierarchische Originale nicht lesen.
Private Konfigurationen und Zugangsdaten werden nicht geändert.

## Replays mit ursprünglicher Software

Der gesamte Komponentenquellhash gehört zur exakten Replayabnahme. Auch die
Änderung der Speicherbibliothek verändert diesen Hash. Eine Hostaktualisierung
darf deshalb keine falsche Quellenidentität zu alten HA-Aufnahmen behaupten.
Für einen Replay mit dem ursprünglichen Release eine flache Arbeitskopie erzeugen:

```bash
.venv/bin/python scripts/archive.py --root data/archive export-dataset \
    pilot-01 data/pilot-01-flat --layout flat
```

Anschließend den Replay mit der ursprünglichen quellen- und bibliotheksgleichen
Software auf dieser Kopie ausführen. Die alte Releaseumgebung bleibt beim
Hostupgrade erhalten. Für neue Werkzeuge bleibt der hierarchische Datasetexport
der Standard. Die Replaytoleranzen werden nicht verändert.

## Validierung

Verhaltenstests prüfen neue Aufnahmen, gemischte Bestände, Migration in beide
Richtungen, bytegleichen Inhalt, unveränderte Pins/Checkpoints, Indexwiederaufbau,
Referenzen, Retention und flache Kompatibilitätsexporte. Fehlerfälle umfassen
Abbrüche beim Verlinken, Synchronisieren und Entfernen, korrupte Kopien, falsche
Präfixe sowie Datei-/Verzeichnissymlinks. Die betroffenen bestehenden
Archivtests prüfen nun auch die hierarchischen Originalpfade.

Lokale Prüfung: **1.648 Tests ohne Skips** in der vollständigen Suite bestanden.
Ein danach ergänzter Gegenfall für zwei gültige, aber unterschiedlich komprimierte
Kopien bestand ebenfalls; alle **15 Migrationstests** sind erfolgreich. Ruff für
Komponente, Skripte und Tests, `pip check` sowie Diffprüfung bestanden.

## Installierter Stand auf dem Archivhost

Die Hostinstallation vom 28.10.2026 verwendet Commit
`ce6173a9baeec2504861287e14b431e6c9ad0ebc`. Der öffentliche Transferumfang
(185 Dateien) wurde gegen das lokale Quellmanifest geprüft; SHA256 des
Transferarchivs: `c6e5ee83d29386ad3b5f8c16dbc91e745ea273455a6381ab9d9ee43c6e2dd7b7`.
Die bestehende 0.2.17-Pythonumgebung wird mit unveränderten Abhängigkeiten genutzt;
der bisherige Releasebaum und eine geprüfte lokale Archivkopie bleiben erhalten.

- **524 Originaldateien / 22.979 Ereignisse** vor der Migration gesichert.
- Alle 524 Originale in **230 belegte Präfixverzeichnisse** verschoben;
  komprimierte Bytes, Pins, SQLite-Index und sämtliche Checkpoints unverändert.
- Unabhängige Archivkopie allein aus Originalen und Pins mit neu aufgebautem
  Index erfolgreich geprüft; identische Batches, Ereigniszahl und Checkpoints.
- Vier Timer wieder aktiv und weiterhin aktiviert. Kontrollierte HA-, Wetter-
  und Beobachtungsläufe erfolgreich mit dem neuen Release ausgeführt.
- Bei der Abnahme **539 Originale**, davon **15 neue Pakete** ausschließlich
  in Hashverzeichnissen. Neue Quellenberichte, Prognosen, qualifizierte
  Messintervalle, acht Wetterantworten und zwei Beobachtungsaufnahmen vorhanden;
  keine gemeldeten Exportlücken oder Exportfehler in diesen neuen Paketen.
- Flacher Export einer eingefrorenen Arbeitskopie mit dem ursprünglichen
  0.2.17-Leser erfolgreich geprüft. **Vier Originalreplays akzeptiert**,
  einschließlich striktem Softwareabgleich; maximale Leistungsabweichung
  `9,095e-13 W` bei unverändert `1e-6 W` Leistungstoleranz.

Die Installation betrifft ausschließlich den Archivhost. HA-Code, Einstellungen
und Lernhistorie wurden nicht verändert. Diese Prüfungen belegen die Migration
und begrenzte Reproduzierbarkeit, keine zusätzliche Prognosegenauigkeit oder
langfristig ausreichende Speicherkapazität. Private Migrations-/Prüfbelege liegen
lokal unter `data/archive-hash-layout-20261028/`; vollständige Archive und
Rückwegkopien bleiben auf dem Archivhost. Die unveränderte tägliche PBS-Sicherung
ist davon getrennt; eine vollständige LXC-Rücksicherung wurde hier nicht getestet.
