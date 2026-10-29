# Stundenkurve der Tagesbeginnprognose

Die Sensoren **Prognose Tag 0** liefern zusaetzlich zur eingefrorenen
Tagessumme deren vollstaendige Stundenkurve in `forecast`. So kann ein
Dashboard fruehe Stunden auch am Nachmittag weiter anzeigen.
Die aktuelle Kurve im Prognosedatenstatus und die Resttagenergie bleiben
unveraendert ab dem jeweiligen Berechnungszeitpunkt.

## Datenvertrag und Speicherung

Der bestehende Tagesbeginn-Snapshot enthaelt optional `forecast`, eine
Zuordnung von Wechselrichter-/Regler-ID auf chronologisch geordnete Zellen
mit `start`, `end` und `energy_kwh`. Jede Zelle integriert ausschliesslich
die bereits ausgegebene native Intervallenergie des gleichen Laufs, ohne
Rundung und ohne erneute Physik-/Wetterberechnung. Beginn/Ende sind absolute
UTC-Zeitpunkte; lokale 23-/25-Stunden-Tage behalten ihre tatsaechliche Dauer.
Die letzte Zelle eines Tages darf kuerzer sein, falls die Zeitzone das verlangt.
Pro Anlage und Tag sind hoechstens 26 Zellen erlaubt. Die Summe muss bis auf
Float-Rechenrundung (`1e-12` absolut/relativ) zur gespeicherten Tagesenergie
passen. Rohzeiten, Struktur, Kontiguitaet und Provenienz werden exakt geprueft.

Tagessumme, Kurve, originaler Ausgabezeitpunkt und Konfigurationsprovenienz
werden zusammen vor Tagesbeginn im vorhandenen Store gesichert. Die
persistierten `daily_snapshots` behalten ihre alten Felder; Kurven liegen
separat unter `daily_snapshot_curves`, nach Zieltag und Anlage zugeordnet.
Damit kann auch Version 0.2.17 denselben Store mit Tageswerten und Lernhistorie
weiter lesen. Intern und beim expliziten Operator-Import darf ein Snapshot
die optionale `forecast`-Zuordnung tragen. Ein erst
nach Mitternacht verfuegbarer Lauf ergaenzt den heutigen Snapshot nicht.
Die bestehende Aufbewahrung und physikalische Provenienzpruefung bleiben
erhalten; die Erweiterung aendert weder den Featurevertrag noch Lern-/Messdaten.
Ein beschaedigter optionaler Kurventeil wird beim Laden isoliert verworfen;
gueltige Tagessummen und Lernhistorie bleiben erhalten. Explizite Operator-
Imports lehnen dagegen ungueltige mitgelieferte Kurven ab.

Am Tag-0-Sensor kennzeichnen `forecast_curve_scope: day_start` und
`forecast_curve_status: available` eine gespeicherte Kurve. `issued_at`
ist deren originale Ausgabezeit, `forecast_cutoff` der heutige lokale
Tagesbeginn als absoluter Zeitpunkt. Aggregierte Alt-Entitaeten summieren
nur vollstaendig ausgerichtete Zellen aller zugehoerigen Anlagen.
`forecast` bleibt wie bei der laufenden Kurve aus Recorder-Attributen
ausgeschlossen. Es gibt keine neuen Entities oder Pflichtoptionen.

## Vorhandene Snapshots und erste sichtbare Kurve

Aeltere Snapshots ohne Kurve behalten ihre Tagessumme. Der Status ist
`not_stored`, die Kurve leer. Fehlt der Snapshot ganz, lautet der Status
`unavailable`. Es gibt keine Rekonstruktion aus Tageswert, aktuellem Wetter,
Ist-Ertrag oder aktuellem Restlauf. Der erste volle Tag wird nach einem
vollstaendig gespeicherten Lauf vor seinem Tagesbeginn verfuegbar.
Ein Wechsel der physischen Konfiguration folgt weiterhin den vorhandenen
Provenienzregeln; historische Daten werden nicht als neue Anlage umgedeutet.

