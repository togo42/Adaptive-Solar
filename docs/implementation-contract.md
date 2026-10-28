# Implementierungsvertrag für Adaptive Solar

Stand: 28.10.2026; veröffentlichtes Referenzrelease 0.2.14 einschließlich des [Messdaten-Nachtrags](messintervalle-92-prozent.md). Die ausdrücklich bezeichnete Originaldatenexport-Erweiterung ist im unveröffentlichten Entwicklungszweig vom 28.10.2026 implementiert; Release und produktive Aktivierung sind damit nicht erfolgt. Anwenderfelder und Abläufe: [Bedienung](bedienung.md). Verhaltenstests: `tests/`; Prognosegüte bleibt gesondert nachzuweisen. Thematisch konsolidiert aus dem lokal archivierten Vorgänger `artifacts/releases/0.2.5-context-window-invalid/source/docs/implementation-contract.md`; das Archiv wird nicht veröffentlicht.

Die [Ablehnungsdiagnose](ablehnungsdiagnose.md) erweitert diesen
Stand um `training_quality.rejection_details` (Schema 1). Join-Ziele stammen aus
den bestehenden Outcomes; Learner-Codes aus den tatsächlichen Prüfstellen.
Je Gruppe höchstens 50 eindeutige Einträge, vollständige unveränderte Rohzähler,
Originalzeiten/Regime und zusammengeführte Gründe. Der bereits gezählte spätere
Schattenfilter erscheint als `incompatible_shade_baseline`; andere spätere Filter
und Validierungsgates erzeugen keine Fake-Zeilen. `alignment` und Detailgruppen
bilden ausdrücklich einen gemeinsamen Snapshot des letzten tatsächlichen Fits;
Cachehits behalten dessen Cutoff. Fittrigger und Modelle bleiben unverändert.
Ohne optionalen Originaldatenexport keine Detailpersistenz oder neuen Recorderreihen; bestehende Redaktion bleibt. Bei aktiviertem Export gehört der tatsächliche Fit-Snapshot zum getrennten privaten Replayzustand.

## Ziel und Aufteilung

Native Custom-Integration `adaptive_solar` unter `custom_components/adaptive_solar/`; `core/` bleibt HA-unabhängig. HA-Imports erst in Setup-Funktionen des obersten `__init__.py` erlauben Offline-Werkzeuge. Modellkern Python ab 3.13, geprüfte HA-Ziele 2026.10.2/.3/.4 mit Python 3.14; pvlib/scikit-learn sind explizite Abhängigkeiten. Kein Helios-Quellcode.

Ziel: **verfügbares PV-Potenzial ohne betriebliche Abregelung** an `ac_inverter_output` oder `dc_charge_controller_output`. Alle Sensoren tragen `forecast_scope=available_pv_potential_without_operational_curtailment`; keine Prognose künftiger Reglerbefehle. `baseline_w`, `power_w`, `actual_w` teilen dieselbe W-Messgrenze, der Produktionszähler liefert deren kumulative Energie statt Netzbilanz/Batterieentladung. Ladereglerlimits sind keine AC-Limits. Aktive/unbekannte Abregelung wird ausgewiesen und sperrt Power-Nowcast, keine echte Sonnenmessung.

Hardwareunabhängigkeit ist eine Produktanforderung: keine Pflichtfelder für Hersteller, Modell, Batterie-SoC oder feste Exportgrenze. Gerätespezifische Protokolle können außerhalb des Modellkerns auf generische HA-Leistungs-, Energie- und Abregelungssignale abgebildet werden. Ohne gebundenes Abregelungssignal wird ungedrosselter Betrieb angenommen; eine entsprechende Betreiberangabe ersetzt keine Messquellenprüfung. Bei DC kann begrenzte Energieaufnahme oder Exportkapazität betriebliche Abregelung verursachen, ein voller Akku allein belegt sie nicht. Die normale deklarierte Ausgangsbegrenzung gehört zur Physik, nicht automatisch zum Abregelungsfilter. Keine allgemeine Hardwarevalidierung oder Simulation der Batterie-/Exportsteuerung behauptet.

## Gemeinsame Datenverträge

`core/models.py`: validierte Dataclasses, timezone-aware Zeitwerte nach UTC normalisiert; SI-Einheiten mit Leistung W, Anlagenleistung kWp, Energie kWh und Azimut 0=N/90=O/180=S/270=W.

Konstruktoren und JSON-Felder: [models.py](../custom_components/adaptive_solar/core/models.py). Verbindliche Besonderheiten:

