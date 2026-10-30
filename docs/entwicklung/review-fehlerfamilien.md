# Fehlerfamilien gemeinsam prüfen

Stand: 30.10.2026, Entwicklung nach `5a53b08`; keine neue Releaseabnahme.
Dieser Ablauf ergänzt die [Validierung](validierung.md#4-lokale-prüfung-und-review).
Transferfreigaben, Quellhashbindung und die Sicherheitsgrenzen externer Reviewer
bleiben unverändert. Ein lokaler Subagentenreview ist kein Provider-Vollreview.

## Vorgehen bei Befunden

1. Den Fehler am alten Stand reproduzieren und die verletzte Regel benennen.
   Beispielsweise: Eine Berichtausgabe darf keine Eingabe überschreiben und
   keinen fremden Baum im Originalarchiv anlegen.
2. Alle Einstiegspunkte derselben Fehlerfamilie erfassen, bevor ein Nachreview
   startet. Schreibende Helfer anhand der folgenden Tabelle prüfen; bei
   Zeitfehlern alle Ausgabe-/Empfangs-/Zielgrenzen, bei Vergleichsfehlern alle
   betroffenen Auswertungsarme und Kennzahlen verfolgen. Bei Einheitenfehlern
   sämtliche numerischen Eingangsklassen sowie Metadatenwechsel, Unterbrechung
   und Wiederanlauf der Messkontinuität über native HA-Ereignisse prüfen.
3. Bestätigte Geschwisterfälle gemeinsam korrigieren. Regressionen prüfen das
   beobachtbare Ergebnis einschließlich Originalerhalt und zulässiger Fälle;
   sie spiegeln nicht lediglich die neue Implementierung. Mindestens einen
   tatsächlichen Einstiegspunkt durchlaufen: Ein korrekter Schutzhelfer genügt
   nicht, wenn sein Aufrufer zuvor einen Symlink auflöst und dessen Identität
   verwirft. Native HA-Pfade zusätzlich ohne verändernde Testadapter prüfen,
   wenn diese Threadwechsel oder verzögerte Callbacks verdecken können.
4. Ein anderer Bearbeiter prüft die Korrektur und ihre Aufrufer gezielt. Befunde
   als konsolidierte Liste zurückgeben; die erste Entdeckung beendet die Suche
   innerhalb des vereinbarten Umfangs nicht. Gegenbeweise dürfen einen Befund
   widerlegen, ohne vorsorglich Produktionslogik hinzuzufügen.
5. Nach Abschluss aller Familienprüfungen die integrierte Änderung einmal
   insgesamt prüfen und die erforderliche Testsuite ausführen. Neue Änderungen
   oder konkrete offene Risiken können weitere Prüfungen erfordern. Es gibt
   weder eine feste Ein-Review-Garantie noch automatische Wiederholungen eines
   Vollreviews nach jedem einzelnen Fix.

Prüfbericht und Urteil nennen den tatsächlichen Umfang, Quellstand, Prüfer und
Nachweisgrenzen. Ein fokussierter Nachreview ersetzt keinen behaupteten neuen
Vollreview. Alte akzeptierte Receipts gelten weiterhin ausschließlich für ihre
ursprünglichen Bytes. Frühere Reviewurteile als historischen Kontext kennzeichnen;
eine ausdrücklich unabhängige Erstsuche erhält sie erst beim Ergebnisabgleich.
Ein Volltextscope wird dafür nicht stillschweigend gekürzt.

## Inventur der Schreibwege

Die Tabelle erfasst die Python-CLI-Einstiegspunkte dieses Entwicklungsstands
einschließlich indirekter Schreiber. Sie ist eine Wartungsübersicht, kein
Nachweis gegen beliebige gleichzeitige Manipulationen des Dateisystems.
Bei neuen Helfern oder neuen Schreibarten die passende Zeile ergänzen.

| Einstiegspunkt | Schreibart / Ziel | Schutzregel und Zuständigkeit |
| --- | --- | --- |
| `forecast.py`, `evaluate.py` | Bericht atomar ersetzen | `replay_paths`: Eingaben, Programme und Ressourcen erhalten; Ziel vor Lesen und Veröffentlichung prüfen |
| `analyze_learning_support.py`, `qualify_actuals.py` | Bericht atomar ersetzen | Gemeinsamer Programmschutz und sämtliche expliziten Daten-/Policy-/Qualitätseingaben |
| `continuous_quality.py`, `replay_archive.py` | Bericht atomar ersetzen | Zusätzlich außerhalb der Quellarchivwurzel, lexikalisch und aufgelöst |
| `replay_shading.py` | Temporären JSONL-Bericht atomar veröffentlichen | Gemeinsamer Ausgabeschutz vor Ausgabe und Veröffentlichung; Quell-/Pinprüfung vor Veröffentlichung abschließen |
| `capture_actuals.py`, `capture_ha.py` | JSONL anhängen | Dedizierte Datei, Elternpfad vor Abruf festhalten und Dateiname für Symlinksperre erhalten; private Grenze vor/nach Abruf, Eingaben/Programme, geöffneten Deskriptor und Pfadidentität prüfen; vollständige Altzeilen erhalten |
| `archive.py export-observations` | Neue Exportdatei veröffentlichen | Ziel außerhalb des Quellarchivs; Veröffentlichung ohne Überschreiben bestehender Ziele |
| `archive.py export-dataset` | Neues Exportverzeichnis | `ArchiveStore.export_dataset`: neues Ziel außerhalb der gesamten Quellarchivwurzel; Originale und Pins erhalten |
| `archive_host.py` | Status atomar ersetzen; Writerlock öffnen | Statusverzeichnis und alle festen Status-/Locknamen vor Anlage gegen Archiv, Hostkonfiguration und konfigurierte Eingabedateien prüfen |
| `archive.py collect`, `capture_weather.py`, `archive_observations.py` | Originale aufnehmen, Index fortschreiben | `ArchiveStore` besitzt den ausdrücklich gewählten Archivbaum; keine Berichtausgabe in dessen Originalablage |
| `archive.py pin`, `maintain`, `migrate-layout`, `rebuild-index` | Archivverwaltung, teils Löschen/Umordnen | Native Archivoperationen mit eigenen Pin-/Hash-/Transaktionsregeln; keine allgemeinen Berichtschreiber |
| `archive.py stats`, `verify`; Replay-/Qualitätsleser | Archiv öffnen und ggf. abgeleiteten Index abgleichen | Ein Archivleser ist nicht automatisch frei von Dateischreibzugriffen; Originalprüfung bleibt Pflicht |
| `install_archive_host.py` | Venv anlegen; Pakete installieren | Explizit gewählte isolierte Hostumgebung; eigener Installationsauftrag, keine Ausführung bei einem bloßen Quellreview |
| `build_haos_wheel.py` | Neuer Buildbaum, Downloads und Buildausgaben | Neues direktes Unterverzeichnis des dedizierten `/work`-Mounts; vorhandene Ziele nicht wiederverwenden |
| `review.py` | Neue private Reviewablage und Laufartefakte | Neues Verzeichnis unter `reviews/private/`; Scope/Transfer/CLI-Audit separat, kein Schreiben in Quellarchive |

`replay_paths.py` und `actual_quality_io.py` sind gemeinsame Hilfsmodule ohne
eigene CLI-Ausgabe. Die native HA-Persistenz verwendet feste `Store`-Schlüssel;
das Exportjournal verwendet `ArchiveJournal`. Deren Lebenszyklus, Migration und
Retention gehören zur HA-/Archivprüfung, nicht zum Schutz frei gewählter
Berichtziele. Shell-/systemd-Installation und native Providerwerkzeuge sind
gesonderte Betriebs- beziehungsweise Reviewabläufe.

Für eine betroffene Tabellenzeile mindestens Eingabekollision, Programmkollision
und gegebenenfalls Archivkollision beurteilen. Direkte Pfade sowie die bereits
unterstützten Symlink-/Hardlinkfälle beachten. Eine Grenze auf `data/` allein
schützt keine Eingaben oder über Hardlinks erreichbaren Inodes. Atomarer Ersatz
und Append sind unterschiedlich: Append verändert den geöffneten Inode.
Bei einer Pfadkorrektur auch prüfen, ob ein bisher festgehaltener Elternalias
nun über einen Netzabruf hinweg neu aufgelöst wird. Die CLI-Regressionen prüfen
sowohl das Umhängen des ursprünglichen Alias als auch eine ersetzte Zielwurzel.

## Bewusst getrennte weitere Arbeit

Der Support-Guard bleibt ein Offlineexperiment mit unveränderter Policy. Weitere
Schwellen oder automatische Aktivierung benötigen qualifizierte prospektive
Vergleiche; Tests und Review allein liefern diesen Nachweis nicht.

Die Verlagerung von Offlineanalysemodulen aus der ausgelieferten Integration ist
ein eigener späterer Schritt. Der derzeitige Producerhash umfasst weiterhin alle
Pythondateien der Integration. Eine Auslagerung muss Paket-/Importpfade,
Hostinstallation und alte Replays prüfen; der Runtime-Producerpin darf dabei
nicht durch eine ungeprüfte Liste angeblich relevanter Dateien abgeschwächt werden.
Archivscans erst anhand von Laufzeit und Datenumfang bewerten, bevor zusätzliche
Indizes oder Caches eingeführt werden.
