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

Der aktuelle Installationsnachweis wird nach erfolgreichem Hostreadback ergänzt.
