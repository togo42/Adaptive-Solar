# Dauerhafter Exportpuffer und externes Originalarchiv

Stand: 28.10.2026, Datenvertrag für 0.2.16. Produktive Aufnahme und
Wiederherstellungsprüfungen werden separat im [Entwicklungsstand](entwicklungsstand.md)
nachgewiesen. Das Archiv belegt keine Prognoseverbesserung.
Die [Speicherentscheidung](archiv-speicherung-und-transport.md) hält fest:
zunächst Originaldateien und SQLite; PostgreSQL bei späterem Bedarf als
zusätzliche Abfrageebene, ohne die Originale aufzugeben.

## Datenvertrag und Grenzen

### Prognose- und Lernzustand ab 0.2.16

Die Aufnahme enthält den vollständigen `SiteConfig` einschließlich optionaler
Physik-/Nowcastparameter aus 0.2.15. `result` bewahrt Gesamtpunkte, Status,
Features, modellweise Punkte und deren ursprüngliche Wetterempfangszeiten.
`early_bias_shadow` enthält Status und Kandidatenpunkte getrennt von der
operativen Prognose. Ein Originalreplay prüft auch Status, Features und
Modellpunkte; übereinstimmende Gesamtleistung allein genügt nicht.

`issued_at` bezeichnet den Eingabecutoff, `computed_at` das Ende der
Forecast-/Modellberechnung. Der Umschlag erhält seinen `received_at` erst nach
Rückkehr aus dem Executor einschließlich Serialisierung. Dieser spätere Zeitpunkt
begrenzt `--as-of` und entspricht der Verfügbarkeit für das interne Forecastarchiv.
Ein während der Berechnung liegender Entscheidungszeitpunkt darf das Ergebnis
noch nicht verwenden. Die spätere Übernahme auf dem Archivhost bleibt nochmals
getrennt als `stored_at` erhalten.

`learner_available` unterscheidet einen vorhandenen Lerner vom Physikfallback
nach einem Fitfehler. Ein fehlender Lerner darf keine angeblichen Fitzeilen oder
einen Fit-Cutoff tragen. Erfolgreiche Fits werden aus den tatsächlich verwendeten
Zeilen einschließlich echter `measurement_support`-Zeitintervalle rekonstruiert.

`shade_learning` erfasst die Regel `beam-shade-learning-v2`: Schema-3-Tabellen
mit ursprünglichem Beobachtungs- und Verfügbarkeitszeitpunkt sowie zeitgebundenen
Freigaben. Die qualifizierte erste Probe einer UTC-Viertelstunde bleibt erhalten;
mehrtägige Stützung und Freigaberate entsprechen 0.2.15. `shading_before` und
`shading` dokumentieren die Zustände vor und nach jedem Lernschritt. Für die
optionale Nowcastglättung enthalten begrenzte `observation_sources` zusätzlich
die Rohzustände der tatsächlich verwendeten älteren Beobachtungen innerhalb
des konfigurierten Fensters. Zukünftige Proben/Freigaben und unbelegte
Beobachtungen werden beim Replay abgelehnt.

### Physisches Format

`custom_components/adaptive_solar/core/archive.py` importiert kein Home Assistant.
Alle Methoden führen blockierende Arbeit aus; HA ruft sie im Executor auf.
Ein getrenntes `ArchiveJournal(root, ...)` verwendet SQLite mit `synchronous=FULL`.
Die Generation ist eine persistente UUID, die Sequenz beginnt bei eins und wird
innerhalb der Transaktion mit dem Ereignis erhöht. Ein neu angelegter Puffer
bekommt eine neue Generation. Bestehende unbekannte oder beschädigte
SQLite-Dateien werden beim Öffnen abgelehnt und erhalten. Generation und
Sequenz-/Verwerfungszähler werden ausschließlich bei einer neuen Datenbank
initialisiert. In bestehenden Puffern sind alle Pflichtmetadaten nötig;
fehlende Felder werden nicht nachgetragen. Vor jeglichem Metadatenzugriff mit
Schreibwirkung oder einer Kompaktierung werden bestehende Umschläge und ihre
Generation, Reihenfolge, Zeilenfelder sowie Sequenz-/Verwerfungszähler gemeinsam
geprüft. Inkonsistente Originaldateien bleiben unverändert erhalten.

