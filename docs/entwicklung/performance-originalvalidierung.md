# Redundante Baumdurchläufe beim Originallesen vermeiden

Stand: 03.11.2026. Lokaler Entwicklungskandidat, keine produktive Aktivierung.
Der gebundene lokale Vergleich und die dokumentierten Abnahmekriterien sind
erfüllt; die operatorbezogenen Einzelwerte bleiben in der privaten Betriebsdokumentation.
Die [Phasenmessung](performance-qualitaetsphasen.md) identifiziert den Archivscan
mit Originalvalidierung als ersten zu untersuchenden Kostenbereich. Der hier
beschriebene Kandidat verändert ausschließlich dessen gemeinsame
[`archive.py`](../../custom_components/adaptive_solar/core/archive.py).

## 1. Änderung und Vertrauensgrenze

Der Originalreader prüft weiterhin komprimierte und dekomprimierte Größe,
Dateihash, Wrapper, komplette Seite und jedes enthaltene Envelope. Beim
kanonischen Serialisieren eines Pythonobjekts prüft `canonical_bytes()` jeden
verschachtelten Objektschlüssel: JSON darf keine Python-Schlüsseltypen still
in Strings umwandeln. Diese öffentliche Funktion bleibt unverändert.

Nach dem frischen, hookfreien `json.loads(raw)` besitzt der Originalreader
einen lokalen Baum aus JSON-Werten. Die strenge kanonische Seitenprüfung
besucht weiterhin den **gesamten** Baum und schützt auch die bisherigen
Rekursionsgrenzen. Erst danach verwenden die zwei kanonischen
Envelope-Serialisierungen einen privaten Encoder ohne weitere
Python-Schlüsselbaumdurchläufe. UTF-8, Sortierung, Trennzeichen und das Verbot
nichtendlicher Zahlen bleiben identisch. Envelopehash und Ereignisgröße werden
weiterhin aus den vollständigen kanonischen Bytes geprüft.

Der private Pfad wird ausschließlich im Originalreader verwendet. Der frisch
geparste Baum wird während dieser Prüfung nicht verändert oder nach außen
gegeben. Öffentliche `validate_page()`- und `validate_envelope()`-Aufrufe auf
beliebigen Pythonobjekten bleiben streng. Es gibt weder einen JSON-Schalter
zum Überspringen der Prüfung noch einen Prüfungs- oder Indexcache.

Validatorfabriken teilen die Schema-/Hash-/Grenzprüfungen zwischen beiden
Pfaden, ohne zusätzliche Aufrufrahmen in die bisherigen öffentlichen
Prüfpfade einzufügen. Der öffentliche Seitenvalidator verwendet weiterhin den
öffentlichen Envelopevalidator. Damit bleiben auch dessen direkte Aufrufe
und die vorhandene Instrumentierung nutzbar.

Ein vollständiges Entfernen des Seitenbaumdurchlaufs wurde verworfen:
Grenztests zeigten, dass damit zuvor abgewiesene tief verschachtelte Eingaben
angenommen würden. Der verbleibende strenge Seitenscan ist deshalb Teil der
Verhaltensgleichheit, kein optionaler Sicherheitsaufschlag.

## 2. Abnahme

Die Prüfungen unterscheiden Format-/Verhaltensgleichheit und Geschwindigkeit:

- Unveränderte kanonische Bytes für Unicode, Fließkommazahlen und verschachtelte
  JSON-Werte; unveränderte Originalbytes und Checksummen.
- Weiterhin Ablehnung nichtendlicher Werte einschließlich `NaN`, `Infinity`
  und überlaufender JSON-Exponenten, falscher Schemas, Sequenzen, Generationen,
  Cursor, Hashes und Größen. Öffentliche Python-APIs weisen Nicht-Stringschlüssel
  und Zyklen weiterhin zurück.
- Differentialvergleiche gegen die eingefrorene Referenz für Listen, Objekte
  und gemischte Bäume nahe mehreren Python-Rekursionsgrenzen. Der vollständige
  Originalreader und die öffentlichen Einstiegspunkte müssen übereinstimmen.
- Ursprüngliche Receipt-/Evidenzzeitstempel, Quellen-/Konfigurations-/Producerpins,
  Stundenentscheidungen, Messwerte und Ausschlüsse bleiben exakt. Neue
  Ableitungs-, Abschluss- und Verfügbarkeitszeiten bleiben real und werden
  gegen die Chronologieinvarianten geprüft; sie dürfen zwischen Läufen abweichen.

