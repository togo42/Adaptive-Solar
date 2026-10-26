# Direktstrahl-Verschattung aus Globalstrahlung und Stufenleistung

Stand: 26.10.2026. Spezifikation und Umsetzungsstand gegen Codebasis **0.2.11**.
Die Arbeitspakete `VS-01` bis `VS-06` sind im Code und in der Testsuite umgesetzt;
`VS-00` bleibt die anlagenseitige Konfigurationsvorgabe ohne Codeänderung. Ein
prospektiver Gütevergleich ist damit noch nicht durchgeführt. Eine gefüllte
Tabelle ist kein Nachweis eines Forecastvorsprungs. Dafür bleibt
[Validierung](validierung.md) zuständig. Einordnung der übrigen Modellthemen:
[Analyse](adaptive-solar-analyse.md), [Bewertung](adaptive-solar-bewertung.md),
[Vertrag](implementation-contract.md).

## 1. Zweck

Das Dokument legt fest, wie nahe Teilverschattung großer Modulflächen gelernt
werden soll, wenn kein belastbares Horizontprofil messbar ist und zwei Flächen
dieselbe Ausgangsstufe und denselben Zähler teilen. Abschnitt 6 schneidet diese
Vorgabe in einzeln abnahmefähige Pakete. Private Standortzuordnungen und
Rohmessungen bleiben außerhalb des Dokuments und außerhalb von Git.

## 2. Entscheidung

Hauswand und Schuppen, oder jedes andere Paar unterschiedlich ausgerichteter
Flächen an einem Zähler, bleiben zwei Strings mit eigener Neigung, Ausrichtung
und kWp. Die Physik rechnet beide unverschattet und addiert sie. Die Messung
sieht nur die Summe.

Nahe Schatten sind ein gleitender Anteil des Direktstrahls, abhängig von Azimut
und Sonnenhöhe. Parallaxe über die Modulfläche und elektrische Verluste durch
Bypassdioden stecken in diesem Anteil. Ein Horizontprofil bildet das nicht ab.
Die gemeinsame Leistung bildet den wirksamen Anteil ab, sobald die
Globalstrahlung die Stunde als klar kennzeichnet.

Der gelernte Faktor `t` gilt für die ganze Stufe. Beide Strings erhalten denselben
Faktor. Getrennte Flächenprognosen entstehen daraus nicht. Dafür wären eigene
Messpunkte nötig.

Der Faktor skaliert nur den Direktanteil. Der Diffusanteil bleibt. Eine an klaren
Stunden gelernte Verschattung darf einen bedeckten Tag nicht mit abschatten.
Wetterfehler bleiben beim bestehenden Residuallernen.

## 3. Abgrenzung

Diese Vorgabe ändert nicht:

- Lerner-Schwellen, Regimetrennung, Lead-Bins und die 120-Tage-Aufbewahrung
- Ensemble-Mittel, Kohortenregeln und den GHI-Nowcast einschließlich seiner 15°-Grenze
- Horizontrechnung und Morgen-/Abenddämpfung als Formeln
- die Zuordnung eines Zählers zu genau einer Stufe

Nicht Teil der ersten Pakete sind Nachbarschaftsfüllung leerer Fenster, eine
Laub- oder Monatsachse, längere Roharchive, Ensemblegewichte und getrennte
Prognosen je Fläche. Eine Laubsaison ist erst dann eine eigene Erweiterung, wenn
Gebäudekanten in der Tabelle sitzen und Bäume den übrigen Jahresgang erklären.

## 4. Normatives Verhalten

### 4.1 Tabelle

Neue, HA-freie Einheit `core/shading.py`. Pro Stufe ein Raster von 10° Azimut
und 5° Sonnenhöhe über der scheinbaren Sonnenhöhe aus der bestehenden
Sonnenstandsrechnung. Azimutfenster sind `floor(azimuth / 10) mod 36` auf
`[0, 360)`. Höhenfenster sind `floor(elevation / 5)` auf `[0, 90)`. Darüber liegt
kein Fenster.

Jedes Fenster speichert höchstens die letzten 24 Aufnahmen. Eine Aufnahme ist
eine Viertelstunde in UTC und ein Faktor. Dieselbe Viertelstunde ersetzt die
ältere Aufnahme. Freigegeben ist der Median, sobald fünf verschiedene
Viertelstunden gespeichert sind. Sonst ist der Faktor 1. Leere Fenster werden
nicht aus Nachbarn gefüllt.