`append(kind, payload, received_at, event_id=None)` nimmt ein JSON-Objekt mit
endlichen Zahlen, ausschließlich Stringschlüsseln in allen verschachtelten
JSON-Objekten und einem zeitzonenbewussten Empfangszeitpunkt entgegen.
Nicht-Stringschlüssel werden vor dem Hashen abgelehnt, damit die JSON-Rundreise
keine Schlüsseltypen und damit Prüfsummen verändert.
Die Antwort enthält `schema=1`, `generation`, `sequence`, `event_id`, `kind`,
`received_at` in UTC, `payload` und `sha256`. Die Prüfsumme umfasst das kanonische
UTF-8-JSON ohne das Feld `sha256`: sortierte Schlüssel, kompakte Trennzeichen,
keine NaN-/Unendlichwerte. `validate_envelope` beziehungsweise `verify_event`
prüfen diesen Vertrag. Eine gleiche noch gepufferte ID mit gleichem Inhalt ist
idempotent; widersprüchlicher Inhalt wird abgelehnt. IDs bereits verworfener
Pufferereignisse sind kein dauerhaftes Deduplizierungsregister.

Startgrenzen des HA-Puffers sind 64 MiB serialisierte Ereignisse, 10.000
Ereignisse und 72 Stunden. Zeitbereinigung erfolgt beim nächsten Append anhand
des neuen Empfangszeitpunkts; ohne weitere Aufnahmen bleiben alte Daten bis
zum nächsten Append erhalten. Byte- und Ereignisgrenzen gelten weiterhin.
Die SQLite-Datei hat zusätzlichen Seiten-/Indexaufwand. Beim Append werden
ältere Ereignisse **vor** der neuen Allokation entfernt; SQLite verwendet die
freien Seiten erneut. Es gibt keine Vollkompaktierung je Append. Ein über die
Zeitbereinigung stark verkleinerter Puffer behält seine freien Seiten für
spätere Aufnahmen. Die physische Dateigrenze wird pro Verbindung durch SQLite
`max_page_count` auf höchstens `2 × max_bytes + 8 MiB` begrenzt, abgerundet auf
ganze Datenbankseiten. Bei den Voreinstellungen sind das **136 MiB** zusätzlich
zur logischen Nutzdatengrenze von 64 MiB. Das ist eine harte Kapazitätsreserve,
keine erwartete Dateigröße. Der temporäre Rollbackjournalbedarf wird gesondert
mit bis zur Dateigrenze plus 64 KiB Reserve berücksichtigt; insgesamt stehen
bei den Voreinstellungen **272 MiB plus 64 KiB** als lokales Diskbudget im
Status. Diese Reserve ist keine gemessene typische Schreibrate.

`stats()` trennt Ereignisbytes, tatsächliche Dateigröße, freie SQLite-Seiten,
physische Dateigrenze und temporäres Diskbudget. Bei einer kleineren
Konfiguration darf eine einmalige Kompaktierung beim Öffnen nötig werden;
ein weiterhin zu großes Archiv wird ausdrücklich abgelehnt. Eine vollständige
SQLite-Prüfung erfolgt beim Öffnen und über `verify()`, nicht mit jedem
Append; Schema-/Metadatenprüfungen bleiben pro Verbindung aktiv. Ein lokaler
synthetischer Versuch mit 64 Ereignissen à etwa 850 kB in einem 55-MiB-/64-Ereignis-
Puffer benötigte 0,626 s für die Erstbefüllung und 0,104 s für zehn nachfolgende
Appends bei unveränderter Dateigröße von 54.546.432 Byte. Das ist ein einzelner
Entwicklungsrechner-Nachweis, keine HA-Betriebszusage.
Die Produzentenseite muss Archivfehler abfangen und die Prognose fortsetzen.

Ein Ereignis ist höchstens 1 MiB groß. Größere Originalantworten oder Lernstände
werden durch den Produzenten in begrenzte Ereignisse zerlegt und mit
Gruppenprüfsumme, Chunkzahl und Indizes verbunden. Ein zu großes Einzelereignis
wird vor der Sequenzfortschreibung ausdrücklich abgelehnt. Die Speicherbibliothek
interpretiert fachliche Referenzen nicht: Ein Replay muss fehlende Chunks und
weitere Abhängigkeiten ablehnen. Byteintegrität ist kein Herkunfts- oder
Vollständigkeitsbeweis.