## Dashboard und Aktivierung

Ein Consumer liest fuer den heutigen Kalendertag `Prognose Tag 0.forecast`,
prueft den Tagesbeginn-Cutoff und die originale Ausgabezeit und laesst echte
Luecken sichtbar. Die Resttaganzeige liest weiterhin den aktuellen
Resttagsensor. Die Erweiterung ist reine Speicherung/Anzeige und kein
Nachweis einer verbesserten Prognosegenauigkeit.

Vor produktiver Nutzung muessen Integrationscode und Consumer gemeinsam
aktiviert und die vier Einzelanlagen gelesen werden. Fuer den Rueckweg
den vorherigen Code und die vorherige Dashboardressource wiederherstellen;
keine Lernstores oder Recorder-Daten zuruecksetzen. Diese Dokumentation
belegt weder eine Veroeffentlichung noch eine produktive Aktivierung.

## Lokaler Implementierungsabschluss am 29.10.2026

Die vollstaendige Suite auf Entwicklungsbasis `665acd4` besteht 1.679 Tests
(ohne Skips), Ruff und `pip check`. Eine separate Kopie der installierten
Version `v0.2.17` mit ausschliesslich den drei geaenderten Komponentendateien
und den neuen Regressionen besteht 1.653 Tests ohne Skips. Der echte Leser
von 0.2.17 hat in einem weiteren HA-Test den neuen Store einschliesslich
unveraenderter Tageswerte und Messintervalle erfolgreich geladen. Der
Paketbau stimmt in allen 38 Komponentendateien bytegenau zum getesteten
Entwicklungsstand; dieser Gesamtstand ist keine Freigabe, weitere dortige
Archiv-Aenderungen in eine bestehende Installation zu uebernehmen.

Aktiver Self-Review: Original-Ausgabezeit und vollstaendige Tagesabdeckung,
Dauer beider Zeitumstellungen, Uebereinstimmung von Tages- und Stundenenergie,
getrennte Live-Restprognose, Alt-Snapshots und Rueckwaertskompatibilitaet
geprueft. Die optionale Kurve liegt deshalb neben dem unveraenderten alten
Snapshotformat. Die drei Codeaenderungen sind unabhaengig von Anlagenoptionen,
Feature-/Messvertraegen und Physik-/Lernberechnung.

Historischer Zwischenstand vor dem freigegebenen Nachreview: Grok meldete
`402 Payment Required` (Nutzungsguthaben erschoepft). Der Gemini-Lauf wurde
wegen einer Kontextverkuerzung korrekt verworfen. Auch die Codex-Versuche
erbrachten keinen gueltigen Abschluss; ein weiterer Aufruf wurde durch die
automatische Freigabepruefung wegen fehlender ausdruecklicher Uebertragungs-
freigabe fuer diesen Empfaenger abgelehnt. Keine dieser Teilpruefungen ist
ein abgeschlossener externer Fachreview. Vor einer produktiven Uebernahme
muss ein zulaessiger Reviewer den finalen Quellstand gueltig abschliessen.
Der HA-Consumer ist separat durch Gemini ohne Findings geprueft.