### 4.2 Faktor

Am Leistungszeitpunkt werden zwei unverschattete Stufenrechnungen ausgeführt.
`P0` setzt den Direktanteil auf 0. `P1` behält ihn. Beide nutzen dieselbe gültige
Modellkohorte und dieselbe Momentan-Wetterform wie die bestehende
Nowcast-Referenz, verlangen jedoch unabhängig von der 15°-/150-W/m²-Schwelle des
veröffentlichten GHI-Nowcasts eine eigenständig qualifizierte, zum
Leistungszeitpunkt passende GHI-Momentanreferenz aller Kohortenmitglieder
(mindestens 10° Sonnenhöhe und 50 W/m² Haurwitz-Klarhimmel). Fehlt diese
Referenz, gibt es keine Aufnahme.
Der auf die jeweilige Momentan-Wetterform normierte Paar-Gain wird für `P0/P1`
voll angewendet, auch bei einer bis zu fünf Minuten älteren oder jüngeren
GHI-Meldung. Eine zeitliche Dämpfung Richtung 1 gehört zum kurzlebigen Nowcast,
nicht zur dauerhaften Schattenaufnahme. Die Paarung nimmt innerhalb dieser
fünf Minuten einen gleichbleibenden normierten Strahlungsfaktor an; sie ist keine
Messung des zwischenzeitlichen Wetterverlaufs.
Auch eine an den Grenzen 0,35/1,65 oder an den Strahlungsobergrenzen gekappte
GHI-Normalisierung liefert keine Schattenaufnahme: Ihr verbleibender Wetterfehler
darf nicht dauerhaft in die Tabelle gelangen. Der kurzlebige GHI-Nowcast behält
seine bisherigen Grenzen.

`t = clip((P_messung - P0) / (P1 - P0), 0, 1)`

Eine Aufnahme entsteht nur, wenn alle Bedingungen gelten:

- Sonnenhöhe mindestens 10° und Haurwitz-Klarhimmel mindestens 50 W/m²
- Clearness-Index `gemessene Globalstrahlung / Haurwitz-Klarhimmel` mindestens 0,6
- Leistungs- und Strahlungsmeldung sind frisch und höchstens fünf Minuten auseinander. Frisch heißt wie heute: Globalstrahlung höchstens fünf Minuten, Leistung höchstens fünfzehn Minuten, keine restaurierten Zustände
- Messung gültig und nicht abgeregelt, nach denselben Sperren wie der Leistungsnowcast
- Direktanteil `P1 - P0` mindestens 40 Prozent von `P1` und mindestens `max(30 W, 3 Prozent der Stufengrenze)`
- weder `P_messung` noch `P1` erreicht 98 Prozent der Stufengrenze
- höchstens eine Aufnahme je Stufe, Fenster und UTC-Viertelstunde

Der Clearness-Index wählt klare Stunden aus. Er ist kein Feature für eine
Prognose über dieses Fenster hinaus. Die Prognose liest nur Sonnenstand und den
freigegebenen Faktor.

### 4.3 Anwendung

`string_dc_power` erhält den Stufenfaktor, Standard 1. Er multipliziert
`poa_direct`, nachdem ein konfigurierter Horizont den Direktanteil bereits
begrenzt hat. Diffuslicht, Modultemperatur, Stringverlust, Dämpfung und der eine
Stufenclip bleiben in der bisherigen Reihenfolge. `inverter_power` gibt denselben
Faktor an alle Strings der Stufe.

`ForecastEngine` bestimmt den Faktor aus der Tabelle:

- Stunden- und Teilintervallprognose am Sonnenstand des Intervallmittelpunkts
- Nowcast-Referenz am Sonnenstand des Leistungszeitpunkts

Alle Wettermodelle einer Stufe und beide Regime verwenden diesen Faktor. Die
Referenz des Leistungsnowcasts enthält die Verschattung. Eine stabile
Teilverschattung ist dann kein abklingendes Leistungsresiduum mehr.

Solange kein Fenster freigegeben ist, bleibt der Faktor 1. Bestehende Prognosen
ohne Tabelle bleiben damit numerisch unverändert.

### 4.4 Speicherung und Lernbaseline