`append_many(events)` veröffentlicht zusammengehörige Chunks und ihren Manifest-
Datensatz in **einer** SQLite-Transaktion. Jedes Element ist ein Vierertupel
`(kind, payload, received_at, event_id_oder_none)`. Die Methode liefert alle
vollständigen Umschläge in Eingabereihenfolge. Die gesamte neue Ereignismenge
muss zusammen in die konfigurierte Byte- und Ereignisgrenze passen; sämtliche
Einzelereignisse bleiben zusätzlich auf 1 MiB begrenzt. Die vollständige
Validierung erfolgt vor jeder Bereinigung oder Aufnahme. Ein ungültiger
späterer Chunk, eine unpassende Gesamtgröße oder ein Fehler mitten im Schreiben
rollen neue Ereignisse, Löschungen und Sequenzfortschreibung gemeinsam zurück.

Die Bereinigung betrifft nur bereits vorhandene ältere Ereignisse; die neu
angenommene Charge bleibt vollständig im Puffer. Die Zeitgrenze richtet sich
nach ihrem spätesten Empfangszeitpunkt. Ein vollständiger Retry derselben noch
vorhandenen IDs ist idempotent; eine Mischung vorhandener und neuer IDs wird
abgelehnt, damit kein teilweiser Retry als vollständige Veröffentlichung gilt.
Doppelte IDs innerhalb einer Charge werden ebenfalls abgelehnt. `append`
verwendet intern dieselbe Methode mit einem Ereignis. Nachfolgende Aufnahmen
können frühere Chargen weiterhin aus dem begrenzten Puffer verdrängen; dann
bleiben Sequenzlücke und strenge Prüfung fehlender fachlicher Referenzen nötig.

## Seiten, Lücken und Wiederanlauf

`page(cursor=None, limit=100, max_bytes=2097152)` liefert:

| Feld | Bedeutung |
| --- | --- |
| `schema` | Seitenversion, derzeit 1 |
| `generation` | Aktuelle Puffergeneration |
| `oldest_sequence` | Älteste verfügbare Sequenz, bei leerem Puffer nächste Sequenz |
| `requested_cursor` | Unveränderter angefragter Cursor oder null |
| `next_cursor` | `UUID:Sequenz` nach dem letzten enthaltenen Ereignis |
| `events` | Aufeinanderfolgende vollständige Ereignisumschläge |
| `gap` | null oder `reason`, `from`, `to` für einen Cursorbruch |

Eine Seite enthält höchstens 1.000 Ereignisse und 4 MiB inklusive Metadaten.
Passt das nächste Ereignis nicht in die angefragte Seitengrenze, wird ein Fehler
statt eines scheinbar abgeschlossenen Abrufs geliefert. Der Abrufende kann eine
höhere Grenze wählen. Cursor vor dem ältesten Ereignis ergeben eine sichtbare
`retention_or_overflow`-Lücke; ein fremder Generationscursor ergibt
`generation_changed`. Bei einem Generationswechsel kann der leere numerische
Lückenbereich `from=1,to=0` auftreten; der Generationsbruch selbst bleibt sichtbar.
Ein Cursor vor dem ersten Abruf ist null; ein Cursor nach der letzten vorhandenen
Sequenz wird abgelehnt. `validate_page` prüft Felder, Grenzen, Prüfsummen,
Sequenzkontinuität, Lücken und den resultierenden Cursor.

## Langzeitarchiv und Transaktionsreihenfolge

`ArchiveStore(root)` speichert jedes neu angenommene Seitenpaket unter
`originals/<sha256>.json.gz`. Der Hash bezieht sich auf den unkomprimierten
Originalwrapper mit `schema`, privatem `source`, monotoner `ingest_order`,
`stored_at`, ursprünglichem `archive_started_at` und der vollständigen Seite.
Kompression verwendet einen festen gzip-Zeitstempel. Jeder komprimierte und
dekomprimierte Lesevorgang hat eine harte Grenze. Die Originale sind maßgeblich;
`index.sqlite3` enthält den abgeleiteten Suchindex und Collector-Checkpoint.

`ingest_page(source, page)` verlangt den eigenen aktuellen dauerhaften Cursor
als `requested_cursor`. Eine Wiederholung bereits vollständig aufgenommener Ereignisse prüft
überlappende Inhalte und erzeugt keine doppelte Aufnahme; ein älterer Retry
setzt den aktuellen Checkpoint nicht zurück. Die Reihenfolge ist:

1. Seite und mögliche Inhaltskonflikte prüfen; Indexänderungen nur vormerken.
2. Original in temporäre Datei schreiben und Datei synchronisieren.
3. Datei atomar umbenennen und Originalverzeichnis synchronisieren.
4. Erst danach die SQLite-Transaktion mit dem neuen Checkpoint bestätigen.

