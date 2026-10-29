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

Seit [0.2.18](../releases/release-0.2.18.md) liefert die Integration diese Kurven. Ein
passender Dashboard-Consumer wird separat installiert; HACS aktualisiert
keine Dashboardressource. Nach der Einrichtung die betroffenen Stufen und
die erste vollständig gespeicherte Tageskurve prüfen. Für einen Rückweg
vorherigen Integrationscode und gegebenenfalls die vorherige Dashboardressource
verwenden; Lernstores und Recorder-Daten nicht zurücksetzen.

Verhaltenstests prüfen beide DST-Wechsel, native Intervallenergie, alte
Snapshots, isolierte Kurvenkorruption und den echten Storeleser von 0.2.17.
Der historische Releaseprüfstand steht in den [Prüfnachweisen](../entwicklung/pruefnachweise.md).