- `HorizonPoint`: `beam_transmission=0.0`, zirkulär interpoliert nur Direktlicht. `StringConfig`: `loss_fraction=0.14`, `temperature_coefficient=-0.004`, `horizon=()`; mehrere Strings teilen eine Stufe.
- `InverterConfig`: alte Positionsargumente bleiben; `output_type="ac"`, `max_output_kw=None`, `dc_loss_fraction=0.0`. Am Ende optional `measurement_valid_entity_id=None`; ungesetzt fehlt das Feld im JSON. Ein gesetzter Binary-Sensor muss `on` sein und darf an derselben Stufe nicht der Abregelungssensor sein. Kanonisch `max_output_kw`/`output_cap_w`, Provenienz `measurement_boundary`/`MEASUREMENT_BOUNDARIES`. AC: `max_ac_kw`-Alias, Effizienz0,96, keine widersprüchlichen Grenzen. DC verlangt `output_type="dc"`/`max_output_kw`, lehnt AC-Alias/-`efficiency` ab.
- `SiteConfig.from_dict/to_dict`: `best_match`, sieben Tage, optionale Sensoren `None`, auch altes GHI-JSON. `MAX_FORECAST_DAYS=7`: ganzzahlig 1–7 einschließlich des heutigen lokalen Tages (maximal Resttag plus sechs Folgetage) in Konstruktor/JSON/UI/maximalen Tagesentitäten; Provider-Quelltage erweitern nicht den Horizont.
- `Observation`: je Signal echte Berichtzeit; GHI kompatibel am Ende. `TrainingSample.features: dict[str,float]`: ausschließlich ausgabezeitlich Bekanntes, `actual_w` echtes Intervallmittel.
- `WeatherForecast.issued_at`: tatsächlicher Empfang, Cache behält ihn; keine erfundene NWP-Vintage. `ForecastResult.issued_at`: Entscheidungszeit. Alle Leads bis Zielmittelpunkt (`midpoint_lead_hours`).
- `ForecastPoint`: frühestens bei Ausgabe; laufende Zelle dort kürzen, Physik/Features/Lead neu am Mittelpunkt. `source_partial_at_issue=1` nicht lernen, Originalwetter behalten. `power_at` ist halboffenes Intervallmittel; `energy_kwh` braucht vollständige Abdeckung/alle Stufen mit UTC-Dauer. Lokale Mitternacht nach UTC übersetzen: echte23/25-Stunden-Tage.

## Schnittstellen der Teilmodule

### Physik und Wetter

`core/physics.py`, `core/engine.py`: `ForecastEngine(config).forecast(forecasts, issued_at, observations=(), learner=None) -> ForecastResult`. Der Learner liefert über `.predict(inverter_id, features, baseline_w, cap_w)` ein Objekt mit `power_w`, `lower_w`, `upper_w`, `status`; fehlendes/abgelehntes ML fällt auf Physik zurück. Mindestfeatures: `baseline_w`, `sun_elevation_deg`, `sun_azimuth_sin`, `sun_azimuth_cos`, `day_of_year_sin`, `day_of_year_cos`, `temperature_c`, `wind_m_s`, `cloud_cover_pct`, `lead_hours`.

Physikkette: GHI/DHI horizontal, DNI normal → pvlib-Sonnenstand → Hay-Davies → Horizontbegrenzung auf `poa_direct` → Stufenfaktor `beam_shade_factor` (Standard `1.0`) auf `poa_direct` → Summe mit `poa_diffuse` → Faiman-Modultemperatur aus Temperatur/Wind → PVWatts-DC (25 °C Referenz) → String-`loss_fraction` → optionale String-Morgen-/Abenddämpfung → Stringsumme je Stufe. Danach AC-Effizienz/gemeinsamer AC-Clip oder nur konfigurierter DC-Stufenverlust/gemeinsamer Ausgangsclip, ohne versteckte AC-Effizienz. Auch ML/Nowcast begrenzen; Physik, Ist-Plausibilität/Restore teilen dieselbe `output_cap_w`.

`core/shading.py` (`BeamShadeTable`) verwaltet je Ausgangsstufe ein `10°`-Azimut- × `5°`-Höhenraster über der scheinbaren Sonnenhöhe (`[0, 360)` × `[0, 90)`). Jedes Fenster speichert höchstens die letzten 24 UTC-Viertelstunden mit Faktoren in `[0, 1]`; dieselbe UTC-Viertelstunde ersetzt den älteren Wert. Ab fünf verschiedenen gespeicherten UTC-Viertelstunden gibt das Fenster den Median frei, darunter und in leeren Fenstern gilt Faktor `1.0` ohne Nachbarschaftsinterpolation. `inverter_power` übergibt denselben Stufenfaktor an alle Strings der Stufe. `ForecastEngine` liest den Faktor für Stunden- und Teilintervalle am Sonnenstand des eigenen Intervallmittelpunkts und für die Nowcast-Momentanreferenz am Sonnenstand des Leistungszeitpunkts. Aufnahmen entstehen im Coordinator nur, wenn Sonnenhöhe `>= 10°` und Haurwitz-Klarhimmel `>= 50 W/m²`, Clearness-Index `GHI / Haurwitz >= 0,6`, Leistungs- und GHI-Bericht frisch (GHI `<= 5 min`, Leistung `<= 15 min`, nicht `restored`) und höchstens fünf Minuten auseinander, Messung gültig und nicht abgeregelt, unverschattete Momentanreferenz `(P0, P1)` auf der gültigen Stufenkohorte verfügbar (`P0` mit `beam_shade_factor=0`, `P1` mit `beam_shade_factor=1`), Direktanteil `P1 - P0 >= 0,4 * P1` und `>= max(30 W, 0,03 * output_cap_w)` sowie weder `P_messung` noch `P1` bei `>= 98 %` von `output_cap_w` liegen (`t = clip((P_messung - P0) / (P1 - P0), 0, 1)`). Detailvorgabe: [Direktstrahl-Verschattung](adaptive-solar-verschattung.md); ein gemessener Prognosevorteil wird damit nicht behauptet.

`damping_morning`/`damping_evening` sind unabhängige Stringfaktoren von 0 bis 1, standardmäßig 0. Der Leistungsfaktor steigt linear von `1−damping_morning` bei Sonnenaufgang auf 1 in der Tageslichtmitte und fällt bis Sonnenuntergang auf `1−damping_evening`. SPA-Auf-/Untergänge werden geometrisch je Standort berechnet, mit UTC-Dauern auch an Zeitumstellungstagen. Ohne definierten Auf-/Untergang, etwa am Polartag, bleibt die Dämpfung neutral. Die Anwendung folgt dem Stundenmittelpunkt beziehungsweise dem Momentanreferenzzeitpunkt, nach Temperaturrechnung und vor dem gemeinsamen Clip. Es werden keine gemessenen Substundenverluste behauptet. Nullwerte fehlen im kanonischen JSON, damit unveränderte Altanlagen ihre Fingerprints behalten. Aktive Korrekturen ändern die Modellkonfiguration und deren Historienbindung.

