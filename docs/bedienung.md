# Adaptive Solar einrichten und bedienen

Stand: 28.10.2026. Veröffentlichtes Referenzrelease: 0.2.14 einschließlich des
[Messdaten-Nachtrags](messintervalle-92-prozent.md). Der unten beschriebene
Originaldatenexport gehört zum unveröffentlichten Entwicklungszweig vom 28.10.2026;
eine produktive Aktivierung wird damit nicht behauptet. [Installation](installation.md),
[Datenverträge](implementation-contract.md), [Datenschutz](datenschutz.md).

## 1. Anlagenaufteilung vorbereiten

Eine **Ausgangsstufe** ist der unabhängig gemessene Ausgang eines AC-Wechselrichters
oder DC-Ladereglers. Mehrere Solarflächen/Strings an derselben Stufe teilen deren
Leistungsgrenze. Ein **Anlageneintrag** kann mehrere Stufen enthalten; seine Summe
umfasst genau diese Stufen. Ein String mit eigener Ausrichtung ist kein zusätzlicher
Wechselrichter. Fiktive Beispiele: [AC](../examples/site.json), [DC](../examples/site-dc.json).

Ein Gesamtzähler lässt sich nicht mehreren unabhängig lernenden Stufen zuordnen.
PV-Erzeugung am gewählten Messpunkt verwenden, keine Netzbilanz oder Batterieentladung.
Ohne lokale Sensoren sind Wetter-/Physikprognosen möglich; Leistung ermöglicht
kurzfristige Korrekturen, kumulative Energie ermöglicht spätere Lernlabels.

## 2. Schritt Standort

