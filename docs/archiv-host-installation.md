# Archivhost dauerhaft betreiben

Stand: 28.10.2026. Die Vorlagen unter `deploy/` und der Runner
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
Dateihashes prüfen. Die Umgebung regulär installieren, beispielsweise mit
`.venv/bin/python -m pip install . 'pvlib==0.16.1' 'scikit-learn==1.9.1'`.
Für einen exakten Replay außerdem die vollständigen numerischen Laufzeitversionen
mit der ursprünglichen HA-Umgebung abgleichen und protokollieren; zwei direkte
Pins allein beweisen keine identische Umgebung. Tests mit HA Core gehören in
die Entwicklungsumgebung, nicht in die Collectorinstallation.

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

## Vorhandene Hostsicherung

Für die dokumentierte Installation bestätigt der Betreiber eine tägliche
LXC-Sicherung über Proxmox Backup Server (PBS). Das Archiv liegt im
Root-Dateisystem des LXC; dafür wird kein zusätzlicher Archivbackupdienst
eingerichtet. Bei einer späteren Verlagerung auf ein separates Volume dessen
Einbeziehung in die Hostsicherung erneut prüfen.

Die 24-Monats-Aufbewahrung der Originale und die Aufbewahrung der PBS-Sicherungen
sind getrennte Einstellungen. Eine erfolgreiche Wiederherstellung einer
eingefrorenen Archivkopie ist kein Nachweis einer vollständigen LXC-Rücksicherung
aus PBS. Herkunft und Umfang der aktuellen Belege stehen im
[Entwicklungsstand](entwicklungsstand.md#veröffentlichter-und-installierter-stand-0217).

Für Rollback zuerst ausschließlich die vier Archivtimer stoppen und deaktivieren,
anschließend laufende Archivdienste kontrolliert beenden. Den bisherigen
`current`-Link und die bisherigen Unitdateien gesichert zurücksetzen, `daemon-reload`
ausführen und nativ nachlesen. Das gemeinsame `data/` mit Originalen und Cursor
bleibt erhalten. Eine ältere Softwareversion darf erst nach Prüfung der
Archivschema-Kompatibilität wieder schreiben. Fremde Dienste nicht stoppen.