Die Verhaltenstests liegen in
[`test_archive_json_validation.py`](../../tests/test_archive_json_validation.py).
Die bestehenden Archiv-, Retentions-, Wiederherstellungs-, Replay- und
HA-Tests bleiben erforderlich; bestandene Archivtests ersetzen keine
Produktivabnahme.

## 3. Laufzeitvergleich

Referenz und Kandidat verwenden denselben vollständig eingefrorenen lokalen
Eingabesatz, Interpreter und Messhelfer. Der versionspassende öffentliche
Referenzquellbaum und seine Kandidatenkopie unterscheiden sich ausschließlich
in `core/archive.py`. Alle Quell- und Eingabedateien werden vor und nach den
Läufen erneut gehasht. Eine positive Kontrolle ergänzt den vollständigen Satz.

Für den lokalen Vergleich werden zwei uninstrumentierte Läufe je Arm in der
Reihenfolge Referenz–Kandidat–Kandidat–Referenz verwendet. Mediane und
Einzelwerte werden berichtet; zwei Läufe liefern keine belastbare p95 oder
statistische Absicherung. Der Betriebssystemcache ist wegen der vorausgehenden
Byteprüfung vorgewärmt. Keine Tests oder anderen Benchmarks parallel starten.
Der genaue Ausführungsplan einschließlich Workerbefehlen gehört zum Messbeleg.

Vor der Ergebnisauswertung festgelegte Kriterien für diesen Kandidaten:
mindestens 10 % weniger Wall- und CPU-Zeit im vollständigen lokalen Satz,
höchstens 10 % höherer Spitzen-RAM und keine Verschlechterung der Wallzeit der
positiven Kontrolle um mehr als 10 %. Exakte fachliche Gleichheit und unveränderte
Originale sind unabhängig von der Geschwindigkeit zwingend. Das sind
Entwicklungskriterien, keine neue fachliche oder produktive Freigabeschwelle.

Der [Phasenmesshelfer](performance-qualitaetsphasen.md) erkennt zusätzlich die
privaten Encoder-/Validatorfunktionen, soweit die gewählte Quellbasis diese
besitzt. Inklusive Phasenzeiten bleiben überlappend und dürfen nicht zur
Berechnung des Beschleunigungsfaktors verwendet werden. Ältere Quellstände
ohne diese privaten Funktionen bleiben messbar.

Operatorbezogene Rohdaten, Befehle und konkrete Laufzeit-/Integritätsbelege
bleiben unter ignorierten lokalen Pfaden. Der kleinere historische Datensatz
ist kein vollständiger Nachlauf des späteren Hostpiloten. Aus diesem Vergleich
folgt weder eine Prognosegüteverbesserung noch ein Beschleunigungsversprechen
für beliebige Archive oder Hardware.

## 4. Weitere Arbeit und Aktivierung

Dieser Schritt entfernt keine Vollscans: Jede ausgewählte Originalseite wird
weiterhin vollständig gelesen und geprüft. Eine spätere gezielte Batchauswahl
muss Anker, Gegenbelege anderer Generationen, Payloadabhängigkeiten und
Auswahlbudgets vollständig erhalten. Auch Änderungen an Trainingsjoin,
Physik-/ML-Aufrufen und Historienpflege sind getrennte Arbeitspakete.

Der anschließende [lokale Auswahlprototyp](performance-archivauswahl.md)
untersucht diese Auswahl nur für einen vollständig gebundenen eingefrorenen
Satz. Sein vollständiger Kaltaufbau und seine Wiederverwendung werden getrennt
gemessen; er ersetzt keinen fortlaufenden Archivscan im Produktivbetrieb.

Format und Datenverträge bleiben unverändert; es gibt keine Migration und
keine neue Abhängigkeit. Lokale Implementierung, Tests, unabhängiger Review
und Laufzeitvergleich sind getrennt von Release, Installation und produktiver
Abnahme. Ein Rollback des Kandidaten besteht im Wiederherstellen der vorherigen
Archivimplementierung; es werden keine Originale oder Indizes umgeschrieben.
Eine spätere Installation geänderter Komponentendateien ändert deren
Producer-Quellhash. Daraus folgt keine automatische Verlängerung oder Anpassung
einer bestehenden Quellenpolicy; Originalpins und eine künftige Installation
bleiben getrennt zu behandeln.
