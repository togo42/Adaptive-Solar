# Archivhost dauerhaft betreiben

Der HA-Job prueft ausser dem Child-Exitcode dessen strukturierten
Collector-Abschluss. Cursorluecken, fehlender Abschluss am Seitenlimit,
Producer-Schreibfehler, offene Producer-Schreibvorgaenge oder fehlende
Statusbelege ergeben `complete=false` und einen fehlgeschlagenen Hostlauf.
Die Statusdatei nennt nur feste Statuswerte, Zaehler und Fehlerbooleans;
rohe Producerfehler, Endpunkte, Tokens und Quellen-IDs werden nicht ins
Journal uebernommen. Bestaetigte Checkpoints bleiben fuer den naechsten
Lauf erhalten. Normale Pufferretention ohne Cursorverlust zaehlt nicht
als neue Abholluecke. Collector und Runner muessen gemeinsam aktualisiert
werden; eine reine Codevorbereitung aendert keinen bestehenden Hostdienst.

Stand: 29.10.2026. Die Vorlagen unter `deploy/` und der Runner
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
qualifiziert.

## Zugangsdaten ohne dauerhafte Klartextdatei

Die beiden HA-lesenden Dienste verwenden `LoadCredentialEncrypted=ha-auth:…`
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
geeignete Verschlüsselung. Ohne sichere Credentialbereitstellung die beiden
HA-lesenden Dienste nicht aktivieren. Vorhandene Helios-/ESS-Zugänge und deren
Dienste bleiben unverändert.

## Timer und erste Aufnahme

Die acht `deploy/adaptive-solar-archive-*.service`/`.timer` nach
`~/.config/systemd/user/` übernehmen. `loginctl show-user "$USER" -p Linger`
muss für einen Betrieb ohne Login `Linger=yes` liefern. Timer verwenden die
Zeitzone des Hosts und holen nach einem Ausfall einmalig einen fälligen Lauf nach.

| Aufgabe | Zeitpunkt |
| --- | --- |
| HA-Originalexport | alle fünf Minuten |
| Zusätzliche Wettermodelle | stündlich Minute 03 |
| Recorder und Referenzen | stündlich Minute 12, 72 Stunden Rückblick, zehn Minuten Reserve |
| Retention | täglich 03:37, 24 Kalendermonate, Pins bleiben erhalten |

Vor dem Aktivieren jeden Dienst einmal kontrolliert starten. Erst nach erfolgreichem
Original-/Cursor-/Quellenreadback, Kapazitätsprüfung und Statusprüfung die vier Timer
mit `systemctl --user enable --now adaptive-solar-archive-{ha,weather,observations,retention}.timer`
aktivieren. Der gemeinsame Dateilock serialisiert sämtliche Runneraufgaben.
Einzelne fehlerhafte HA-Einträge verhindern keine Aufnahme der anderen Einträge;
der Gesamtlauf meldet trotzdem Fehler. Ein Dienststart veröffentlicht keine
Prognose und verändert keine HA-Modelloption.

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

Für Rollback zuerst ausschließlich die vier Archivtimer stoppen und deaktivieren,
anschließend laufende Archivdienste kontrolliert beenden. Den bisherigen
`current`-Link und die bisherigen Unitdateien gesichert zurücksetzen, `daemon-reload`
ausführen und nativ nachlesen. Das gemeinsame `data/` mit Originalen und Cursor
bleibt erhalten. Eine ältere Softwareversion darf erst nach Prüfung der
Archivschema-Kompatibilität wieder schreiben. Fremde Dienste nicht stoppen.
