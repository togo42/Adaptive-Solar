# Adaptive Solar einrichten und bedienen

Stand: 26.10.2026, Codebasis 0.2.11. [Installation](installation.md),
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

Über **Konfigurieren/Optionen** werden Standort, bestehende Stufen und Strings
nacheinander bearbeitet. Der letzte abgeschlossene Stringdialog speichert und lädt
den Eintrag neu. Den Flow bei einer bloßen Inspektion abbrechen. Physische Änderungen
und neue Messbindungen können die Lernhistorie zurücksetzen; reine Wetter-/Beobachtungs-
Änderungen erhalten unabhängig gültige Istintervalle nach dem Persistenzvertrag.

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
Standardmäßig sind mindestens 28 qualifizierte Zieltage und 240 Stunden eindeutiger
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
| Tag 0 fehlt | Ohne vor Mitternacht ausgegebenen vollständigen Snapshot erwartbar; Resttag und Folgetage getrennt prüfen |
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