Die Tabelle liegt im bestehenden `history_v2`-Store unter `beam_shade_v1`. Sie
geht nicht in `history_fingerprint` ein. Ein Store ohne den Schlüssel lädt eine
leere Tabelle. Messintervalle und ausgegebene Tages-Snapshots bleiben nach den
bisherigen Provenienzregeln erhalten.

Ein Wechsel der physischen Historienbindung verwirft den Primary wie bisher und
damit auch die Tabelle. Neue kWp, Ausrichtung oder ein zusätzlicher String machen
alte Faktoren gegenstandslos. Ein Wechsel der für die Schattenaufnahme maßgeblichen
Sensor- oder Wettermodellbindungen (`shade_fingerprint`, d. h. ohne `forecast_days`)
setzt `beam_shade_v1` ebenfalls auf eine leere Tabelle zurück, während gültige
Messintervalle und Tages-Snapshots erhalten bleiben.

Der Featurevertrag wird auf `beam-shade-table-v1` gesetzt. Forecastzeilen, deren
Baseline noch ohne Tabelle (`beam_shade_factor = 1,0`) oder in einer
inkompatiblen Schatten-Baselinephase (Abweichung über `SHADE_BASELINE_TOLERANCE = 0,10`
oder Wechsel zwischen unverschattet und verschattet) desselben Sonnenstandsfensters
entstand, werden beim Training als `stale_beam_shade_baseline` ausgeschlossen,
ohne das unveränderliche Archiv umzuschreiben; kleinere Medianschwankungen
innerhalb einer freigegebenen verschatteten Baselinephase bleiben kompatibel. Bis
für ein neu freigegebenes Fenster eigene Trainings- und Validierungsstützung
vorliegt, bleibt die Prognose dort bei `physics_unvalidated_shade_baseline`;
Holdout-Validierung und empirische Kalibrierung bewerten dieselbe
Schattenstützungs- und Rückfallregel wie `predict`.
Gemessene Energie bleibt. Die Aktivierungsschwellen des Lerners bleiben. Spätere
Vertragswechsel dürfen `beam_shade_v1` nur verwerfen, wenn sich die Definition
von `t` ändert.

### 4.5 Diagnose

Je Stufe erscheint unter dem bestehenden Lernstatus ein Block `beam_shade`. Der
Qualitätsstatus gibt `learning` bereits aus, die Diagnose ebenfalls. Felder:

| Feld | Inhalt |
| --- | --- |
| `azimuth_bin_deg`, `elevation_bin_deg` | Fenster des aktuellen Sonnenstands, sonst leer |
| `transmittance` | freigegebener Faktor, sonst 1 |
| `samples` | gespeicherte Viertelstunden dieses Fensters |
| `released` | wahr ab fünf Viertelstunden |
| `filled_bins` | Zahl freigegebener Fenster der Stufe |
| `last_rejection` | letzter Ablehnungsgrund oder leer |

Ablehnungsgründe sind `low_elevation`, `low_clearness`, `stale_or_unpaired`,
`low_beam`, `at_cap`, `curtailed_or_invalid`, `no_reference` und
`insufficient_samples`. Mehrere Gründe dürfen zugleich gelten. Die Diagnose ändert
keine Prognose.

### 4.6 Konfiguration ohne Code

Die beteiligten Flächen werden zwei Strings an einer Stufe. Nahe Dächer, Bäume
und Wandvorsprünge bleiben ohne Horizontpunkt. Ein einzelner Horizontpunkt gilt
für alle Azimute und würde den Direktanteil abschneiden, den die Tabelle lernen
soll. Eine ferne Silhouette, die das gesamte Feld deckt, darf bleiben. Sie wirkt
vor dem Faktor. Dieselbe Kante darf nicht zusätzlich als Morgen- oder
Abenddämpfung eingetragen werden. Für diese Flächen bleibt die Dämpfung aus.
Globalstrahlung und die gemeinsame Stufenleistung bleiben die einzigen Sensoren
der Tabelle.

## 5. Eingefrorene Parameter

Diese Werte gelten für die ersten Pakete. Eine Änderung ist eine neue
Tabellendefinition und kein stilles Nachjustieren.