Grenzen: Mittelpunkt-Sonnenstand ist keine hochaufgelöste Energiequadratur, Faiman keine vermessene Modulkalibrierung. Nomineller DC-Deckel ist ein Forecastparameter; Stromlimit und wechselnde DC-Spannung können andere Momentangrenzen ergeben. Das zyklisch linear interpolierte Horizontprofil simuliert weder Diffus-Himmelsabschirmung noch elektrische Bypass-/Stringeffekte. Standortverbesserungen sind zu messen.

Wetteradapter: ungültige/unvollständige Pflichtwerte bleiben Lücken. Die einzige numerische Nachtkorrektur normalisiert GHI/DNI/DHI gemeinsam aus [-1,0] W/m² zu 0, wenn mindestens einer negativ und die gesamte Stunde am Standort an 13 Fünfminutenstützen unter −6° Sonnenhöhe liegt. Ohne Standort, bei positiven Anteilen, Dämmerung, größeren Fehlern oder fehlenden/nichtendlichen Werten bleibt die Lücke. Rohwerte, Zeiten und Zähler stehen begrenzt in `weather_diagnostics`; Parser und SPA laufen beim Wetterabruf im Thread. [Vertrag](forecast-repairs.md). Open-Meteo-Strahlung am API-Zeitpunkt `t` gehört zu `[t-1h,t)`; Temperatur/Wind/Bewölkung sind Momentanwerte bei `t`. Zwei einzeln gültige, genau stündlich benachbarte Endpunkte ergeben eine lineare Mittelpunktnäherung, kein gemessenes Stundenmittel ([Zeitdefinition](https://open-meteo.com/en/docs#hourly-parameter-definition)). Fehlende Stützen werden nicht interpoliert. Cropping/Instant-Geometrieproxy behalten konstante Quellbedingungen; neue Grenzen erzeugen keine gemessene Substundenmeteo.

Unterschiedliche Raster werden an vorhandenen Grenzen und Ausgabezeit geteilt. Je Intervall zählt nur die verfügbare Modellkohorte, ohne rückwirkende Abdeckung oder erfundene Tage. `best_match` kann andere Arme überlappen: keine behauptete Unabhängigkeit oder kalibrierte Ensemble-Unsicherheit. `PhysicsUnavailable` entfernt nur die betroffene Stufe/Modellzelle, erhält gültige Nachbarstufen und führt deren Kohorten, GHI-Regime und Instantreferenzen getrennt. Ohne gültige Berechnung bleibt eine Lücke; `inverter_id` ermöglicht selektive Stufenrechnung, unerwartete Programmierfehler propagieren.

Im Entwicklungszweig fordert der Wetterclient relative Stunden statt einer auf
UTC-Mitternacht verkürzten Tageszahl an: `forecast_hours=(forecast_days+1)*24+1`
und `past_hours=1`, weiterhin UTC/Unixzeit. Der vorherige Momentanendpunkt dient
der laufenden Quellzelle; ein früher endender nativer Modelllauf wird weder
verlängert noch aufgefüllt. Lokale Tages-/DST-Grenzen bestimmt weiterhin der
Forecastkern. Zusätzliche Providerstützen verlängern nicht `SiteConfig.forecast_days`.

### Lokale Eingaben und Nowcast

Alte/zukünftige Berichte bleiben ungenutzt; Temperatur/Wind werden kurzfristig an NWP angenähert. Opt-in-GHI verlangt höchstens fünf Minuten Alter sowie geeignete Sonnenhöhe/Strahlungsbasis. Haurwitz am echten Beobachtungszeitpunkt und Vierpunkt-Gaussquadratur über das **originale** NWP-Intervall liefern einen Clearness-Abgleich statt naiver Division Momentanwert/Stundenmittel. Ein begrenzter gemeinsamer GHI/DNI/DHI-Faktor erhält die Modellaufteilung; Gewicht mit 30 Minuten Zeitkonstante über maximal 90 Minuten integrieren. Das Ausgabeintervallmittel wirkt bis zum Ende der letzten überlappenden Quellstunde (Stundenraster: weniger als 150 Minuten).

GHI gilt je Stufe atomar für ihre numerisch gültige Modellkohorte, sonst bleibt die gesamte Zelle NWP. Baseline, Gain, Regime und Instantreferenz müssen dieselbe Stufenkohorte beschreiben. Betroffene Zellen veröffentlichen keine für einen anderen Datenstand kalibrierten ML-Grenzen. Entfernte Grenzen ändern auch den punktuellen Kalibrierungsstatus; die Statusunion entsteht erst nach allen Korrekturen.

Der Leistungs-Nowcast addiert eine kurze abklingende Restleistungskorrektur nur bei aktueller plausibler Produktion ohne Abregelung. Bei gebundenem Signal muss der echte Powerbericht **strikt nach Beginn des aktuellen klaren Zustands** liegen; ein älterer bleibt bis zu einem echten neuen HA-Bericht gesperrt. Seine Messzeit wird nie ersetzt. Wiederhergestellte Steuersignale gelten auch bei `off` als unbekannt. Bei Entfernung des `restored`-Attributs begrenzt zusätzlich `last_updated` die neue Freigabephase; `last_changed` allein reicht dafür nicht.

Momentanreferenz: Original-NWP-Strahlungsmittel mit [Ineichen-Klarhimmelform](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.ineichen.html)/Achtpunkt-Gaussquadratur normalisieren, String-/Stufenphysik am echten Power-Messzeitpunkt rechnen. Das ist eine Wolkenpersistenz-Approximation, keine gemessene Feinauflösung/neues Ausgaberaster. Frische Vorstundenproben bleiben nutzbar; fehlende Quellintervalle/Kohorten werden nicht verlängert. Gleichzeitige GHI gegen **dieselbe Momentanapproximation**, nicht den gedämpften zukünftigen Zellgain abgleichen, um Wetterfehler nicht doppelt zu korrigieren. Nichtvergleichbarer Physik-/ML-Status oder unterschiedliche belegte Lernunterstützung sperren die Zusatzkorrektur; unplausible Referenzen liefern kein Residual. Beide Korrekturintegrale durch echte Ausgabezelllänge teilen: zehn Restminuten sind keine Stunde.

### Lernen und Archiv

`core/learning.py`: `ResidualLearner().fit(samples, as_of)`, `.predict(...)` wie oben, Diagnose `.status`. Je Stufe getrennte NWP-/GHI-Baselinemodelle. Zusatzfeatures: `ghi_regime` 0/1, `ghi_nowcast_gain` (NWP 1), `ghi_observation_age_seconds` (NWP 0). Im Kern sind markerfreie Zeilen NWP, unvollständige alte GHI-Marker ungültig. Sensorausfall erlaubt kein GHI-Modell auf roher NWP-Baseline.

Je Regime eigene chronologische Trainings-/Validierungs-/Kalibrierungs-Zieltage nach lokalem Intervallstart, auch über Mitternacht bei Teilstundenoffsets. Ganze frühere Zielzeilen mit `end > nächster Blockstart` werden an beiden Grenzen entfernt; Gleichheit ist zulässig. Historientage/-stunden danach erneut prüfen, Messenergie nie teilen. `purged_boundary_overlap_rows` nennt entfernte Zeilen. Je Regime: Future-Labels, Nacht, Abregelung, ungültige Daten/Duplikatgewichtung ausschließen. Aktivierung, LeadRange/Kalibrierung nicht aus dem anderen Regime leihen. Solar-Geometrie/Saison erlauben wiederkehrende Verschattung; Stufenzähler identifizieren keine Einzelstrings. Modelle aus Zeilen rekonstruieren, keine Pickles.

Standard: mindestens 28 Zieltage/240 Stunden vereinigter Messdauer, keine vollen Stunden aus Kurzfragmenten. Je aktivem Lead-Bin eigene ausreichende Trainings-/Validierungstage/-stunden, strikt mehr als 5 % MAE-Verbesserung gegen Physik und 60 % gewonnene Validierungstage. Unterstützter Lead: Schnittmenge der Trainings-/Validierungsbereiche; unbelegt/abgelehnt bedeutet Physik. Fehlergrenzen brauchen eigene Kalibrierungstage/-stunden im Bin, keine zertifizierten P10/P90.

`training_quality.alignment.rejection_reasons` trennt `issued_after_target_start`, `target_shorter_than_minimum`, `source_partial_at_issue` und `stale_beam_shade_baseline` (wenn der zur Ausgabezeit archivierte `beam_shade_factor` eines Sonnenstandsfensters einer inkompatiblen Baselinephase angehört, d. h. Wechsel zwischen unverschattet `1,0` und verschattet `< 1,0` oder Abweichung über `SHADE_BASELINE_TOLERANCE = 0,10` gegenüber dem aktuellen Tabellenfaktor; ohne kompatible Trainings- und Validierungsstützung fällt sowohl die Holdout-Bewertung/Kalibrierung als auch `predict` für verschattete Baselines auf `physics_unvalidated_shade_baseline` zurück); mehrere Gründe können dieselbe Zielzelle betreffen. Die unveränderte Mindestdauer von 30 Minuten ist eine Historienanforderung, kein Leakage-Nachweis für kürzere, ansonsten prospektive Wetterzellen.

HA verbindet vor Zielbeginn bekannte Features erst nach Intervallende mit echten Zählerdifferenzen. Positive Tages-Baselines ohne `source_partial_at_issue` je Zielzelle/Lead-Bin/Regime getrennt archivieren; Tagesenergie-Snapshots bleiben unabhängig. Mitte heißt Origin am nächsten zur festen Binmitte:

| Stufenzahl | NWP-Origins je Bin/Zelle | Zusätzliche GHI-Origins |
| --- | --- | --- |
| 1–3 | Tatsächlich kleinster/größter Lead und Mitte | Beide Ränder |
| 4–6 | Beide Ränder | Beide Ränder |
| Ab 7 | Mitte | Nahe 1,5 h im ersten Bin, sonst Binmitte |

Regime verdrängen einander nicht; Gesamtzeilengrenzen gelten weiterhin. Mehrere Origins/Regime erzeugen keine zusätzlichen Iststunden. Zeitdauergewichte und Entdoppelung begrenzen häufige Mess-/Ausgabeereignisse. Im flachen Lernbericht stammen Zustand, MAE, Gewinnquote und Lead-Bins nur aus `primary_regime`: aktives NWP vor aktivem GHI. `active_regimes` und vollständige `regimes` bleiben getrennt; Gesamt-Historienzähler tragen `history_scope=deduplicated_all_regimes` und sind keine Primärregime-Trainingsmenge.

### Messintervalle und Persistenz

`join_training(as_of=...)` schließt Labels mit späterem `observed_at` vor Samplebau und Duplikaterkennung aus; Gleichheit ist zulässig. Der Lerner prüft die As-of-Grenze zusätzlich.

Anker nur bei strikt steigender Messzeit; ältere/doppelte Events im gewöhnlichen Counterpfad ändern weder Anker noch Sperren. Negativer Vorwärtsdelta: Resetanker ohne Label. Keine Brücken über Lücken, unplausible Leistung/Abregelung. Gefilterte HA-Reports können unveränderte/Null-Stände als Empfangsgrenzen liefern, Polling gehaltener Werte nicht. HA-Empfang zertifiziert keine Quellenqualität. Ohne Abregelungssensor: optionale Unconstrained-Annahme statt bewiesener Freiheit; Messquelleneignung separat prüfen.

Ein zunächst unplausibles kleines positives Zählerdelta kann bis zu einem echten Folgebericht innerhalb von 60 Sekunden zurückgehalten werden. Energiegrenze: höchstens die bei Stufengrenze plus 10 % in 60 Sekunden mögliche Energie. Erst eine plausible ganze Differenz ergibt ein Label mit ursprünglichem Anker und echter Endbericht-/Empfangszeit. Keine Energieclips oder Änderung bereits angenommener Intervalle; große Sprünge, anhaltende Überleistung, Timeout, Reset und ungültige/abgeregelte Phasen bleiben gesperrt. Resetprüfung nutzt auch den neuesten zurückgehaltenen Originalwert. `pending_counter_aggregation`, `deferred_power_check`, `accepted_deferred_delta` und `counter_aggregation_timeout` erklären diesen flüchtigen Zustand; er wird nicht persistiert.

Mit optionaler [Messgültigkeitsquelle](measurement-validity.md) sperren `off`, unbekannt/unverfügbar, fehlend und restauriertes `on` Energie- und Powerdaten. Der erste Originalbericht streng nach Monitoringstart/Wiederfreigabe ankert nur; frühere gültige Intervalle bleiben. Ein verspäteter Bericht vor dieser neuen Grenze kann konservativ auch einen inzwischen neuen Anker verwerfen; daraus entsteht eine Lücke, kein rückwirkend gültiges Label. Original-Nullberichte bleiben erhalten, Umweltbeobachtungen und PV-Potenzial werden nicht gesperrt. Wiederholtes gültiges `on` setzt die gültige Phase nicht neu. Gültigkeit ist weder Abregelung noch ein physischer Ganzintervallnachweis; zusätzliche Zählerpolls können die Original-Berichtssemantik verletzen.

Angrenzende Messdifferenzen innerhalb einer UTC-Stunde werden exakt zusammengefasst; ganze gültige Stundenübertritte bleiben ungeteilt gespeichert. Der Join schneidet daraus keine unbekannte Randenergie: mindestens halbstündige Zielzelle, **mindestens 92 % Messabdeckung, höchstens 180 Sekunden Verlust an jedem Rand**. Der längste verfügbare zusammenhängende Block wird gewählt, bei gleicher Dauer der frühere; keine Auswahl nach Ertragswert oder Modellfehler. Ein frühes Fragment verdeckt keinen längeren späteren Block. Exakte Messduplikate zählen einmal; widersprüchliche oder überlappende Messungen sperren das Ziel. Bei `as_of` muss auch das ursprüngliche Ziel beendet sein. Istleistung verwendet die reale Messdauer als Nenner. `ResidualLearner` prüft die Grenzen unabhängig; `measurement_edge_fraction` bleibt Samplemetadatum, die Policy nennt nun `max_missing_edge_seconds=180`. `training_quality` nennt Zähler-/Alignment-Ablehnungen je Stufe ohne Origin-Mehrfachzählung.

HA `Store`: höchstens120 Tage,60.000 Forecast-/30.000 Istzeilen; Raster/Stufenzahl können die Dauer verkürzen. Ist-/Tagesenergien:10% Ausgangsgrenzentoleranz, echte UTC-/DST-Dauer, keine Bool-Werte. Zwei feste Keys: neuer `history_v2`-Primary, Legacy ausschließlich lesend. Dessen opaker Vollhash muss zur Migration exakt passen; sonst Original behalten/neuen Primary kalt beginnen. Moderner `history_fingerprint` bindet Physik/Zeitzone/Output/Energie-/Curtailmentquelle und eine gesetzte Messgültigkeitsquelle; ungesetzt bleiben beide bisherigen Fingerprints unverändert. Die Direktstrahl-Schattentabelle liegt im `history_v2`-Primary unter `beam_shade_v1`, geht nicht in `history_fingerprint` ein und zählt nicht gegen die 120-Tage-/Zeilengrenzen von `archive` und `intervals`. Fehlt `beam_shade_v1` oder ist sein Inhalt beschädigt, wird eine leere Tabelle geladen, ohne valide `archive`-, `intervals`- oder `daily_snapshots`-Daten des Primary zu verwerfen. Wetter/Horizontlänge/Temp/Wind/GHI/Power-Bindungswechsel erhalten valide Istintervalle und ausgegebene Tages-Snapshots; `beam_shade_v1` ist an `shade_fingerprint` (Anlagengeometrie, Stufen, Wettermodelle und Leistungs-/GHI-/Umwelt-/Gültigkeits-/Curtailment-Bindungen ohne `forecast_days`) gebunden, sodass ein reiner `forecast_days`-Wechsel `beam_shade_v1` erhält, während Sensor- oder Wettermodellwechsel `beam_shade_v1` zurücksetzen. Forecastfeatures brauchen zusätzlich Vollhash und `learning_feature_contract="beam-shade-table-v1"`; deren Wechsel verwirft nur Lernfeatures/abgeleitete Modelle. Bekannte physische Änderungen (`history_fingerprint`) beginnen den festen Primary einschließlich `beam_shade_v1` neu, **erst nach erfolgreichem Erstrefresh/Plattform-/Service-Setup**. Zuvor kein Delay-/Close-Save; unbekannte/korrupte Primärdaten werden nicht überschrieben. Keine unbegrenzten Hash-Namespaces. AC-JSON/Fingerprint und HA-Store-Version bleiben kompatibel. Seit 0.2.14 bleiben historische Tagesstartwerte als unabhängig gekennzeichnete Originalprognosen im selben Store erhalten: `daily_snapshot_provenance` bindet ursprüngliche Konfigurationshashes, Identität, Zeitzone und Ausgangsgrenzen. Physische Änderungen verwerfen weiterhin Lernhistorie und zukünftige Alt-Snapshots, nicht bereits ausgegebene historische Werte derselben Anlagenidentität. Standort/Zeitzone/Stufenidentität dürfen nicht wechseln; opake Altprovenienz wird nicht geraten. [Details und Administratorimport](forecast-repairs.md).

Modelle beim Erstaufbau oder bei geänderter Fit-Signatur rekonstruieren: Historienrevision, lokaler Tag und vollständig serialisierte Schattentabelle. Auch neue/ersetzte Schattenaufnahmen bei unverändertem Median können einen Refit auslösen; HA serialisiert Updates, offline kein paralleles `fit`/`predict` zugesichert. Tagesbeginnenergie: eigener vollständiger Snapshot vor Mitternacht, nie aus späterem Forecast rückdatieren. Keine Secrets/ausführbaren Modellobjekte persistieren.

### Optionaler Originaldatenexport im Entwicklungszweig

`archive_export` ist eine separate boolesche Config-Entry-/Optionswahl; fehlt sie,
gilt `false`. Der native Standortdialog bietet den Schalter. Sie gehört nicht
zu `SiteConfig`, `history_fingerprint` oder `shade_fingerprint`. Ein bestehender
Eintrag wird durch die Codeaktualisierung nicht aktiviert. Der neue Pfad schreibt
bei ausgeschalteter Option keine Exportdateien und verändert die deterministische
Modellgewichtung nicht.

`archive_export.py` führt einen vom Lernstore getrennten `ArchiveJournal` unter
`<HA-Konfigurationsverzeichnis>/adaptive_solar_archive/<entry_id>/`. Writes beginnen
erst nach erfolgreichem Erstrefresh, Plattform- und Service-Setup; ein
Setupabbruch verwirft bis dahin nur im Speicher vorgemerkte Ereignisse.
Schreibarbeit, Kompression und Quell-/Bibliotheksprovenienz laufen im Executor.
Journal- oder Serialisierungsfehler werden abgefangen und als Exportfehler
ausgewiesen; gültige Forecasts werden weiterhin veröffentlicht.

`weather_response` bindet die tatsächliche ursprüngliche Antwort, Anfrageparameter,
Modell, Empfang, HTTP-/Parserstatus und Normalisierungsbeleg an eine stabile ID.
Ein Cachehit behält deren ID und ursprünglichen Empfang; eine unbekannte
Providerlaufzeit bleibt unbekannt. `forecast_issued` bewahrt alle ausgegebenen
Zellen einschließlich Nacht/Teilstunden, ursprüngliche normalisierte Wetterzellen
und ihre Antwort-IDs, Beobachtungen, vollständige Anlagenkonfiguration, Software-
und Featurevertrag sowie die Einzelmodell-Physikausgaben ohne Beobachtungs- und
Residualkorrektur. `issued_at` ist der Berechnungscutoff; `computed_at` und der
Ereignisempfang werden erst nach der numerischen Berechnung erfasst.

Historienzeilen, Beobachtungen, Schattentabelle, Quellen-IDs und Historienrevision
werden vor der Workerberechnung eingefroren. Der Replayzustand bewahrt die
tatsächlich an den letzten Fit übergebenen `fit_samples`, `fit_as_of`, den
gemeinsamen Diagnosesnapshot und den zur Ausgabe angewandten Schattenzustand.
Ein Cachehit erhält den alten Fitstichtag und dessen Zeilen; aktuelle Meterdaten
werden nicht nachträglich als frühere Fitgrundlage ausgegeben. `source_report`
bewahrt Original-Zähler-/Gültigkeits-/Abregelungsberichte sowie bei aktiviertem
Export alle konfigurierten Leistungs-/GHI-/Temperatur-/Windberichte mit Quell-
und Empfangszeiten. Unveränderte, ungültige, restaurierte und entfernte Zustände
bleiben erhalten; die Attribute sind auf Einheit, State-Class und `restored`
beschränkt. Die deduplizierte Subscriptionmenge ändert keine Zählerverarbeitung
und erzwingt keine Quellenaktualisierung. `qualified_interval` ist ein getrenntes abgeleitetes Messergebnis,
kein unabhängiger Beweis physischer Quellenqualität.

`forecast_issued.shade_learning` (`schema: 1`) ergänzt den Rohzustandssnapshot
aller konfigurierten Quellen, normalisierte Stufeneingaben sowie Entscheidungen
einschließlich abgelehnter Lernversuche, Referenzleistungen, Sonnenstand, Faktor
und versionierter Regelparameter. Der Replayzustand enthält `shading_before`
und den weiterhin unter `shading` gespeicherten angewandten Folgezustand.
`session_id`, `step_sequence`, `step_id` und `previous_step_id` binden jeden
Schritt an seinen Vorgänger; die Nummer wird unabhängig vom Exporterfolg erhöht.
Der erste Zustand ist ausdrücklich `unverified_preexisting_history`, kein
rückwirkender Nachweis früherer Lerndaten.

`core/shade_learning.py` enthält die gemeinsame Schrittfunktion; ihre Standardregel
entspricht dem bisherigen Coordinator. `core/shade_replay.py` prüft eine gewählte
vollständige Sitzung ab Schritt 1, Originalwetter-/Rohquellenbindung, Normalisierung,
Zeitverfügbarkeit, Entscheidungen und Tabellenfortschreibung. Kandidaten besitzen
unabhängige Tabellen und erhalten keine früher auf der alten Schattenbaseline
trainierten Residualmodelle. Der separate Kontroll-Replay vergleicht weiterhin
die tatsächlich ausgegebene Gesamtprognose. Der CLI schreibt schrittweise JSONL
und benötigt einen Datenpin. Alte Exporte ohne Schattenlernvertrag bleiben für
den normalen Prognose-Replay lesbar, nicht für vollständiges Schattenneulernen.
[Ablauf und Grenzen](archivbetrieb.md#51-schattenlernen-chronologisch-vergleichen).

`forecast_state_chunk`, `forecast_payload_chunk` und `weather_payload_chunk`
verbinden große Zustände beziehungsweise vollständige Nutzdaten mit komprimierten
Fragmenten, Gruppen-ID, Indizes und Prüfsumme. Ein kleines Manifest referenziert
die vollständigen Inhalte; es ersetzt sie nicht durch Summen. Vor Replay werden
Vollpayload-, Zustands- und Originalwetterabhängigkeiten einschließlich gleicher
Quelle/Generation, Empfangsgrenze, Inhaltsprüfsummen und deklarierter
Dekompressionsgrenze geprüft. Fehlende Originale bleiben ein Fehler. Identische
Zustände werden nur wiederverwendet, solange ihre Chunks nachweislich noch im
Puffer liegen; bei bereits komprimiertem Vollforecast bleiben dessen eingebettete
Zustandsverweise unverändert und erhalten eigene Chunks.

Die Aufnahme hat insgesamt 64 Ereignisse und 8 MiB Warteschlangenbudget
einschließlich laufender Writes. Ein vollständiges Forecastpaket wird gemeinsam
angenommen oder als Aufnahmeverlust gekennzeichnet. Der Journalwriter bestätigt
Chunks, Nutzdatenmanifeste und vorgemerkte Aufnahmebelege einer Schreibcharge
gemeinsam in einer SQLite-Transaktion einschließlich nötiger Verdrängungen.
Wiederverwendbare Zustandsreferenzen werden erst nach dem Commit vorgemerkt;
ein fehlgeschlagener später Datensatz lässt keine vorherigen Teilereignisse
der Charge zurück. Journalgrenzen sind
72 Stunden, 64 MiB Ereignisbytes und 10.000 Ereignisse; keine garantierte
72-Stunden-Abdeckung. `archive_export` in Diagnostik/Statussensor und
`status` der Exportantwort nennen Größen, Verdrängungszähler und letzte
Fehlertypen. Cursorbrüche und verbleibende Referenzen müssen zusätzlich geprüft
werden. Physische Dateigrenzen und temporärer Platzbedarf stehen im
[Speichervertrag](archive-storage-contract.md).

`adaptive_solar.export_archive` wird als Administratorservice mit
`SupportsResponse.ONLY` registriert: geladene eigene `config_entry_id`, optional
`cursor`/`generation`, 1–1.000 Ereignisse pro Seite, 1 KiB–4 MiB Seitenbudget
(Standard 100/2 MiB). Antwort: `page` und separater `status`; ausgeschaltet
`page=null`. Der native HA-Authentifizierungskontext prüft Administratorrechte.
Die Aktion aktualisiert weder Wetter noch Prognosen und bestätigt oder entfernt
keine Daten. Erfolgreich geladene Einträge teilen die Registrierung; der letzte
Unload entfernt sie. Setupfehler entfernen vorgemerkte Servicebesitzer.

Der externe Collector bestätigt seinen lokalen Cursor erst nach dauerhafter
Originalspeicherung. HA-Puffer, externe Aufnahme, 24-monatige Hostaufbewahrung,
Backups, Replay und Genauigkeitsbewertung bleiben getrennte Nachweise.
[Archivbetrieb](archivbetrieb.md), [Speicher-/Cursorvertrag](archive-storage-contract.md)
und [Datenschutz](datenschutz.md) beschreiben den privaten Betrieb. Keine produktive
Aktivierung, Modelländerung oder Überlegenheit folgt aus den lokalen Tests.

### HA und native Energy

`weather.py`, `coordinator.py`, `config_flow.py`, `sensor.py`, `__init__.py`, `const.py`, `manifest.json`, Strings/Übersetzungen: Anlagen-/String-/Stufen-UI, native Entity-Selektoren, lokale Einheiten-/Zeit-/unavailable-Prüfung. Netzwerk async mit Timeout, Physik/ML im Executor, Wettercache, häufigerer Resttag-Refresh. Keine produktiven Fremdeinstellungen ändern.

Alle Sensorarten lehnen `restored`-Berichte ab: Leistung, GHI, Temperatur, Wind und Energie. Ein aktueller HA-Wiederherstellungszeitstempel belegt keine neue physische Messung. Neue reguläre Berichte können die Beobachtungspfade wieder aktivieren. Featurevertrag `beam-shade-table-v1` (Nachfolger von `atomic-ghi-cohort-centered-weather-v2`) trennt ältere Archivfeatures ohne Direktstrahl-Schattentabelle oder mit restaurierten Eingaben von neuen Baselines; unabhängig validierte Messintervalle, tatsächlich ausgegebene Tagesbeginn-Snapshots und eine gültige `beam_shade_v1`-Tabelle bleiben nach den bestehenden Provenienzprüfungen erhalten. Je Stufe ergänzt `learning.<Stufe>.beam_shade` den Lern- und Diagnosestatus um `azimuth_bin_deg`, `elevation_bin_deg`, `transmittance`, `samples`, `released`, `filled_bins` und überlappende `last_rejection`-Gründe (`low_elevation`, `low_clearness`, `stale_or_unpaired`, `low_beam`, `at_cap`, `curtailed_or_invalid`, `no_reference`, `insufficient_samples`).

AC-JSON behält unverändert Serialisierung/Fingerprint, neue DC-Stufen ändern ihn. Keine Power-/Energy-Bindung für mehrere unabhängige Stufen; gemeinsames Curtailment erlaubt. AC/DC-Typwechsel im Optionsflow verwirft alte Messbindungen. AC-Entity-IDs bleiben kompatibel, DC-/Mixed-Gesamtsensoren nutzen getrennte Historien-Namespaces.

Qualität: `SensorDeviceClass.ENUM`, keine Genauigkeits-/Konfidenzklasse. Priorität: aktive Abregelung → partielle Resttagabdeckung → beeinträchtigte konfigurierte Eingaben/unbekannte Abregelung → Physik, teilweise (`mixed`) oder vollständige Residualanwendung. Tatsächlicher Ausgabestatus gilt horizonweit; inaktives Gegenregime/Nacht-/Nullzellen verdecken aktive Tageskorrekturen nicht. `learning_horizon`: globaler Scope, Rohstatus, NWP-/GHI-Validierungsranges; `coverage_scope`: Resttag. Horizonweite Wetter-/Physikdiagnosen und letzter Abruffehler bleiben Attribute: Zusatzproviderausfall/ferne Lücke degradieren gültige heutige Ausgabe nicht; echte Resttagslücken bleiben `partial`.

Native `wh_hours`: nur vollständige UTC-Stunden **aller** Stufen homogener AC-/DC-Entries; kleinere Zellen nach Dauer integrieren. Angefangene Stunden fehlen, Resttag/Qualitätskurve behalten verbleibende Teilenergie. Keine Minutenkeys als Stunden-Wh/erfundene Vorenergie; DST behält 23/25 UTC-Stunden.

Mixed-Entries behalten Stufensensoren und `mixed_output_generation_sum` verschiedener Messpunkte, ohne AC-Netz-/Batteriefluss oder nativen Gesamtforecast einer Messgrenze. `native_energy_eligible=False` gilt der Entry-Schnittstelle, nicht fehlenden Stufenprognosen. `output_type`, `output_types`, `measurement_boundary`, `measurement_boundaries`, `output_stage_boundaries` bleiben auch ohne Zustände verfügbar. CLI nennt Stufe/nominelle W-Grenze ohne Sensorbindungen/Standort.

## Nachweis

`services.py` liest native Helios-/Open-Meteo-Wh mit Domain-Allowlist/Timeout, ohne Energy-Preferences-Write. `capture_ha.py`/`capture_actuals.py` bewahren Empfang, Rohrevision, Einheiten/Qualitätsprovenienz; spät geprüfte Altstände verdecken keine neuere Invalidierung und erzeugen keine rückdatierten Labels. Ablauf/Formate: [Aufnahmeleitfaden](benchmark-aufnahme.md).

`core/evaluation.py` bewertet archivierte statt neu rekonstruierte Prognosen auf identischen Fenstern/Cutoffs. Gemeinsamer Lead geht vom Cutoff bis Fenstermitte, Issuezeiten wählen nur zulässige Snapshots. Ganze gemessene Istintervalle bleiben ungeschnitten, Prognosemittel zuschneidbar, fehlende Werte niemals Null. `interval_task_identity=[cutoff,inverter_id,start,end]`: Intervallzählung/-energie ist Taskexposition, dauergewichtet, keine unabhängige Stichprobe/einmalige Erzeugung. Schätzer/Gates bleiben unverändert.

Je Stratum/Referenz liefern nur vollständige geplante Origins eines Zieltags mittleren Fehler/eine Stimme; Gesamtquote ist das Minimum. `statistical_validation.py` resampelt alle Strata/Referenzen desselben Tages gemeinsam. Familienkonfidenz, Bonferroni, Seed/Resamples versioniert; keine Ersatzaussage bei fehlenden Strata/gescheitertem deskriptivem Gate. [Vorabkriterien/Reviewaudit](validierung.md) und Testdatenfluss sind keine Feldgüte; fairer prospektiver Vergleich bleibt nötig.


## Abregelungsprüfung und Bestandsdaten ab 0.2.11

Neue Messintervalle mit konfiguriertem Abregelungssignal tragen den Zeilenmarker
`curtailment_measurement_contract=non-restored-control-v1`. Nur echte, nicht
wiederhergestellte `off`-Zustände sind freigegeben. Ein unbekannter/aktiver Zustand
invalidiert den Anker; nach Freigabe liefert erst das zweite Originalzählerereignis
wieder ein Delta. Zeilen mit unterschiedlichem Vertragsmarker werden nicht koalesziert.

Alte Intervalle werden innerhalb der bisherigen Provenienz-/Aufbewahrungsgrenzen
weitergenutzt und nicht nachträglich als geprüft markiert. Der Meterdiagnosezähler
`legacy_curtailment_intervals` weist die technisch nicht belegte alte Kontrollprovenienz
aus. Ihre Nutzung verlangt Betreiberqualifikation; für den aktuellen Bestandsbetrieb
liegt die ausdrückliche Bestätigung keiner Abregelung in den letzten Tagen und der
Wunsch zur Datennutzung vor. Das ist kein Signal- oder physikalischer Nachweis.
Archivbaselines und echte Tagesanfangsprognosen bleiben davon unabhängig erhalten.