Bei einem Absturz vor Schritt vier bleibt der alte Checkpoint gültig. Beim
Wiederanlauf werden dauerhaft geschriebene, noch nicht indexierte Originale
wieder eingelesen. Ein dauerhaft bestätigtes Original darf nicht fehlen; sonst
wird das Öffnen abgebrochen. Eine periodische explizite Integritätsprüfung liest
auch die bereits indexierten Originale erneut. Das Öffnen prüft neue Originale
und die vorhandene Dateimenge, ohne alle komprimierten Nutzdaten bei jeder
neuen Seite erneut zu dekomprimieren. Die Suche nach Originaldateien skaliert
mit der Dateianzahl; diese Kosten gehören zur Pilotmessung.

`checkpoint(source)` liefert den Cursor oder null.
`iter_events(source=None, kind=None, dataset=None)` liest überprüfte Originale
in Aufnahmereihenfolge. Der Iterator hält während der Iteration die Archivlock;
langsame Auswertungen sollen die Eingaben zuerst in ein separates eingefrorenes
Dataset exportieren. `rebuild_index()` erstellt einen vollständig geprüften
Kandidaten und ersetzt den Index erst nach Erfolg. Das explizite CLI-Kommando
kann auch einen nicht mehr lesbaren Index aus den Originalen ersetzen.
Ein unbekanntes oder beschädigtes Original lässt den bestehenden Index dabei
unverändert. Eine Prüfsumme bestätigt nur Unverändertheit, keine authentische
Herkunft der behaupteten Daten.

## Aufbewahrung, eingefrorene Daten und Speicherprüfung

`maintain(now=...)` ist ein ausdrücklich auszuführender lokaler Wartungsschritt.
Er entfernt nicht gepinnte Seitenpakete nach 24 **Kalendermonaten** seit ihrer
lokalen Aufnahme; Monatsenden werden auf den letzten gültigen Tag abgebildet.
Die letzte Seite jeder Quelle bleibt als rekonstruierbarer Checkpoint erhalten,
auch nach Ablauf dieser Frist. Das bedeutet eine begrenzte zusätzliche
Aufbewahrung je Quelle. Vor der Wartung werden unbekannte Originale wieder
indexiert. Ein beschädigtes Pinmanifest bricht die Wartung ab.

`pin(dataset, sources=None)` friert alle derzeitigen Originaldateien der
gewählten Quellen ein; ohne Auswahl werden alle Quellen aufgenommen. Pin-Namen
sind unveränderlich. Vor Indexwiederaufbau, Integritätsprüfung, Datasetiteration,
Export und Aufbewahrungsbereinigung muss jede referenzierte Pin-Originaldatei
existieren. Ein fehlendes gepinntes Original bricht den Vorgang ab; ein
Indexwiederaufbau darf es weder vergessen noch ein scheinbar leeres Dataset
erzeugen. Datasetiteration verlangt außerdem die vollständige Mitgliedschaft
im Index; bei fehlenden Indexzeilen ist zuerst ein überprüfter Wiederaufbau
nötig. Spätere Ereignisse gehören nicht zu diesem Dataset.
`export_dataset(dataset, destination)` kopiert die Originale und ein Manifest
mit Hashes, Quellen und den ursprünglichen Empfangszeitbereichen in ein neues
Zielverzeichnis. Das Ziel lässt sich mit `ArchiveStore` unabhängig öffnen und
indexieren. Ein bereits existierendes Ziel wird nicht überschrieben. Bei einem
abgebrochenen Export bleibt eventuell ein unvollständiges Ziel; das Quellarchiv
bleibt erhalten. Die erfolgreiche vollständige Ausgabe enthält `dataset.json`.

Ein Pin bewahrt alle aufgenommenen Originale seiner gewählten Quellen, nicht
bloß eine Ergebnisdatei. Fachliche Vollständigkeit und die Auflösung sämtlicher
Referenzen einschließlich vor Aufnahmestart fehlender Chunks bleiben ein
separater Replay-Abnahmepunkt. Quellenfilter dürfen benötigte fremde Quellen
nicht ausschließen. Für eine sichere vollständige Aufnahme zunächst alle
Quellen gemeinsam pinnen und die Replayabhängigkeiten prüfen.