| Parameter | Wert |
| --- | --- |
| Azimutfenster | 10° |
| Höhenfenster | 5° |
| Freigabe | Median ab 5 verschiedenen UTC-Viertelstunden |
| Speicher je Fenster | 24 Aufnahmen |
| Faktorgrenzen | 0 bis 1, sonst 1 |
| Mindest-Sonnenhöhe | 10° |
| Mindest-Klarhimmel | 50 W/m² Haurwitz |
| Mindest-Clearness-Index | 0,6 |
| Mindest-Direktanteil | 40 Prozent von `P1` und `max(30 W, 3 Prozent der Stufengrenze)` |
| Grenze für die Aufnahme | 98 Prozent der Stufengrenze |
| Paarungsfenster | Globalstrahlung und Leistung höchstens 5 Minuten auseinander |
| Featurevertrag | `beam-shade-table-v1` |
| Store-Schlüssel | `beam_shade_v1` |

## 6. Ableitbare Arbeitspakete

Die Pakete sind einzeln prüfbare Zuschnitte. `VS-01` bis `VS-06` sind umgesetzt
und durch Verhaltenstests abgedeckt; `VS-00` betrifft die lokale
Anlagenkonfiguration. Kurzzeichen `VS` kollidieren nicht mit `AS-OPT`. Aufwand
ist relativ zu diesem Repository: S = ein Modul und seine Tests, M = mehrere
Module.

### VS-00 Flächen an einer Stufe beschreiben

**Priorität P0 · Aufwand S · Voraussetzung:** keine Codeänderung.

**Ziel und Ergebnis:** Die beteiligten Flächen sind zwei Strings einer Stufe mit
eigener Geometrie und kWp. Nahe Hindernisse haben keine Horizontpunkte. Die
Dämpfung dieser Strings ist 0. Globalstrahlung und die gemeinsame Leistung sind
gebunden. Private Zuordnungen bleiben außerhalb von Git.

**Abnahme:**

- Jede Fläche hat Neigung, Azimut und kWp. Beide hängen an derselben Stufe und demselben Zähler.
- Für nahe Verschattung ist `horizon` leer. Eine bewusst eingetragene ferne Vollfeld-Silhouette ist als solche benannt.
- `damping_morning` und `damping_evening` sind 0.
- Ein physischer Fingerprintwechsel durch diese Korrektur ist vor dem Speichern bekannt. Die daran hängende Historie wird nicht nebenbei verworfen.

**Betroffene Stellen:** Konfiguration der Stufe, [Bedienung](bedienung.md)
Abschnitt PV-String. Kein Laufzeitcode.

### VS-01 Schattentabelle

**Priorität P0 · Aufwand S · Voraussetzung:** keine.

**Ziel und Ergebnis:** `core/shading.py` verwaltet Fenster, Aufnahmen, Median und
Freigabe. Ohne freigegebenes Fenster ist der Faktor 1. Die Einheit kennt weder
Home Assistant noch Wetterabruf.

**Abnahme:**

- Azimut 0° und 360° treffen dasselbe Fenster. Die Höhe 89,9° hat ein Fenster, negative Höhe und Höhe ab 90° keines.
- Die fünfte verschiedene Viertelstunde gibt den Median frei. Vier bleiben bei Faktor 1.
- Dieselbe Viertelstunde ersetzt den Faktor und zählt nicht als neue Stunde.
- Die 25. Viertelstunde verwirft die älteste. Der Median verwendet nur die gespeicherten Werte.
- Faktoren außerhalb von 0 bis 1 werden vor dem Speichern begrenzt. Eine leere Tabelle lässt jede Abfrage bei 1.
- Roundtrip der serialisierbaren Form stellt Fenster, Zeiten und Faktoren wieder her. Unbekannte oder beschädigte Inhalte laden als leere Tabelle, ohne eine Ausnahme in die Prognose zu werfen.

**Betroffene Stellen:** `core/shading.py`, `tests/test_shading.py`.

### VS-02 Faktor in der Stufenphysik

**Priorität P0 · Aufwand S · Voraussetzung:** VS-01 für den Faktor, die Physik
selbst kann mit einem übergebenen Skalar entstehen.

**Ziel und Ergebnis:** `string_dc_power` und `inverter_power` multiplizieren den
Direktanteil mit einem Stufenfaktor nach dem Horizont und vor Temperatur,
Verlust, Dämpfung und Clip. Der Standardfaktor 1 lässt die bisherigen
Physikzahlen unverändert.

**Abnahme:**

