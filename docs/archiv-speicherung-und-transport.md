# Archivspeicherung und Transport von Home Assistant

Stand: 28.10.2026. Nutzerentscheidung: zunächst komprimierte Originaldateien mit
lokalem SQLite-Index; PostgreSQL bei späterem Bedarf als zusätzliche Abfrageebene
prüfen. Die folgenden Aussagen beschreiben den implementierten Transport und
eine spätere Ausbauoption, keine bereits aktive Hostinstallation.

## 1. Zuerst Originaldateien

Das Archiv muss mehrere Versionen derselben Prognose oder Messung erhalten.
Zielzeit, tatsächlicher Empfang, Berechnungscutoff und spätere Archivübernahme
sind unterschiedliche Angaben. Wiederholte Meldungen mit gleichem Messwert können
neue Frischebelege sein; abgelehnte Schattenlerneingaben bleiben für spätere
Verfahren relevant. Diese Information darf beim Speichern nicht verschwinden.

Der aktuelle `ArchiveStore` bewahrt deshalb komprimierte Originalpakete mit
Prüfsummen. Ein lokaler SQLite-Index enthält Quellen, Generationen, Sequenzen,
Originalverweise und Lesecursor. Die Dateien sind maßgeblich; der Index kann
wiederaufgebaut werden. Ein Pin friert konkrete Originale für einen Versuch ein.
Details: [Datenvertrag, Retention und Wiederherstellung](archive-storage-contract.md).