Der vom Nutzer anschliessend ausdruecklich freigegebene Codex-Review
(`gpt-6.1-sol/high`, vollstaendige Originalbytes per Chunktransport,
keine Kontextverkuerzung oder Werkzeugaufrufe) wurde mit zwei mittleren
Befunden abgeschlossen. Sie betreffen die bestehenden Replay-Ausgabepfade
und ausgelassene systemd-Units im Reviewumfang, nicht die drei
Tagesbeginn-Aenderungen. Beide Punkte sind vor dem Nachreview korrigiert:
[Schutz der Replayeingaben](archivbetrieb.md#5-eingefrorene-daten-und-exakter-replay)
und [vollstaendiger Unit-Scope](validierung.md#4-lokale-prüfung-und-review).
245 gezielte Regressionen bestanden. Diese Werkzeugkorrekturen gehoeren
nicht zum vorbereiteten HA-Deploy; dessen Umfang bleibt bei drei
Komponentendateien und dem Consumer. Ein gueltiger Nachreview bleibt
Voraussetzung fuer die Aktivierung.

Der erste Nachreview bestaetigte die beiden Werkzeugkorrekturen, meldete
aber einen weiteren bestehenden Befund zur Fehlerweitergabe des
Collectors an den Archivhost. Die Korrektur uebernimmt einen bereinigten
Producerstatus, bestaetigt den Abholabschluss explizit und laesst sowohl
Collector als auch Hostrunner bei Luecken/Fehlern/unklarem Abschluss
fehlschlagen. 45 gezielte Tests decken auch den vollstaendigen Weg von
Collector-CLI bis Host-Exitcode ab. Normale Ringpufferretention ohne
Cursorverlust wird separat geprueft und nicht als Fehler gemeldet.
Diese Korrektur bleibt ebenfalls ausserhalb des HA-Deployumfangs.

Der anschliessende Nachreview fand einen uebersehenen lokalen Aufrufer
des geaenderten Collectorvertrags. `archive_observations.py` liefert nun
eine explizite lokale Journalseite mit Producerstatus und prueft sowohl
Recovery- als auch Abschlussstatus. Unvollstaendige Recovery ueberspringt
eine neue Aufnahme des betroffenen Streams. 57 gezielte Tests pruefen
normale und unvollstaendige Beobachtungsläufe bis zum Host-Exitcode.
Alle produktiven Aufrufstellen von `scripts.archive.collect` wurden
abgeglichen; die HA-Komponentendateien bleiben dabei unveraendert.

Der naechste vollstaendige Codex-Nachreview fand zwei weitere bestehende
Archivwerkzeugfehler: Die Wetteraufnahme uebernahm Journalbrueche nicht in
ihren Exitstatus; der Hostinstaller konnte durch Pip-Einstellungen in ein
anderes Ziel installieren. Beide Pfade sind korrigiert und durch echte
CLI-/Host- sowie Offline-pip-Regressionen abgedeckt. 59 gezielte Tests und
Ruff bestehen; die gesamte Suite besteht 1.727 Tests ohne Skips, `pip check`
meldet keine Abhaengigkeitsfehler. Der aktive Self-Review hat alle produktiven
Wettertransfer-Aufrufstellen sowie die echten Installations- und Importpfade
abgeglichen. Diese Werkzeugkorrekturen bleiben ausserhalb des HA-Deploys;
der abschliessende Integrationsreview steht noch aus.

## Abgeschlossener Integrationsreview am 29.10.2026

Der vollstaendige Codex-Nachreview akzeptiert Quellcommit
`70966fcda17d92ada852e77097a3707d226b5db2` mit `verdict=mergeable` und
ohne Findings. Modell `gpt-6.1-sol`, Effort `high`; Payload-SHA256
`572529575cf2fb199e97617a67dab96a6f13beafd5cf0e23ab6ec2977aa312c1`
bei 2.467.285 Originalbytes. Der native Audit bestaetigt 42 Quellchunks
und den unabhaengigen Abschlussturn, 43 abgeschlossene Turns und keinerlei
Kontextverkuerzung, Werkzeugaufrufe oder Hintergrundaufgaben. Receipt und
Bericht liegen lokal ignoriert unter
`reviews/private/day-start-codex-weather-pip-fixed/`.

Alle oben beschriebenen Zwischenbefunde sind damit nachgeprueft. Die
Suite besteht 1.727 Tests ohne Skips; die auf die installierte 0.2.17-Basis
begrenzte Pruefung der drei Komponentendateien und des alten Store-Lesers
bleibt separat dokumentiert. Dieser Dokumentationsabschluss aendert keine
reviewten Codebytes und ist kein HACS-Release. Produktive Aktivierung und
deren begrenzte Laufzeitbelege werden installationsspezifisch dokumentiert;
Review und Tests beweisen keinen Prognosevorsprung.