- Faktor 1 reproduziert die bisherige String- und Stufenleistung, einschließlich Horizont, Dämpfung, AC-Wirkungsgrad, DC-Verlust und einmaligem Clip.
- Faktor 0 entfernt den Direktanteil und behält den Diffusanteil. Ein teilweiser Faktor liegt dazwischen und wirkt auf beide Strings der Stufe gleich.
- Temperatur und Clip sehen die verschattete Summe. Ein Faktor verändert die Wetterkomponenten nicht.
- Nicht endliche Faktoren werden abgewiesen und nicht als volle Leistung ausgegeben.

**Betroffene Stellen:** `core/physics.py`, `tests/test_physics.py`.

### VS-03 Anwendung in Prognose und Nowcast-Referenz

**Priorität P0 · Aufwand M · Voraussetzung:** VS-02.

**Ziel und Ergebnis:** Die Engine liest je Stufe einen Faktor zum Sonnenstand des
Ausgabeintervalls und denselben Faktor für jedes Wettermodell. Die
Momentanreferenz liest den Faktor zum Leistungszeitpunkt. Eine leere Tabelle
ändert keine Prognose.

**Abnahme:**

- Ein freigegebenes Fenster mit Faktor 0,5 senkt in einer klaren Stunde nur den Direktanteil. Der Diffusfall bleibt bei Faktor 1, weil sein Fenster leer ist oder weil der gespeicherte Faktor nur den Direktanteil skaliert.
- Alle Mitglieder einer Kohorte verwenden denselben Faktor. Ein fehlendes Mitglied ändert den Faktor der übrigen nicht.
- Die Nowcast-Referenz einer stabilen Teilverschattung liegt bei der verschatteten Physik. Der zusätzliche Leistungsrest entsteht nicht aus dem schon angewendeten Faktor.
- Teilintervalle am Ausgabezeitpunkt verwenden den Sonnenstand ihres eigenen Mittelpunkts.
- Nacht und fehlende Kohorte bleiben Lücken. Der Faktor füllt sie nicht.

**Betroffene Stellen:** `core/engine.py`, `tests/test_engine.py`,
`tests/test_nowcast_reference.py`, `tests/test_irradiance.py`.

### VS-04 Aufnahme, Store und Featurevertrag

**Priorität P0 · Aufwand M · Voraussetzung:** VS-01 und VS-03.

**Ziel und Ergebnis:** Der Coordinator nimmt klare, gültige Leistungsmeldungen
in die Tabelle auf und speichert sie unter `beam_shade_v1`. Der
Featurevertrag `beam-shade-table-v1` trennt alte Baselines ohne Tabelle von neuen
Baselines. Lerner-Schwellen und Messhistorie bleiben.

**Abnahme:**

- Die Aufnahmeregeln aus Abschnitt 4.2 gelten einschließlich Clearness-Index, Viertelstunde, Grenze, Abregelung, Messgültigkeit und fehlender Momentanreferenz. Abgelehnte Meldungen schreiben nichts.
- Wiederherstellen ohne Schlüssel ergibt eine leere Tabelle und behält Messintervalle. Ein passender `history_fingerprint` bleibt gültig. Beschädigte Tabelleninhalte werden leer geladen und verwerfen den übrigen Primary nicht.
- Ein physischer Fingerprintwechsel verwirft die Tabelle zusammen mit dem Primary. Ein reiner Vertragswechsel auf `beam-shade-table-v1` verwirft Forecastfeatures und behält Messintervalle, Tages-Snapshots und eine bereits gültige Tabelle.
- Alte Forecastzeilen ohne den neuen Vertrag trainieren nicht gegen neue verschattete Baselines.
- Aufbewahrung von 120 Tagen, 60.000 Forecastzeilen und 30.000 Messzeilen bleibt unverändert. Die Tabelle zählt nicht gegen diese Zeilengrenzen.
- Beide DST-Wechsel behalten die UTC-Viertelstunde und den Sonnenstand als Schlüssel.

**Betroffene Stellen:** `coordinator.py`, `const.py` nur falls ein gemeinsamer
Vertragsname dort liegen muss, Persistenztests unter `tests/`.

### VS-05 Diagnose

**Priorität P1 · Aufwand S · Voraussetzung:** VS-04.

**Ziel und Ergebnis:** Der Lernstatus jeder Stufe trägt `beam_shade` mit den
Feldern aus Abschnitt 4.5. Qualitätsattribut und Diagnose zeigen denselben Block.
Die Prognosewerte bleiben von der Diagnose unberührt.

**Abnahme:**