SQLite braucht keinen zusätzlichen Datenbankdienst und passt zu diesem lokalen
Collector. Es unterstützt nur einen gleichzeitigen Schreiber pro Datenbank;
ein Serverdatenbanksystem ist eher angebracht, wenn viele Clients gleichzeitig
schreiben oder gemeinsame Netzwerkabfragen benötigen.
[SQLite: Einsatzgebiete und Grenzen](https://www.sqlite.org/whentouse.html).

Das ist keine pauschale Zusage für die Last von zwei Jahren. Der derzeitige
Hostpfad gleicht beim Öffnen und vor einer Aufnahme die Originaldateiliste mit
dem Index ab. Langfristig können Dateianzahl, Verzeichnisabgleich und wiederholtes
Lesen großer Zustände aufwendig werden. Im Pilot sind deshalb Dateianzahl,
Aufnahmelatenz, Replaydauer, Ereignisse pro Sekunde, Nutz-/Index-/Stagingbytes und
Backupbedarf zu messen. Eine spätere Bündelung in größere unveränderliche
Dateisegmente wäre ebenso eine Option wie ein zusätzlicher Datenbankindex.

Die erneute Speicherbewertung nach drei und sechs Monaten bleibt vorgesehen;
Überlauf und auffälliges Wachstum verlangen schon während des Piloten eine
frühere Anpassung. Wiederholt gespeicherte Lernzustände und die Berichtshäufigkeit
können den Platzbedarf stärker beeinflussen als die Wahl der Datenbank.

## 2. Wann PostgreSQL oder InfluxDB helfen

| Speicher | Eignung für dieses Projekt | Entscheidung |
| --- | --- | --- |
| Komprimierte Originaldateien + SQLite | Verlustfreie Eingangsbasis, einfacher lokaler Betrieb, eingefrorene Versuche und Wiederherstellung | Jetzt verwenden |
| PostgreSQL | Gemeinsame Abfragen über Quellen, Wettermodelle, Vorlaufzeiten, Qualitätszustände und Versuchsergebnisse; mehrere parallele Verbraucher | Später bei gemessenem Bedarf ergänzen |
| InfluxDB | Messkurven, Betriebskennzahlen, Fehlerquoten und Visualisierung abgeleiteter Zeitreihen | Optional; kein geplanter Ersatz der Originaldateien |

Für einen späteren PostgreSQL-Ausbau sollten die Originaldateien weiterhin
unverändert bleiben. Tabellen können sie über Hash und Dateiverweis referenzieren
und häufig abgefragte Felder gezielt indexieren. Eine Identität aus Quelle,
Generation und Sequenz bewahrt mehrere Versionen derselben Zielzeit. Neu erzeugte
Auswertungen bekommen eigene Software-/Parameter-/Eingangshashes. Zuerst die
abgeleiteten Tabellen aus einem eingefrorenen Datensatz aufbauen und vollständige
Abfragen gegen den bisherigen Leser vergleichen; erst dann Verbraucher umstellen.

PostgreSQL unterstützt indexierbares `jsonb`; dieses erhält jedoch weder die
ursprüngliche JSON-Schlüsselreihenfolge noch doppelte Schlüssel oder Whitespace.
Für bytegenaue Originalnachweise bleiben daher die unveränderten Bytes maßgeblich.
[PostgreSQL: JSON-Datentypen](https://www.postgresql.org/docs/current/datatype-json.html).

Bei InfluxDB OSS v2 bestimmt die Kombination aus Measurement, Tagmenge und
Zeitstempel die Punktidentität. Wiederholte Schreibvorgänge vereinigen Felder
und ersetzen gleichnamige Werte. Eine naive Ablage allein nach Prognosezielzeit
könnte dadurch frühere Prognoserevisionen verlieren. Eine explizite zusätzliche
Revisionsidentität wäre erforderlich; künstlich verschobene Originalzeitstempel
sind für unseren Nachweis ungeeignet.
[InfluxDB OSS v2: doppelte Datenpunkte](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/duplicate-points/).
Andere InfluxDB-Versionen benötigen einen eigenen Schema-/Semantikabgleich.

Ein PostgreSQL- oder InfluxDB-Backend ist durch diese Entscheidung **nicht
implementiert oder aktiviert**. Die spätere Erweiterung betrifft den Archivhost;
HA benötigt dafür keine Datenbankzugangsdaten.

## 3. Der Archivhost holt Daten ab

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant P as Begrenzter HA-Exportpuffer
    participant C as Collector auf dem Archivhost
    participant A as Originaldateien und SQLite-Index
    HA->>P: Originaleingaben, Lernversuche und Prognosen
    C->>HA: Authentifizierter Exportaufruf mit letztem Cursor
    HA->>P: Begrenzte Seite lesen
    P-->>C: Ereignisse, Prüfsummen, Folgekursor, Lückenstatus
    C->>A: Originalpaket dauerhaft schreiben
    C->>A: Index und lokalen Cursor bestätigen
    Note over C,A: Bei Abbruch wiederholen; bestätigte Ereignisse nicht doppelt zählen
```

Vorgesehen ist ein Timer auf dem Archivhost, der den Collector alle fünf Minuten
je HA-Eintrag startet. `scripts/archive.py collect` verbindet sich mit HAs
`/api/websocket`, authentifiziert sich mit `HA_TOKEN` und ruft ausschließlich den
nativen Administrator-Lesedienst `adaptive_solar.export_archive` mit
`return_response=true` auf. HA liefert Seiten mit Generation, Sequenz und Cursor.
[HA: WebSocket-Authentifizierung und Aktionen](https://contributors.home-assistant.io/core/internals/websocket-api/).

`HA_URL` und `HA_TOKEN` kommen aus der geschützten Prozessumgebung auf dem Host.
Der Dienst verlangt Administratorberechtigung; das ist kein eigens auf diesen
einen Dienst beschränkter HA-Token. Der Collector benutzt ihn nur zum Lesen des
Exports. Die Verbindung benötigt einen erreichbaren HA-Endpunkt; bei einer
HTTPS-Basisadresse verwendet der Helfer `wss://`, bei HTTP `ws://`. Der konkrete
Netzwerk-/TLS-Zugang gehört zur privaten Inbetriebnahme.

Der Cursor wird **auf dem Archivhost** erst nach dauerhafter Originalspeicherung
und erfolgreicher Indextransaktion fortgeschrieben. Es gibt keinen Löschbefehl
oder eine Bestätigung, die anschließend HA-Zeilen entfernt. HA bereinigt seinen
eigenen Puffer anhand der festen Grenzen. Wiederholte Seiten nach einem Abbruch
sind idempotent; Prüfsummen- oder Inhaltswidersprüche werden abgelehnt.

Bei ausgefallenem Host läuft die Prognose weiter. Der Puffer überbrückt den
Ausfall nur innerhalb seiner Grenzen: 64 MiB Ereignisinhalt, 10.000 Ereignisse,
bis zu 72 Stunden bei weiteren Schreibvorgängen. Bei einem Ereignis pro Sekunde
würde allein die Zeilengrenze rechnerisch nach etwa 2 Stunden 47 Minuten greifen;
weitere Prognose-/Chunkereignisse verkürzen dies. 72 Stunden sind daher keine
garantierte Ausfalldauer. Überlauf oder eine neue Generation werden sichtbar.

Zusätzliche Forschungswettermodelle ruft der Host direkt bei Open-Meteo ab.
Recorder-/Referenzcollector lesen die jeweiligen HA-Schnittstellen separat.
Diese Abrufe ersetzen nicht den Export der Wetterantworten, die HA tatsächlich
bei seiner ursprünglichen Prognose benutzt hat.

Einrichtungsbefehle, Qualitätsregeln und Replay:
[Originaldaten archivieren und Prognosen wiederholen](archivbetrieb.md).