| Feld / JSON-Name | Bedeutung und Standard |
| --- | --- |
| Breitengrad / `latitude` | −90 bis 90°, Vorgabe aus HA |
| Längengrad / `longitude` | −180 bis 180°, Vorgabe aus HA; Koordinaten gehen an Open-Meteo |
| IANA-Zeitzone / `timezone` | Etwa `Europe/Berlin`, Vorgabe aus HA; keine feste UTC-Verschiebung |
| Open-Meteo-Modelle / `weather_models` | Standard `best_match`; mindestens eines. Die UI bietet zusätzlich ICON seamless/global/EU/D2, ECMWF IFS025 und GFS seamless; eigene Kennungen müssen vom Provider unterstützt sein |
| Originaleingaben archivieren / `archive_export` | Standard aus. Separate Eintragsoption für den privaten Originaldatenpuffer; kein Feld der Anlagenphysik. Einzelheiten in [Abschnitt 8](#8-optionalen-originaldatenexport-einrichten) |
| Prognosetage / `forecast_days` | Ganzzahlig 1–7, Standard 7; einschließlich des laufenden lokalen Tages, keine garantierten sieben vollen Folgetage |
| Außentemperatur / `temperature_entity_id` | Optionaler Temperatursensor; °C, °F oder K |
| Wind / `wind_entity_id` | Optionaler Windgeschwindigkeitssensor; m/s, km/h, mph oder kn |
| Globalstrahlung / `irradiance_entity_id` | Optional: echte horizontale Globalstrahlung in W/m² oder kW/m², keine Beleuchtungsstärke in Lux |

Mit `best_match` beginnen. Zusätzliche Wettermodelle werden gleichgewichtet, soweit
sie das jeweilige Intervall gültig abdecken. Mehr Modelle sind kein belegter
Genauigkeitsgewinn. Kurze Modellhorizonte können früh enden; fehlende Werte bleiben
Lücken. GHI braucht höchstens fünf Minuten alte Berichte; andere numerische Eingänge
grundsätzlich höchstens 15 Minuten. Ein aktueller restaurierter Zustand genügt nicht.

## 3. Schritt Wechselrichter oder DC-Laderegler

| Feld / JSON-Name | Bedeutung und Standard |
| --- | --- |
| Stabile Kennung / `id` | Eindeutig im Anlageneintrag; neue UI-Vorgabe etwa `inverter_1`. Nicht ohne Grund ändern: Kennungen sind Teil von Historien-/Entityzuordnungen |
| Ausgabemessgrenze / `output_type` | `ac` oder `dc`; beim Typwechsel alte Leistungs-/Energiebindungen neu wählen |
| AC-Leistungsgrenze / `max_ac_kw` | AC-Ausgangsgrenze in kW; UI-Vorgabe 5. Nicht kWp der Module verwenden |
| Wirkungsgrad / `efficiency` | Nur AC; Standard 0,96 = 96 % |
| DC-Ausgangsgrenze / `max_output_kw` | Nur DC im UI; nominelle DC-Grenze in kW, Vorgabe 5. Kein Modell wechselnder strom-/spannungsabhängiger Hardwaregrenzen |
| DC-Zusatzverlust / `dc_loss_fraction` | Nur DC; Standard 0. Zusätzlich zu Stringverlusten, etwa 0,02 = 2 % |
| PV-Leistung / `power_entity_id` | Optionaler Leistungssensor derselben Ausgangsstufe; W, kW oder MW |
| Kumulativer Ertrag / `energy_entity_id` | Optionaler Energiezähler derselben Stufe; Wh, kWh oder MWh. Echte fortschreitende Originalberichte erforderlich |
| Messquelle gültig / `measurement_valid_entity_id` | Optionaler Binary-Sensor: nur `on` erlaubt neue Messungen; Ausfall/Unbekannt sperrt Energie und Power-Nowcast |
| Abregelung aktiv / `curtailed_entity_id` | Optionaler Binary-Sensor oder Input-Boolean: `on` bedeutet Abregelung. Aktive/unbekannte/wiederhergestellte Abregelung sperrt betroffene Lern-/Powerbeobachtungen |
| Weiteren hinzufügen / `add_another` | Nach den vorhandenen Stufen eine weitere bearbeiten |
| Entfernen / `remove` | Diese Stufe entfernen; mindestens eine muss erhalten bleiben |

DC verwendet keinen AC-Wirkungsgrad. Messgültigkeit und Abregelung haben verschiedene
Bedeutungen und dürfen an derselben Stufe nicht denselben Sensor verwenden. Ohne
Abregelungssignal wird ungedrosselter Betrieb angenommen; die Quellen müssen trotzdem
geeignet sein. Ein voller Akku allein belegt keine Abregelung. Details zur
Wiederfreigabe: [Messgültigkeit](measurement-validity.md).

## 4. Schritt PV-String und spätere Änderungen

| Feld / JSON-Name | Bedeutung und Standard |
| --- | --- |
| Stabile Kennung / `id` | Eindeutiger Stringname, etwa `string_1` |
| Ausgangsstufe / `inverter_id` | Der tatsächlich angeschlossene Wechselrichter/Laderegler; jede Stufe braucht mindestens einen String |
| Modulnennleistung / `peak_kw` | Summe der Modul-STC-Leistungen in kWp, UI-Vorgabe 5 |
| Neigung / `tilt_deg` | UI 0–90°; 0° waagerecht, 90° senkrecht; Vorgabe 30° |
| Azimut / `azimuth_deg` | 0° Nord, 90° Ost, 180° Süd, 270° West; Vorgabe 180° |
| Systemverlust / `loss_fraction` | Standard 0,14 = 14 %; nicht `14` eingeben |
| Temperaturkoeffizient / `temperature_coefficient` | Standard −0,004 pro °C = −0,4 %/°C; Modulblattwert durch 100 teilen, wenn er in %/°C angegeben ist |
| Morgen-/Abenddämpfung / `damping_morning`, `damping_evening` | Je 0–1, Standard 0 = aus; 1 bedeutet volle Randdämpfung bei Auf-/Untergang, keine ganztägige Abschaltung |
| Horizontpunkte / `horizon` | Liste, standardmäßig leer. Je Punkt `azimuth_deg`, `elevation_deg` und optional `beam_transmission` (Standard 0 = kein Direktlicht unter dem Horizont) |
| Weiteren hinzufügen / `add_another` | Einen weiteren String nach vorhandenen Einträgen bearbeiten |
| Entfernen / `remove` | Diesen String entfernen; jede verbleibende Stufe braucht weiterhin einen String |

Horizontazimute müssen eindeutig sein und werden zyklisch interpoliert. Diffuslicht
bleibt erhalten; das Modell simuliert weder Bypassdioden noch elektrische Einzelmodul-
Verschattung. Dämpfung verläuft linear zwischen Sonnenaufgang, Tageslichtmitte und
Sonnenuntergang, vor der gemeinsamen Stufenbegrenzung. Ohne definiertes Auf-/Untergangspaar
bleibt sie neutral. Übernommene Werte anderer Integrationen sind zunächst Annahmen.

Horizontprofil, Morgen-/Abenddämpfung und die gelernte Direktstrahl-Tabelle
([Direktstrahl-Verschattung](adaptive-solar-verschattung.md)) haben getrennte Aufgaben:

- **Horizontpunkte (`horizon`)** beschreiben nur eine ferne Vollfeld-Silhouette, die den
  gesamten String unterhalb der angegebenen Sonnenhöhe gleichmäßig betrifft. Nahe
  Dachkanten, Bäume oder Wandvorsprünge mit starker Parallaxe und Teilverschattung großer
  Modulflächen gehören nicht in `horizon`, weil ein Horizontpunkt für alle Teilflächen
  gilt und den Direktanteil vor dem Tabellenlernen abschneiden würde.
- **Morgen-/Abenddämpfung (`damping_morning`, `damping_evening`)** ist eine pauschale
  lineare Randabsenkung der Stringleistung über die Tageshälfte. Dieselbe Schattenkante
  darf nicht zusätzlich als Dämpfung eingetragen werden; für Flächen mit gelernter
  Direktstrahl-Verschattung bleiben `damping_morning` und `damping_evening` auf `0`.
- **Gelernte Direktstrahl-Tabelle (`beam_shade_v1`)** lernt je Ausgangsstufe in einem
  `10°`-Azimut- × `5°`-Höhenraster aus gebundener Globalstrahlung (`irradiance_entity_id`)
  und gemeinsamer Stufenleistung (`power_entity_id`) an klaren, ungedrosselten Stunden
  (`Clearness-Index >= 0,6`, Sonnenhöhe `>= 10°`, Haurwitz-Klarhimmel `>= 50 W/m²`,
  Paarung innerhalb von fünf Minuten, ausreichender Direktanteil, unterhalb 98 % der
  Stufengrenze) den wirksamen Direktstrahl-Faktor `t` in `[0, 1]`. Ab fünf verschiedenen
  UTC-Viertelstunden je Fenster wird der Median freigegeben; leere oder noch nicht
  freigegebene Fenster bleiben bei Faktor `1` ohne Nachbarschaftsfüllung. Der Faktor
  skaliert nur `poa_direct` nach einem etwaigen fernen Horizont und lässt Diffuslicht
  an bedeckten Tagen unverändert.

Teilen zwei unterschiedlich ausgerichtete Flächen (etwa Hauswand und Schuppen) denselben
Wechselrichter/MPPT und Zähler, werden sie als **zwei Strings derselben Ausgangsstufe**
mit jeweils eigener Neigung, eigenem Azimut und eigener kWp konfiguriert (`horizon` für
nahe Hindernisse leer, `damping_morning=0`, `damping_evening=0`). Der gelernte Faktor
gilt gemeinsam für die gesamte Stufe; getrennte Einzelprognosen je Teilfläche entstehen
ohne eigene Messpunkte nicht. Ein gemessener Prognosevorteil gegenüber unverschatteter
Physik oder Referenzintegrationen wird durch die bloße Einrichtung nicht behauptet.

Über **Konfigurieren/Optionen** werden Standort, bestehende Stufen und Strings
nacheinander bearbeitet. Der letzte abgeschlossene Stringdialog speichert und lädt
den Eintrag neu. Den Flow bei einer bloßen Inspektion abbrechen. Physische Änderungen
(wie geänderte kWp, Ausrichtung, Neigung, Horizont, Dämpfung oder ein zusätzlicher
String) ändern den `history_fingerprint` und setzen den Primary-Store einschließlich
der gelernten Direktstrahl-Tabelle `beam_shade_v1` nach erfolgreichem Setup zurück.
Seit 0.2.14 bleiben bereits ausgegebene vergangene/heutige Tagesstartprognosen
bei gleicher Anlagenidentität mit ursprünglicher Konfigurationsprovenienz erhalten;
zukünftige Altstände und inkompatible Lernmessungen werden nicht übernommen.
[Grenzen und gezielter Originalimport](forecast-repairs.md).
Reine Wetter-/Beobachtungs- oder Featurevertragswechsel erhalten unabhängig gültige
Istintervalle und Tages-Snapshots. Für die Schattentabelle gilt zusätzlich der
`shade_fingerprint`: Ein Wechsel der Wettermodelle oder der Leistungs-, GHI-,
Temperatur- oder Windbindung setzt sie zurück. Ein reiner Wechsel von
`forecast_days` erhält sie. Der Featurevertragswechsel auf `beam-shade-table-v1`
verwirft alte Forecastfeatures, erhält aber eine separat kompatible Schattentabelle.
Details stehen im [Persistenzvertrag](implementation-contract.md).

## 5. Sensoren und Lernstatus

Die konkrete Entity-ID vergibt HA aus Sprache, Namen und Registryzustand. Daher die
Sensoren im Gerätebereich auswählen, keine feste Beispiel-ID übernehmen.

| Sensor | Einheit / Semantik |
| --- | --- |
| Prognoseleistung | W; Mittel des aktuell gültigen Forecastintervalls, keine Messung der Momentanleistung |
| Prognose Resttag | kWh ab jetzt bis lokaler Mitternacht, einschließlich verbleibender Teilstunde |
| Prognose Tag 0 | kWh des ganzen heutigen Tages aus einem tatsächlich vor Tagesbeginn eingefrorenen Snapshot; am ersten Einrichtungstag oft nicht verfügbar |
| Prognose Tag 1 bis Tag 6 | Aktuell prognostizierte kWh der vollständigen jeweiligen lokalen Folgetage; außerhalb des eingestellten/gelieferten Horizonts nicht verfügbar |
| Prognosedatenstatus | Diagnose mit den unten beschriebenen Zuständen und zusätzlichen Attributen |

Je Stufe werden zehn Sensoren angelegt, auch wenn kürzere Horizonte manche Tageswerte
nicht liefern. Mehrere Stufen erhalten zusätzlich die Gesamtsicht. Bestehende
Gesamtsensoren einer Einzelstufe bleiben als ausgeblendete Aliase erhalten.

| Status | Aussage |
| --- | --- |
| `curtailed` | Aktuelle Abregelung aktiv; Prognose bleibt verfügbares PV-Potenzial |
| `partial` | Verbleibender heutiger Tag unvollständig abgedeckt |
| `degraded` | Konfigurierte aktuelle Eingänge/Abregelungsinformation eingeschränkt |
| `physics` | Physikalisches Rückfallmodell |
| `mixed` | Residualkorrektur nur teilweise im veröffentlichten Horizont angewandt |
| `complete` | Resttag abgedeckt und Residualkorrektur horizonweit ohne relevanten Tagesfallback angewandt |

Diese Zustände sind keine Genauigkeitsklassen. Die Priorität entspricht der
Tabellenreihenfolge bis `physics`/`mixed`/`complete`; `learning_horizon` beschreibt
den Ausgabeverlauf, `coverage` den Resttag. Der Statussensor enthält außerdem
`forecast` mit Intervallstart/-ende, `power_w`, `energy_kwh` und optionalen Grenzen.
`energy_kwh` ist bereits Intervallenergie und wird nicht nochmals integriert.

`learning.<Stufe>.training_quality` erklärt Zähler- und Alignment-Ablehnungen.
`learning.<Stufe>.beam_shade` zeigt für die Direktstrahl-Schattentabelle das aktuelle
Sonnenfenster (`azimuth_bin_deg`, `elevation_bin_deg`), den wirksamen Faktor
(`transmittance`, ohne Freigabe `1.0`), die gespeicherten Viertelstunden dieses Fensters
(`samples`), die Freigabe ab fünf Viertelstunden (`released`), die Gesamtzahl
freigegebener Fenster der Stufe (`filled_bins`) und den letzten (auch mehrteiligen)
Ablehnungsgrund (`last_rejection`).
Für Lernlabels gelten mindestens 92 % Messabdeckung des ursprünglichen Ziels
und höchstens drei Minuten fehlende Zeit je Rand. Der längste zusammenhängende
gültige Messblock zählt; Lücken werden nicht aufgefüllt.
`training_quality.policy.max_missing_edge_seconds` nennt die absolute Randgrenze.
Kurze auffällige Zählerdifferenzen können bis zu einem echten Folgebericht
innerhalb eines begrenzten 60-Sekunden-Fensters zurückgehalten werden;
`meter.pending_counter_aggregation` und die Ereigniszähler erklären den Zustand.

Die lokale [Ablehnungsdiagnose](ablehnungsdiagnose.md) ergänzt
`training_quality.rejection_details` mit Schema 1: ursprüngliche Zielzeiträume,
bei Trainingszeilen zusätzlich Ausgabezeit und Regime, sowie technische Gründe.
`targets` und `rows` haben getrennte Nenner und dürfen nicht addiert werden.
Je Gruppe höchstens 50 eindeutige Einträge; `total` zählt vollständig,
`truncated` kennzeichnet Begrenzung oder zusammengefasste gleiche Zeilen.
Ungültige Originalzeiten sind `null`, nicht die aktuelle Uhrzeit.
`evaluated_at`, Zielzähler und Detailgruppen bleiben bei Cachehits gemeinsam auf
dem letzten tatsächlich ausgeführten Fit. Aktueller Forecastzeitpunkt und
aktuelle Eingangsanzeigen bedeuten daher keine erneute Historienauswertung.
Die Erweiterung ist mit 0.2.13 produktiv installiert; gebundene Nachweise stehen im Prüfstand.

Standardmäßig sind für den Residuallerner mindestens 28 qualifizierte Zieltage und 240 Stunden eindeutiger
Messdauer nötig; getrennte chronologische Train-/Prüf-/Kalibrierblöcke und Lead-Gates
kommen hinzu. 28 vergangene Kalendertage allein aktivieren kein Modell. Fehlende,
abgeregelte oder unzureichend abgedeckte Intervalle zählen nicht als gute Labels.
Ohne passende Historie ist Physik der vorgesehene Zustand.

## 6. Native Energy-Anbindung

Im Energy-Dashboard die Einstellungen der passenden **Solarproduktion** öffnen und
bei der Prognoseauswahl den betreffenden Adaptive-Solar-Eintrag auswählen. Der
Erzeugungszähler bleibt der tatsächliche Energiezähler; Forecastsensoren sind keine
`total_increasing`-Zähler und gehören nicht an dessen Stelle. Allgemeine Schritte:
[HA-Solarintegration](https://www.home-assistant.io/docs/energy/solar-panels/).

Ein Entryforecast umfasst alle seine Ausgangsstufen. Homogene AC- oder DC-Einträge
liefern native Stunden-Wh, sofern alle Stufen die ganze UTC-Stunde abdecken. Die
laufende Teilstunde fehlt dort absichtlich. Nicht denselben Gesamtforecast mehrfach
einzelnen Teilanlagen zuordnen. Gemischte AC/DC-Einträge haben keine native
Gesamtprognose einer einzigen Messgrenze; Stufensensoren bleiben nutzbar.

Für Benchmarking gibt es die lesende Antwortaktion
`adaptive_solar.get_reference_forecasts` mit einer expliziten Liste
`config_entry_ids` geladener Helios-/Open-Meteo-Referenzeinträge (höchstens 16).
Sie ändert weder Wetterstände noch Energy-Einstellungen. Das ist keine notwendige
Einrichtungsaktion; Beispiele stehen im [Aufnahmeleitfaden](benchmark-aufnahme.md).

## 7. Fehlerbehebung und Support

| Beobachtung | Prüfen / nächster Schritt |
| --- | --- |
| Integration fehlt nach Installation | Richtiger Komponentenordner, vollständige Dateien, Neustart und Protokoll; keine alte zweite Komponentenkopie im Loaderpfad |
| Fehler beim Installieren/Importieren von `sklearn` | Core-ABI, Architektur, Musl/glibc und vollständige `.libs`/`.dist-info` mit [HAOS-Anleitung](haos-installation.md) vergleichen |
| Setup wiederholt sich / kein Wetter | Internet/DNS, Providerfehler, gültige Modellkennung und API-Bedingungen prüfen; keine Nullkurven erfinden |
| Tag 0 fehlt | Ohne vor Mitternacht ausgegebenen vollständigen Snapshot erwartbar; bereits verlorene Originalwerte können Administratoren mit Originalkonfiguration gezielt [wiederherstellen](forecast-repairs.md#3-bereits-verlorenen-originalwert-gezielt-wiederherstellen) |
| Ferne Tage fehlen | Eingestellter Horizont und tatsächliche Providerabdeckung; zusätzliche Modelle verlängern fehlende Daten nicht automatisch |
| `physics` bleibt bestehen | `learning` und `training_quality` lesen: fehlende Energiebinding, kalte Historie, zu kurze/teilweise Ziele oder nicht bestandene Validierung unterscheiden |
| `degraded` | `inputs` prüfen: Einheit, echte Berichtzeit, `restored`, GHI-Frische, Messgültigkeit und Abregelung |
| Keine neuen Energieintervalle | Originalzählerberichte, Reset/Lücken und Wiederfreigabe prüfen; `update_entity` am gehaltenen Integral ist kein Ersatz für neue Quellenberichte |
| Doppelte alte Gesamtanzeigen | Unter 0.2.10 mögliche Kompatibilitätsaliase; IDs/Verbraucher erhalten, Ausblendung prüfen |

Fehler unter [GitHub Issues](https://github.com/togo42/Adaptive-Solar/issues) melden:
Integrations-/Core-/Pythonversion, Architektur, Installationsweg, erwartetes und
beobachtetes Verhalten, Zeitpunkt mit Zeitzone und einen bereinigten Logausschnitt
angeben. Bei API-/Sensorproblemen die Einheit und das Alter angeben; persönliche
Koordinaten, Tokens, komplette Konfigurationen und rohe Historien nicht veröffentlichen.
Diagnose vor dem Hochladen gemäß [Datenschutz](datenschutz.md) prüfen. Ein kleiner
reproduzierbarer Fall ist hilfreicher als ein vollständiges privates Backup.

## 8. Optionalen Originaldatenexport einrichten

Dieser Abschnitt gilt für den unveröffentlichten Entwicklungszweig. Das
Referenzrelease 0.2.14 enthält diese Erweiterung noch nicht. Die Prognose kann
weiterhin ohne Archivhost und ohne Exportpuffer betrieben werden.

Im Standortdialog der Einrichtung oder unter **Konfigurieren/Optionen** lässt sich
**Originaleingaben archivieren (privater Exportpuffer)** (`archive_export`)
einschalten. Erst der vollständig abgeschlossene Optionsflow speichert die Wahl
und lädt den Eintrag neu. Die Option ist standardmäßig aus; das Update allein
aktiviert sie nicht. Sie gehört weder zu `SiteConfig` noch zu den physikalischen
Historienhashes und setzt für sich keine Lernhistorie zurück.

Der Puffer erfasst ursprüngliche Wetterantworten und deren Empfangs-/
Normalisierungsbelege, sämtliche ausgegebenen Forecastzellen einschließlich Nacht
und Teilstunden, verwendete Beobachtungen, Anlagenkonfiguration, Softwarestand,
Schattenzustand und die tatsächlich verwendeten Fitzeilen mit Fitstichtag.
Originale Zähler-, Gültigkeits- und Abregelungsberichte bleiben von abgeleiteten
Messintervallen getrennt. Das sind private Daten; für Support keine vollständige
Exportantwort veröffentlichen. [Datenschutz](datenschutz.md).

Administratoren lesen den Puffer mit der Antwortaktion
`adaptive_solar.export_archive`. `config_entry_id` wählt genau einen geladenen
Adaptive-Solar-Eintrag. Optional sind `cursor`, `generation`, `limit`
(Standard 100, höchstens 1.000) und `max_bytes` (Standard 2 MiB, höchstens 4 MiB).
Die Antwort enthält `page` und einen getrennten `status`; bei ausgeschaltetem
Export ist `page=null` und der Status `disabled`. Der Abruf löst weder Wetter-
noch Prognoseneuberechnung aus und bestätigt oder löscht keine Ereignisse.
Der Collector speichert die Seite zuerst dauerhaft und benutzt erst danach
ihren `next_cursor`. [Archivbetrieb](archivbetrieb.md) und
[Seiten-/Cursorvertrag](archive-storage-contract.md).

Der neustartfeste HA-Puffer ist vom Lernstore getrennt: höchstens 72 Stunden,
zusätzlich 64 MiB serialisierte Ereignisse und 10.000 Ereignisse. Große Lernstände
und mehrere Stufen können den verfügbaren Zeitraum deutlich verkürzen. Die
Warteschlange hat zusätzlich 64 Ereignisse und 8 MiB einschließlich laufender
Schreibarbeit als Grenze. Große Originale werden in geprüfte komprimierte
Chunks aufgeteilt. Diese Grenzen versprechen keine 72 Stunden Vollständigkeit;
Dateigröße und temporäres Schreibbudget stehen im
[Speichervertrag](archive-storage-contract.md#datenvertrag-und-grenzen).

`archive_export` in der Diagnose und den Attributen des Prognosedatenstatus zeigt
Aktivierung, Puffer-/Warteschlangengröße, Verdrängungszähler und letzten Fehlertyp.
`gap` kann Pufferverdrängung oder lokale Aufnahmeverluste anzeigen; ein
Cursorbruch wird zusätzlich als `page.gap` mit Sequenzbereich geliefert. Ob ein
rechtzeitig abholender Collector Daten verloren hat, muss anhand seines Cursors
und der Originalabhängigkeiten geprüft werden. `error` verlangt eine Prüfung des
Archivs. Ein leerer Fehlerwert allein bestätigt keine Vollständigkeit.
Archivfehler werden abgefangen, die Prognoseberechnung bleibt funktionsfähig.
Fehlgeschlagenes Entry-Setup schreibt keinen Exportpuffer.

Ausschalten beendet neue Aufnahmen nach dem Reload. Vorhandene Pufferdateien und
externe Kopien werden dadurch nicht gelöscht. Langzeitaufnahme, 24-monatige
Aufbewahrung, Sicherungen und Wiederherstellungsprobe gehören zum separat
einzurichtenden [Archivbetrieb](archivbetrieb.md). Ein vollständiges technisches
Replay ist noch kein Nachweis eines Prognosevorteils.
