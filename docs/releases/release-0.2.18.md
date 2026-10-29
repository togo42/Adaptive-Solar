# Adaptive Solar 0.2.18

Die Sensoren **Prognose Tag 0** liefern jetzt neben ihrer eingefrorenen
Tagessumme die vollständige Stundenkurve desselben vor Tagesbeginn
ausgegebenen Laufs. Frühere Tagesstunden bleiben damit für einen passenden
Dashboard-Consumer verfügbar. Originalausgabezeit, native Intervallenergie,
vollständige Tagesabdeckung und beide Zeitumstellungen bleiben erhalten.
[Datenvertrag und Statusattribute](../technik/day-start-curve.md).

Vorhandene Snapshots ohne Stundenwerte behalten ihre Tagessumme und melden
`forecast_curve_status: not_stored`. Eine fehlende Kurve wird weder aus
aktuellem Wetter noch aus Istwerten oder der Tagessumme rekonstruiert.
Die erste vollständige Kurve setzt einen vollständigen gespeicherten Lauf
vor Beginn ihres Zieltags voraus. Laufende Restprognose, Physik, Lernen,
Messgates, Entity-IDs und Abhängigkeitspins ändern sich nicht.

Das vollständige Release enthält außerdem die bereits separat entwickelte
hierarchische Hashablage des externen Archivs. HA-Exportjournale verwenden
weiterhin ihren bisherigen Vertrag. Korrekturen der Archivhelfer verhindern
das Überschreiben von Replayeingaben, melden unvollständige HA-/Wetter-/
Beobachtungstransfers als Fehler und prüfen Pip-Installationsziel und
Runtimeimports. Der Reviewumfang schließt systemd-Units ein. Diese Helfer
werden durch HACS nicht auf einem externen Archivhost installiert.

## Upgrade und Rückweg

Vorher aktuellen Komponentenstand und Konfiguration sichern, dann in HACS
0.2.18 herunterladen und einmal Home Assistant Core neu starten. Vorhandene
Einträge und Optionen weiterverwenden; keine Lernstores oder Recorder-Daten
zurücksetzen. Anschließend alle vorhandenen Einträge, Tag-0-Status, Restprognose,
Exportstatus, Konfigurationsprüfung und Repairs lesen. Ein Core-/OS-Upgrade
oder ein erneuter Musl-Wheelbau ist nicht erforderlich.

Die optionalen Kurven liegen als `daily_snapshot_curves` neben den bisherigen
`daily_snapshots` im selben Store. Der echte Leser von 0.2.17 ist mit diesem
Format geprüft: Tageswerte und kompatible Mess-/Lernhistorie bleiben bei einem
Code-Rückweg lesbar. Für einen exakten Code-Rückweg die zuvor gesicherten Komponentenbytes verwenden. Dashboardressourcen
und externe Archivhostdienste werden unabhängig versioniert und installiert.

## Prüfung und Grenzen

Der vollständige Codex-Review (`gpt-6.1-sol/high`) akzeptiert Quellcommit
`70966fcda17d92ada852e77097a3707d226b5db2` ohne Findings. Payload-SHA256
`572529575cf2fb199e97617a67dab96a6f13beafd5cf0e23ab6ec2977aa312c1`;
42 Quellchunks und separater Abschluss, keine Kontextverkürzung oder Tools.
Alle Codebytes sind für die Releasevorbereitung erneut abgeglichen;
Releaseversionsnummern und der Dokumentationsabschluss sind zusätzliche
Metadatenänderungen. Die historischen Test-, Build- und CI-Angaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md); konkrete Installationsprotokolle bleiben privat.

Tests, Review und kurze Laufzeitprüfung belegen keine höhere reale
Prognosegenauigkeit und ersetzen keinen prospektiven Anlagenvergleich.

## Veröffentlichung

Historische Quell-, Test- und Veröffentlichungsangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md). Anlagenspezifische Installations-
und Laufzeitprotokolle werden privat geführt.