`stats(now=...)` meldet Ereignisanzahl, komprimierte Bytes, Indexgröße, Bytes je
Quelle, Beobachtungstage, komprimierte Bytes pro Tag sowie eine auf 731 Tage
hochgerechnete Planung. Drei- und Sechsmonatszeitpunkte beziehen sich auf den
ursprünglichen Aufnahmestart, der in nachfolgenden Originalen mitgeführt und
beim Indexwiederaufbau erhalten wird. Modell-/Datensatzraten, Messdaten,
Lernzustände, temporäre Replaydaten, Kopien und Backups müssen in der
betrieblichen Kapazitätsprüfung zusätzlich aufgeschlüsselt werden. Die
Hochrechnung ist kein festgestellter langfristiger Bedarf.

## CLI und Transport

`resolve_events(event_ids, source=..., generation=..., dataset=...)` liest
höchstens 1.024 eindeutige Referenzen über einen SQLite-Index aus ihren
Originalpaketen. Fehlende/mehrdeutige IDs, andere Quellen/Generationen und
Verweise außerhalb des Pins werden abgelehnt; der Originalinhalt wird gegen
die Indexzuordnung geprüft. Der Index bleibt vollständig wiederaufbaubar.

Für viele aufeinanderfolgende Schritte bietet
`reference_reader(source=..., generation=..., dataset=...)` einen Lesekontext.
Er prüft den vollständigen gewählten Pin am Anfang und vor erfolgreichem Ende;
jede einzelne Abfrage verifiziert die benötigten Originale erneut. Zwischen
Abfragen wird kein Archivlock gehalten. Pinänderungen oder inzwischen fehlende
Originale verhindern den erfolgreichen Abschluss. Der Aufrufer darf seinen
Ergebnisbericht erst nach Verlassen des Kontexts veröffentlichen. Damit wird
der vollständige Pin nicht für jede einzelne Chunkreferenz neu durchlaufen.

Private Archive gehören unter ignorierte `data/`-Pfade, niemals in Git.
Beispiele verwenden fiktive Bezeichner:

```bash
.venv/bin/python scripts/archive.py --root data/archive stats
.venv/bin/python scripts/archive.py --root data/archive collect --source example --entry-id PRIVATE_ENTRY_ID
.venv/bin/python scripts/archive.py --root data/archive export-observations --source example:actuals --kind actuals --dataset pilot --output data/actuals.jsonl
.venv/bin/python scripts/archive.py --root data/archive verify
.venv/bin/python scripts/archive.py --root data/archive pin pilot
.venv/bin/python scripts/archive.py --root data/archive export-dataset pilot data/pilot-frozen
.venv/bin/python scripts/archive.py --root data/archive maintain
.venv/bin/python scripts/archive.py --root data/archive rebuild-index
```

`export-observations` rekonstruiert gespeicherte Istwert- beziehungsweise
Referenzaufnahmen über `archive_observations.py` verlustfrei als JSONL für die
bestehenden Auswertungsadapter. Das Kommando veröffentlicht die Ausgabe atomar
und überschreibt keine vorhandene Datei; `--source` bezeichnet den vollständigen
privaten Streamnamen einschließlich `:actuals` beziehungsweise `:references`.

`collect` liest `HA_URL` und `HA_TOKEN` ausschließlich aus der Umgebung,
authentifiziert sich über den nativen HA-Websocket und ruft ausschließlich
`adaptive_solar.export_archive` mit `return_response=true` auf. Die Antwort
enthält `page` und gegebenenfalls den getrennten Producerstatus. Der Abruf
fordert weder Wetter noch Prognoseneuberechnung an. Ein eigener dauerhafter
Cursor wird je privatem Quellbezeichner geführt. Der nächste Seitenabruf folgt
erst nach bestätigter lokaler Speicherung; Verbindungsabbrüche setzen beim
letzten bestätigten Cursor fort. Pro Lauf ist die Seitenzahl begrenzt. Ein
fünfminütiger Scheduler und Backups werden durch diese CLI nicht eingerichtet.
Fehlermeldungen geben keine fremden Exceptiontexte oder Zugangsdaten aus.

Die Tests in `test_archive_store.py` und `test_archive_collector.py` prüfen
Wiederanlauf, Wiederholungen, Absturzfenster, Diskfehler, Generationenwechsel,
Überlauf, harte Grenzen, Prüfsummen, beschädigte/unbekannte Schemas,
Indexwiederaufbau, konkurrierende Abrufe/Schreibvorgänge, 24-Monatsfrist,
Pinning und authentifizierten Exporttransport mit simuliertem Server. Diese
lokalen Nachweise ersetzen weder eine echte HA-/Host-Betriebsprobe noch eine
Wiederherstellung aus einem externen Backup.
