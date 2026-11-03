# Archivhost dauerhaft betreiben

Der HA-Job prueft ausser dem Child-Exitcode dessen strukturierten
Collector-Abschluss. Cursorluecken, fehlender Abschluss am Seitenlimit,
Producer-Schreibfehler, offene Producer-Schreibvorgaenge oder fehlende
Statusbelege ergeben `complete=false` und einen fehlgeschlagenen Hostlauf.
Die Statusdatei nennt nur feste Statuswerte, Zaehler und Fehlerbooleans;
rohe Producerfehler, Endpunkte, Tokens und Quellen-IDs werden nicht ins
Journal uebernommen. Bestaetigte Checkpoints bleiben fuer den naechsten
Lauf erhalten. Normale Pufferretention ohne Cursorverlust zaehlt nicht
als neue Abholluecke. Für den HA-Collector kann der Abschluss die feste,
aus dem ersten Exportstatus belegte Sequenzgrenze bestätigen. Neue Ereignisse
verschieben diese Grenze nicht; ohne passende Metadaten bleibt eine leere
Abschlussseite erforderlich. Ein erfolgreicher Lauf bedeutet daher nicht,
dass die laufende Quelle dauerhaft leer ist. Details stehen im
[Seiten- und Abschlussvertrag](archive-storage-contract.md#seiten-lücken-und-wiederanlauf).
Collector und Runner müssen einen kompatiblen Statusvertrag verwenden;
eine reine Codevorbereitung ändert keinen bestehenden Hostdienst. Die begrenzte
HA-Sammlung nutzt vorhandene Producer-Metadaten und benötigt kein neues
Seitenschema oder HA-Update. Ein bestehender Prüfplan mit festen Softwarepins
muss vor einem Hostupdate abgeschlossen oder ausdrücklich neu festgelegt werden.

Stand: 02.11.2026. Die Vorlagen unter `deploy/` und der Runner
`scripts/archive_host.py` bereiten den Hostbetrieb vor. Ihre Existenz bedeutet
keine Aktivierung. HA-Exportoptionen und produktive Hoständerungen benötigen den
konkreten Inbetriebnahmeauftrag. Grundlagen und Datenvertrag stehen in
[Archivbetrieb](archivbetrieb.md) und
[Speicherentscheidung](archiv-speicherung-und-transport.md).

## Installation und private Dateien

Auf dem Archivhost eine eigene Installation verwenden:

```text
~/adaptive-solar-archive/
  releases/QUELLCOMMIT/          Repository und eigene .venv
  current -> releases/QUELLCOMMIT
  data/                        private Zuordnungen, Status und Archiv
```

Jede Releasekopie erhält `data -> ../../data`. Der Pfad `data/` muss ignoriert
bleiben. Den vollständigen Quellcommit vor dem Transfer festhalten und danach
Dateihashes prüfen. Für Erstinstallation und Updates ausschließlich den
Hostinstaller mit Python ab 3.13 verwenden:

```bash
python3 scripts/install_archive_host.py --venv .venv
```

Er installiert das reguläre Paket und die Versionspins aus dem HA-Manifest,
ohne Entwicklungs-/HA-Extras. Die verpflichtenden
`deploy/archive-host-constraints.txt` schließen HA Core und dessen Testharness
auch als versehentliche transitive Abhängigkeit aus. Vor und nach der Installation
prüft der Installer die isolierte Umgebung und die Abwesenheit von HA;
`pip check` ist Pflicht. Eine bereits mit HA bestückte Umgebung wird abgelehnt.
Geerbte Pip-Ziele und Konfigurationsdateien werden deaktiviert; der Postflight
prueft reale Laufzeitimports und deren Lage im Ziel-venv. Einzelheiten und
Regressionen stehen unter [Runtimeisolation](archiv-runtime-ohne-ha.md).
Bei einem Release mit `.venv`-Symlink den tatsächlichen, privaten Umgebungspfad
an `--venv` übergeben. Gemeinsame Umgebungen nur bei pausierten Archivschreibern
aktualisieren; einen neuen Stand bevorzugt in einer separaten Umgebung vorbereiten.

`--constraints data/runtime-pins.txt` bindet zusätzliche numerische
Laufzeitversionen. Diese Datei darf keine HA-Installation verlangen.
Die CI baut separat eine echte HA-freie Archivumgebung und importiert sämtliche
Collector-/Replay-CLIs; native HA-Tests bleiben in ihrer Entwicklungsumgebung.
Für einen exakten Replay außerdem die vollständigen numerischen Laufzeitversionen
mit der ursprünglichen HA-Umgebung abgleichen und protokollieren; zwei direkte
Pins allein beweisen keine identische Umgebung. Die unveränderte strenge
Replayprüfung vergleicht zusätzlich die aufgezeichnete HA-Version. Für alte
HA-Aufnahmen fehlt nach deren bewusster Entfernung diese Versionsgleichheit:
Numerische Reproduzierbarkeit und formale Originalabnahme bleiben getrennt.
[Umstellung und Nachweis](archiv-runtime-ohne-ha.md).

`deploy/archive-host.example.json` als private `data/host.json` übernehmen und
Standort, Messgrenzen, Referenzen und eindeutige dauerhafte Quellen eintragen.
`weather_source` und `observations_source` bleiben von allen HA-Quellen getrennt;
der Beobachtungscollector hängt `:actuals` und `:references` an seine Basisquelle.
Die Standortdatei folgt `examples/site.json`. Alle privaten Eingabedateien bleiben
unter dem tatsächlichen gemeinsamen `data/`-Verzeichnis. Kein Token gehört in
diese Dateien. Eine optionale `quality`-Datei muss nachgewiesene Intervallqualität
enthalten; ohne sie wird Rohenergie bewahrt, aber nicht als Trainingswahrheit
qualifiziert. Alternativ aktiviert der optionale Schlüssel `quality_bindings`
eine neue Ableitung je Aufnahme aus einer privaten v2-Policy. Er setzt
`actual_config` voraus und darf nicht zusammen mit `quality` gesetzt sein.
Quellenqualifikation, Ankererhalt und der
[lokale Probelauf](istwert-qualitaetsadapter.md#5-fortlaufende-quellenbindung-und-qualitätsaufnahme)
sind vor einer Hostaktivierung zu prüfen. Diese Funktion ist ab Release 0.2.20
enthalten; ein HA-Update aktualisiert oder aktiviert den externen Host nicht.

`quality_diagnostics` wählt optional `compact` oder `full`; ohne Schlüssel gilt
weiterhin `full`. Die Beispielkonfiguration empfiehlt `compact`: Die vollständige
Qualitätsableitung und ihre Gates bleiben erhalten, umfangreiche Beleglisten im
Capture werden aber durch ausdrücklich gekennzeichnete Hash-/Anzahlbelege ersetzt.
Stundenentscheidungen und Gründe, Masken, Konflikte, Quell-/Policy-/Codebindungen
und echte Zeitstempel bleiben enthalten. Das Profil wird nur an `actuals` oder
den kompatiblen `observations`-Job weitergegeben; der Referenzabruf verwendet es
nicht. Details stehen beim [Qualitätsadapter](istwert-qualitaetsadapter.md).

## Zugangsdaten ohne dauerhafte Klartextdatei

Die HA-lesenden Dienste (`ha`, `actuals`, `references` beziehungsweise der
bisherige kombinierte Dienst `observations`) verwenden `LoadCredentialEncrypted=ha-auth:…`
mit `~/.config/adaptive-solar-archive/ha-auth.cred`. Der entschlüsselte Inhalt ist
ein JSON-Objekt mit genau `HA_URL` und `HA_TOKEN`. Nur der Runner liest die von
systemd für den Dienst bereitgestellte Laufzeitdatei und setzt die Werte in der
Prozessumgebung seiner Kinder. Wetterabruf und Retention benötigen diesen Zugang
nicht. Der HA-Exportdienst verlangt einen Administratorzugang.

Die neue Credentialdatei aus einem bereits autorisierten geschützten Zugang über
stdin verschlüsseln; weder Tokenargumente noch Shell-History oder temporäre
Klartextdateien verwenden. Vorher nativ prüfen, ob `systemd-creds --user encrypt`
mit einem sicheren vorhandenen Schlüssel funktioniert. Einen fehlenden Hostschlüssel
gegebenenfalls separat administrativ einrichten. `--with-key=null` ist keine
geeignete Verschlüsselung. Ohne sichere Credentialbereitstellung die
HA-lesenden Dienste nicht aktivieren. Vorhandene Helios-/ESS-Zugänge und deren
Dienste bleiben unverändert.

## Timer und erste Aufnahme

Für die getrennte Aufnahme die zehn Unitdateien für `ha`, `weather`, `actuals`,
`references` und `retention` aus `deploy/` nach `~/.config/systemd/user/`
übernehmen. Die beiden bisherigen `observations`-Vorlagen bleiben für kompatible
Bestandsinstallationen erhalten und werden dabei nicht zusätzlich aktiviert.
`loginctl show-user "$USER" -p Linger`
muss für einen Betrieb ohne Login `Linger=yes` liefern. Timer verwenden die
angegebene Zeitzone, sonst die des Hosts, und holen nach einem Ausfall einmalig
einen fälligen Lauf nach.

| Aufgabe | Zeitpunkt |
| --- | --- |
| HA-Originalexport | alle fünf Minuten |
| Zusätzliche Wettermodelle | stündlich Minute 03 |
| Recorder-Istwerte und Qualitätsableitung (`actuals`) | alle sechs Stunden um 00:12, 06:12, 12:12 und 18:12 UTC; 72 Stunden Rückblick, zehn Minuten Reserve |
| Referenzprognosen (`references`) | stündlich Minute 24 UTC |
| Retention | täglich 03:37, 24 Kalendermonate, Pins bleiben erhalten |

Vor dem Aktivieren jeden Dienst einmal kontrolliert starten. Erst nach erfolgreichem
Original-/Cursor-/Quellenreadback, Kapazitätsprüfung und Statusprüfung die fünf Timer
mit `systemctl --user enable --now adaptive-solar-archive-{ha,weather,actuals,references,retention}.timer`
aktivieren. Der gemeinsame Dateilock serialisiert sämtliche Runneraufgaben.
Einzelne fehlerhafte HA-Einträge verhindern keine Aufnahme der anderen Einträge;
der Gesamtlauf meldet trotzdem Fehler. Ein Dienststart veröffentlicht keine
Prognose und verändert keine HA-Modelloption.

`actuals` reicht ausschließlich `actual_config` und die optionale `quality` oder
`quality_bindings` weiter, `references` ausschließlich `reference_config`.
Jeder Job verlangt seine eigene Mapping-Datei. Damit löst der stündliche
Referenzabruf keine Recorderaufnahme oder Qualitätsableitung aus. Basisquelle,
Suffixe `:actuals`/`:references`, Checkpoints, Rückblick und Qualitätsgates bleiben
erhalten. Referenzprognosen sind eine Aufnahme des jeweils verfügbaren Stands;
der 72-Stunden-Parameter begrenzt nur die Recorder-Istwerte und rekonstruiert
keine früheren Referenzstände. Ein seltenerer Actuals-Lauf macht die abgeleiteten
Qualitätsnachweise entsprechend später verfügbar; er qualifiziert keine Quelle.

Die Actuals-Frequenz lässt sich ohne Host-JSON-Erweiterung über ein systemd-Drop-in
ändern. Zum Beispiel setzt `systemctl --user edit adaptive-solar-archive-actuals.timer`
mit folgendem Inhalt einen Zwölfstundenrhythmus:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 00/12:12:00 UTC
```

Vor einer autorisierten Aktivierung den Kalender mit `systemd-analyze calendar`
prüfen, `daemon-reload` ausführen und den betroffenen Timer neu starten. Die leere
erste `OnCalendar=`-Zeile entfernt den geerbten Kalender; andernfalls würden beide
Zeitpläne gelten. Längere Ausfälle können trotz `Persistent=true` Lücken jenseits
des unveränderten 72-Stunden-Rückblicks hinterlassen. Die Timerfrequenz ändert
weder die HA-Producerfrequenz noch bestehende Originale.

### Bestehenden kombinierten Beobachtungslauf umstellen

Diese Schritte sind eine vorbereitete Migration, keine automatische Änderung
einer vorhandenen Installation. Der alte Job `observations` und seine stündliche
Timerdatei bleiben unverändert nutzbar und verwenden weiterhin beide konfigurierten
Mappings. Die Existenz neuer Vorlagen ändert keinen installierten Timer.

1. Vorher Softwarestand, Unit-/Drop-in-Dateien und aktive/aktivierte Timerzustände
   sichern; neue Software und Units zunächst ohne Aktivierung bereitstellen.
2. Nur `adaptive-solar-archive-observations.timer` stoppen und deaktivieren.
   Einen bereits laufenden `observations.service` vollständig abwarten; nicht
   zusammen mit den neuen Jobs weiterbetreiben. Der Writerlock verhindert zwar
   gleichzeitige Schreibvorgänge, aber keine doppelten Aufnahmen nacheinander.
3. Neue Units mit `daemon-reload` laden. Beide neuen Dienste einzeln kontrolliert
   aufnehmen lassen und `actuals.json` beziehungsweise `references.json`,
   Quellenidentitäten, Originale und fortgeschriebene Checkpoints prüfen.
4. Erst nach erfolgreicher Abnahme die neuen `actuals`- und `references`-Timer
   aktivieren. `observations.timer` bleibt inaktiv und deaktiviert. Die bisherigen
   `ha`-, `weather`- und `retention`-Timer behalten ihre Zustände.

Für den Rückweg zuerst beide neuen Timer stoppen und deaktivieren und ihre
laufenden Dienste abwarten. Dann die gesicherten alten Units/Drop-ins laden und
den zuvor aktiven `observations`-Timer wiederherstellen. Niemals kombinierte und
getrennte Beobachtungstimer parallel aktivieren. Das gemeinsame Archiv, die
Quellen und ihre Checkpoints werden weder zurückgesetzt noch umbenannt. Ein
Software-Rollback verlangt zusätzlich die weiter unten beschriebene Prüfung der
Archivformat- und Leserkompatibilität.

## Kapazität und Betriebsnachweis

Der Runner prüft vor jeder Aufnahme den freien Dateisystemplatz und die tatsächlich
belegten Archivdateiblöcke einschließlich Staging. Voreinstellung: mindestens
2 GiB freier Platz, zusätzlich 1 GiB Reserve je Operation, mindestens 15 Prozent
freier Dateisystemplatz und höchstens 4 GiB Archivbudget einschließlich Reserve.
Bei unterschrittener Schwelle beginnt keine weitere Aufnahme. Eine bereits
laufende Operation wird dadurch nicht abgebrochen; die Reserve ist keine
bewiesene Obergrenze ihrer Spitzenbelegung. Retention und Status bleiben möglich.
Diese Schutzschwellen sind ein begrenzter Pilotbetrieb, keine Zusage für zwei Jahre.

Je Aufgabe liegt ein atomar aktualisierter privater Nachweis unter
`data/host-status/JOB.json`. Er enthält Erfolg, einzelne Rückgabecodes,
Kapazität, Archivgröße und die aus der bisherigen Rate geschätzten komprimierten
24-Monatsbytes. Staging, Dateisystemreserve, Indexwachstum und Backups kommen zu
dieser Projektion hinzu. Eine kurze Beobachtungsdauer erlaubt keine belastbare
Langfristprognose. Jobfehler und Kapazitätsstopp erscheinen zusätzlich als
fehlgeschlagener systemd-Dienst; das ist noch keine externe Alarmierung.

`status_dir` darf einen anderen privaten Statusordner wählen. Der Ordner,
`writer.lock`, sämtliche sieben Jobnachweise und deren feste
`JOB-runtime.json`-Sidecars müssen außerhalb des Archivs
liegen, sowohl nach ihrem konfigurierten Pfad als auch nach Symlinkauflösung.
Sie dürfen weder die mit `--config` gelesene Hostkonfiguration noch konfigurierte
Standort-, Istwert-, Referenz- oder Qualitätsdateien oder Programmdateien
überlagern; vorhandene Symlink- und Hardlinkaliase werden ebenfalls abgelehnt.
Der Runner prüft diese Grenzen für alle Aufgaben vor der ersten
Verzeichnisanlage. Eine ungültige Konfiguration endet mit Exitcode 2 und
schreibt keinen Status. Insbesondere sind `data/archive/originals/status` und
eine Hostkonfiguration unter `data/host-status/status.json` unzulässig.
Der Standard `data/host-status` bleibt erhalten.

Das optionale [native Qualitätsbackend](native-qualitaetsbackend.md) wird nur
über die zusammengehörigen privaten Felder `quality_backend_manifest` und
`quality_backend_manifest_sha256` aktiviert. Standard bleibt Python. Die
Aktivierung benötigt eigene Source-/Binär-/Runtimepins und eine kontrollierte
Hostabnahme; sie verändert weder Timer noch Qualitätsgates oder HA-Einstellungen.

Der Repository-Runner ergänzt einen per `run_id` korrelierten, begrenzten
`JOB-runtime.json`-Nachweis. Er trennt Timeout und Betriebssystemfehler beim
Kindstart, misst Lockwartezeit, Kapazitätsprüfung, Kindaufruf, Statistik,
tatsächliches Ergebnisschreiben und Lockschluss. Wandzeiten sind monoton;
CPUzeiten gelten nur für den jeweiligen Prozess und enthalten bei
`child_run` keine KindCPU. Die eigene Sidecarveröffentlichung ist ausgenommen.
Fehlende oder nicht zur `run_id` passende Sidecars sind eine Nachweislücke;
ein Telemetrie-Schreibfehler startet keine zweite Erfassung. API, Teilergebnisse
und Aussagegrenzen beschreibt [Laufzeittelemetrie](../entwicklung/archiv-laufzeittelemetrie.md).
Die getrennten Aufgaben `actuals` und `references` behalten ihre eigenen
Nachweise; `observations` bleibt für bestehende kombinierte Installationen erhalten.

```bash
current/.venv/bin/python current/scripts/archive_host.py status --config current/data/host.json
systemctl --user list-timers 'adaptive-solar-archive-*'
systemctl --user --failed
```

Vorher die eigene Arbeitsposition beachten: Der Runner löst relative private
Pfade gegen seine Releasewurzel auf. Die Statusabfrage führt denselben Indexabgleich
wie der Collector aus und ist deshalb durch den gemeinsamen Lock geschützt.
Nach ausreichenden Pilotdaten Speicherbedarf, Backup und Wiederherstellung prüfen;
nach drei und sechs Monaten die Speicherentscheidung erneut bewerten.

## Layoutmigration und Rollback

Für die Hosterweiterung nach 0.2.17 beschreibt [Hashablage](archiv-hashablage.md)
die Migration bestehender Originale in Präfixverzeichnisse sowie den Rückweg vor
einem Rollback auf ältere Software. Neue Leser unterstützen beide Layouts;
alte Leser benötigen einen flachen Bestand. Die Historie der HA-Integration wird
durch diese Hostmigration nicht verändert.

## Sicherung und Wiederherstellung

Den tatsächlichen Archivpfad, Index, Pins und die privaten Zuordnungen in
die bestehende Hostsicherung einbeziehen. Ob eine LXC-/VM-Sicherung oder
eine andere vorhandene Sicherung diese Pfade abdeckt, muss für die eigene
Installation geprüft werden; ein zusätzlicher Backupdienst ist dafür
nicht automatisch erforderlich. Bei einem separaten Volume dessen
Einbeziehung ausdrücklich kontrollieren.

Die 24-Monats-Aufbewahrung der Originale und die Backupaufbewahrung sind
getrennte Einstellungen. Eine aus Originalen wiederaufgebaute Archivkopie
belegt keine vollständige Hostwiederherstellung. Sicherung, Entschlüsselung
und Restore auf einem getrennten Ziel prüfen und privat dokumentieren.

Für Rollback zuerst ausschließlich die tatsächlich gewählten Archivtimer stoppen
und deaktivieren (fünf im getrennten oder vier im bisherigen kombinierten Betrieb),
anschließend laufende Archivdienste kontrolliert beenden. Den bisherigen
`current`-Link und die bisherigen Unitdateien gesichert zurücksetzen, `daemon-reload`
ausführen und nativ nachlesen. Das gemeinsame `data/` mit Originalen und Cursor
bleibt erhalten. Eine ältere Softwareversion darf erst nach Prüfung der
Archivschema-Kompatibilität wieder schreiben. Fremde Dienste nicht stoppen.