- Aktuelles Fenster, Faktor, Samplezahl, Freigabe, Zahl gefüllter Fenster und letzter Ablehnungsgrund sind je Stufe lesbar.
- Eine Stufe ohne Sonne oder ohne Tabelle zeigt Faktor 1, keine Freigabe und keine erfundenen Fenster.
- Ablehnungsgründe können sich überlappen und werden nicht zu einer einzigen Ursache zusammengezogen.

**Betroffene Stellen:** `coordinator.py`, `sensor.py` nur falls der bestehende
Lernblock den neuen Schlüssel nicht bereits durchreicht, `diagnostics.py`,
`tests/test_quality.py`.

### VS-06 Vertrag und Bedienung

**Priorität P1 · Aufwand S · Voraussetzung:** eingefrorene Parameter aus Abschnitt 5.
Kann parallel zu VS-01 geschrieben werden und wird mit VS-04 gegen den Code gelegt.

**Ziel und Ergebnis:** Vertrag und Bedienung beschreiben Faktor, Aufnahmeregeln,
leere Fenster, den gemeinsamen Stufenfaktor und die Konsequenz eines
Fingerprintwechsels. Die Anleitung nennt die Konfiguration aus VS-00.

**Abnahme:**

- [Implementierungsvertrag](implementation-contract.md) nennt Anwendungsstelle, Standardfaktor 1, Store-Schlüssel und Featurevertrag.
- [Bedienung](bedienung.md) unterscheidet Horizont, Dämpfung und gelernte Direktstrahl-Tabelle.
- Das Dokument behauptet keinen gemessenen Gütegewinn.

**Betroffene Stellen:** `docs/implementation-contract.md`, `docs/bedienung.md`.

## 7. Reihenfolge

1. **VS-00** vor produktivem Lernen. Tests dürfen synthetische Strings verwenden, ohne diese Anlagenkorrektur vorwegzunehmen.
2. **VS-01**, danach **VS-02** und **VS-03**. Bis zur ersten freigegebenen Viertelstunde bleibt jede Prognose bei Faktor 1.
3. **VS-04** schaltet Aufnahme und Vertrag zu. **VS-05** und **VS-06** gehören zum selben auslieferbaren Stand, sind aber getrennt prüfbar.
4. Ein prospektiver Vergleich gegen die unverschattete Physik folgt erst, wenn freigegebene Fenster klare und bedeckte Tage abdecken. Er verwendet das Protokoll aus [AS-OPT-01](adaptive-solar-bewertung.md) und ist kein Bestandteil der Pakete VS-01 bis VS-06. Klare Tage prüfen den wandernden Anteil. Bedeckte Tage dürfen nicht unter der bisherigen Diffusprognose liegen.

## 8. Verhältnis zu den bestehenden Optimierungspaketen

| Bestehendes Paket | Verhältnis zu dieser Vorgabe |
| --- | --- |
| AS-OPT-01 | Weiter die Voraussetzung für einen Gütevergleich. Keine Voraussetzung für VS-01 bis VS-06. |
| AS-OPT-02 | Die Tabelle ist klein und läuft nicht im Lerner-Fit. Eine eigene Laufzeitmessung ist kein Vorpaket. |
| AS-OPT-03 und AS-OPT-07 | Unberührt. Modellgewichte ändern den Stufenfaktor nicht. |
| AS-OPT-04 | Unberührt. Die Aufnahme ist kein zusätzlicher Baum-Fit. |
| AS-OPT-05 | Der Clearness-Index dieser Vorgabe filtert Aufnahmen. Er wird kein Lernfeature. AS-OPT-05 bleibt ein späterer Wetterfeature-Versuch auf der schon verschatteten Baseline. |
| AS-OPT-06 | Unberührt. Der Nowcast sieht die verschattete Referenz und glättet sie nicht. |
| AS-OPT-08 und AS-OPT-09 | Unberührt. |

## 9. Nachweisgrenze

VS-01 bis VS-06 belegen Verhalten: Faktor 1 bleibt die alte Prognose, klare
Aufnahmen füllen das getroffene Fenster, der Direktanteil wird skaliert, der
Diffusanteil nicht, Store und Vertrag halten die festgelegte Trennung.
Mindestens 30 gepaarte Zieltage, der Vergleich gegen beide Referenzintegrationen
und jede Aussage über einen geringeren Energiefehler bleiben außerhalb dieser
Pakete und folgen [validierung.md](validierung.md).
