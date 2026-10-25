# Implementierungsvertrag für Adaptive Solar

Stand: 25.10.2026. Verhaltenstests: `tests/`; Prognosegüte bleibt gesondert nachzuweisen. Thematisch konsolidiert aus dem lokal archivierten Vorgänger `artifacts/releases/0.2.5-context-window-invalid/source/docs/implementation-contract.md`; das Archiv wird nicht veröffentlicht.

## Ziel und Aufteilung

Native Custom-Integration `adaptive_solar` unter `custom_components/adaptive_solar/`; `core/` bleibt HA-unabhängig. HA-Imports erst in Setup-Funktionen des obersten `__init__.py` erlauben Offline-Werkzeuge. Python ab 3.13, HA-Ziele 2026.10.2/.3; pvlib/scikit-learn sind explizite Abhängigkeiten. Kein Helios-Quellcode.

Ziel: **verfügbares PV-Potenzial ohne betriebliche Abregelung** an `ac_inverter_output` oder `dc_charge_controller_output`. Alle Sensoren tragen `forecast_scope=available_pv_potential_without_operational_curtailment`; keine Prognose künftiger Reglerbefehle. `baseline_w`, `power_w`, `actual_w` teilen dieselbe W-Messgrenze, der Produktionszähler liefert deren kumulative Energie statt Netzbilanz/Batterieentladung. Ladereglerlimits sind keine AC-Limits. Aktive/unbekannte Abregelung wird ausgewiesen und sperrt Power-Nowcast, keine echte Sonnenmessung.

Hardwareunabhängigkeit ist eine Produktanforderung: keine Pflichtfelder für Hersteller, Modell, Batterie-SoC oder feste Exportgrenze. Gerätespezifische Protokolle können außerhalb des Modellkerns auf generische HA-Leistungs-, Energie- und Abregelungssignale abgebildet werden. Ohne gebundenes Abregelungssignal wird ungedrosselter Betrieb angenommen; eine entsprechende Betreiberangabe ersetzt keine Messquellenprüfung. Bei DC kann begrenzte Energieaufnahme oder Exportkapazität betriebliche Abregelung verursachen, ein voller Akku allein belegt sie nicht. Die normale deklarierte Ausgangsbegrenzung gehört zur Physik, nicht automatisch zum Abregelungsfilter. Keine allgemeine Hardwarevalidierung oder Simulation der Batterie-/Exportsteuerung behauptet.

## Gemeinsame Datenverträge

`core/models.py`: validierte Dataclasses, timezone-aware Zeitwerte nach UTC normalisiert; SI-Einheiten mit Leistung W, Anlagenleistung kWp, Energie kWh und Azimut 0=N/90=O/180=S/270=W.

Konstruktoren und JSON-Felder: [models.py](../custom_components/adaptive_solar/core/models.py). Verbindliche Besonderheiten:

- `HorizonPoint`: `beam_transmission=0.0`, zirkulär interpoliert nur Direktlicht. `StringConfig`: `loss_fraction=0.14`, `temperature_coefficient=-0.004`, `horizon=()`; mehrere Strings teilen eine Stufe.
- `InverterConfig`: alte Positionsargumente bleiben; `output_type="ac"`, `max_output_kw=None`, `dc_loss_fraction=0.0`. Kanonisch `max_output_kw`/`output_cap_w`, Provenienz `measurement_boundary`/`MEASUREMENT_BOUNDARIES`. AC: `max_ac_kw`-Alias, Effizienz0,96, keine widersprüchlichen Grenzen. DC verlangt `output_type="dc"`/`max_output_kw`, lehnt AC-Alias/-`efficiency` ab.
- `SiteConfig.from_dict/to_dict`: `best_match`, sieben Tage, optionale Sensoren `None`, auch altes GHI-JSON. `MAX_FORECAST_DAYS=7`: ganzzahlig1–7 in Konstruktor/JSON/UI/maximalen Tagesentitäten; Provider-Quelltage erweitern nicht den Horizont.
- `Observation`: je Signal echte Berichtzeit; GHI kompatibel am Ende. `TrainingSample.features: dict[str,float]`: ausschließlich ausgabezeitlich Bekanntes, `actual_w` echtes Intervallmittel.
- `WeatherForecast.issued_at`: tatsächlicher Empfang, Cache behält ihn; keine erfundene NWP-Vintage. `ForecastResult.issued_at`: Entscheidungszeit. Alle Leads bis Zielmittelpunkt (`midpoint_lead_hours`).
- `ForecastPoint`: frühestens bei Ausgabe; laufende Zelle dort kürzen, Physik/Features/Lead neu am Mittelpunkt. `source_partial_at_issue=1` nicht lernen, Originalwetter behalten. `power_at` ist halboffenes Intervallmittel; `energy_kwh` braucht vollständige Abdeckung/alle Stufen mit UTC-Dauer. Lokale Mitternacht nach UTC übersetzen: echte23/25-Stunden-Tage.

## Schnittstellen der Teilmodule

### Physik und Wetter

`core/physics.py`, `core/engine.py`: `ForecastEngine(config).forecast(forecasts, issued_at, observations=(), learner=None) -> ForecastResult`. Der Learner liefert über `.predict(inverter_id, features, baseline_w, cap_w)` ein Objekt mit `power_w`, `lower_w`, `upper_w`, `status`; fehlendes/abgelehntes ML fällt auf Physik zurück. Mindestfeatures: `baseline_w`, `sun_elevation_deg`, `sun_azimuth_sin`, `sun_azimuth_cos`, `day_of_year_sin`, `day_of_year_cos`, `temperature_c`, `wind_m_s`, `cloud_cover_pct`, `lead_hours`.

Physikkette: GHI/DHI horizontal, DNI normal → pvlib-Sonnenstand → Hay-Davies → Faiman-Modultemperatur aus Temperatur/Wind → PVWatts-DC (25 °C Referenz) → String-`loss_fraction` → Stringsumme je Stufe. Danach AC-Effizienz/gemeinsamer AC-Clip oder nur konfigurierter DC-Stufenverlust/gemeinsamer Ausgangsclip, ohne versteckte AC-Effizienz. Auch ML/Nowcast begrenzen; Physik, Ist-Plausibilität/Restore teilen dieselbe `output_cap_w`.

Grenzen: Mittelpunkt-Sonnenstand ist keine hochaufgelöste Energiequadratur, Faiman keine vermessene Modulkalibrierung. Nomineller DC-Deckel ist ein Forecastparameter; Stromlimit und wechselnde DC-Spannung können andere Momentangrenzen ergeben. Das zyklisch linear interpolierte Horizontprofil simuliert weder Diffus-Himmelsabschirmung noch elektrische Bypass-/Stringeffekte. Standortverbesserungen sind zu messen.

Wetteradapter: ungültige/unvollständige Pflichtwerte bleiben Lücken, nie Null. Open-Meteo-Strahlung am API-Zeitpunkt `t` gehört zu `[t-1h,t)`; Temperatur/Wind/Bewölkung sind Momentanwerte bei `t`. Zwei einzeln gültige, genau stündlich benachbarte Endpunkte ergeben eine lineare Mittelpunktnäherung, kein gemessenes Stundenmittel ([Zeitdefinition](https://open-meteo.com/en/docs#hourly-parameter-definition)). Fehlende Stützen werden nicht interpoliert. Cropping/Instant-Geometrieproxy behalten konstante Quellbedingungen; neue Grenzen erzeugen keine gemessene Substundenmeteo.

Unterschiedliche Raster werden an vorhandenen Grenzen und Ausgabezeit geteilt. Je Intervall zählt nur die verfügbare Modellkohorte, ohne rückwirkende Abdeckung oder erfundene Tage. `best_match` kann andere Arme überlappen: keine behauptete Unabhängigkeit oder kalibrierte Ensemble-Unsicherheit. `PhysicsUnavailable` entfernt nur die betroffene Stufe/Modellzelle, erhält gültige Nachbarstufen und führt deren Kohorten, GHI-Regime und Instantreferenzen getrennt. Ohne gültige Berechnung bleibt eine Lücke; `inverter_id` ermöglicht selektive Stufenrechnung, unerwartete Programmierfehler propagieren.

### Lokale Eingaben und Nowcast

Alte/zukünftige Berichte bleiben ungenutzt; Temperatur/Wind werden kurzfristig an NWP angenähert. Opt-in-GHI verlangt höchstens fünf Minuten Alter sowie geeignete Sonnenhöhe/Strahlungsbasis. Haurwitz am echten Beobachtungszeitpunkt und Vierpunkt-Gaussquadratur über das **originale** NWP-Intervall liefern einen Clearness-Abgleich statt naiver Division Momentanwert/Stundenmittel. Ein begrenzter gemeinsamer GHI/DNI/DHI-Faktor erhält die Modellaufteilung; Gewicht mit 30 Minuten Zeitkonstante über maximal 90 Minuten integrieren. Das Ausgabeintervallmittel wirkt bis zum Ende der letzten überlappenden Quellstunde (Stundenraster: weniger als 150 Minuten).

GHI gilt je Stufe atomar für ihre numerisch gültige Modellkohorte, sonst bleibt die gesamte Zelle NWP. Baseline, Gain, Regime und Instantreferenz müssen dieselbe Stufenkohorte beschreiben. Betroffene Zellen veröffentlichen keine für einen anderen Datenstand kalibrierten ML-Grenzen. Entfernte Grenzen ändern auch den punktuellen Kalibrierungsstatus; die Statusunion entsteht erst nach allen Korrekturen.

Der Leistungs-Nowcast addiert eine kurze abklingende Restleistungskorrektur nur bei aktueller plausibler Produktion ohne Abregelung. Bei gebundenem Signal muss der echte Powerbericht **strikt nach Beginn des aktuellen klaren Zustands** liegen; ein älterer bleibt bis zu einem echten neuen HA-Bericht gesperrt. Seine Messzeit wird nie ersetzt.

Momentanreferenz: Original-NWP-Strahlungsmittel mit [Ineichen-Klarhimmelform](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.ineichen.html)/Achtpunkt-Gaussquadratur normalisieren, String-/Stufenphysik am echten Power-Messzeitpunkt rechnen. Das ist eine Wolkenpersistenz-Approximation, keine gemessene Feinauflösung/neues Ausgaberaster. Frische Vorstundenproben bleiben nutzbar; fehlende Quellintervalle/Kohorten werden nicht verlängert. Gleichzeitige GHI gegen **dieselbe Momentanapproximation**, nicht den gedämpften zukünftigen Zellgain abgleichen, um Wetterfehler nicht doppelt zu korrigieren. Nichtvergleichbarer Physik-/ML-Status oder unterschiedliche belegte Lernunterstützung sperren die Zusatzkorrektur; unplausible Referenzen liefern kein Residual. Beide Korrekturintegrale durch echte Ausgabezelllänge teilen: zehn Restminuten sind keine Stunde.

### Lernen und Archiv

`core/learning.py`: `ResidualLearner().fit(samples, as_of)`, `.predict(...)` wie oben, Diagnose `.status`. Je Stufe getrennte NWP-/GHI-Baselinemodelle. Zusatzfeatures: `ghi_regime` 0/1, `ghi_nowcast_gain` (NWP 1), `ghi_observation_age_seconds` (NWP 0). Im Kern sind markerfreie Zeilen NWP, unvollständige alte GHI-Marker ungültig. Sensorausfall erlaubt kein GHI-Modell auf roher NWP-Baseline.

Je Regime eigene chronologische Trainings-/Validierungs-/Kalibrierungs-Zieltage nach lokalem Intervallstart, auch über Mitternacht bei Teilstundenoffsets. Ganze frühere Zielzeilen mit `end > nächster Blockstart` werden an beiden Grenzen entfernt; Gleichheit ist zulässig. Historientage/-stunden danach erneut prüfen, Messenergie nie teilen. `purged_boundary_overlap_rows` nennt entfernte Zeilen. Je Regime: Future-Labels, Nacht, Abregelung, ungültige Daten/Duplikatgewichtung ausschließen. Aktivierung, LeadRange/Kalibrierung nicht aus dem anderen Regime leihen. Solar-Geometrie/Saison erlauben wiederkehrende Verschattung; Stufenzähler identifizieren keine Einzelstrings. Modelle aus Zeilen rekonstruieren, keine Pickles.

Standard: mindestens 28 Zieltage/240 Stunden vereinigter Messdauer, keine vollen Stunden aus Kurzfragmenten. Je aktivem Lead-Bin eigene ausreichende Trainings-/Validierungstage/-stunden, mindestens 5 % MAE-Verbesserung gegen Physik und 60 % gewonnene Validierungstage. Unterstützter Lead: Schnittmenge der Trainings-/Validierungsbereiche; unbelegt/abgelehnt bedeutet Physik. Fehlergrenzen brauchen eigene Kalibrierungstage/-stunden im Bin, keine zertifizierten P10/P90.

HA verbindet vor Zielbeginn bekannte Features erst nach Intervallende mit echten Zählerdifferenzen. Positive Tages-Baselines ohne `source_partial_at_issue` je Zielzelle/Lead-Bin/Regime getrennt archivieren; Tagesenergie-Snapshots bleiben unabhängig. Mitte heißt Origin am nächsten zur festen Binmitte:

| Stufenzahl | NWP-Origins je Bin/Zelle | Zusätzliche GHI-Origins |
| --- | --- | --- |
| 1–3 | Tatsächlich kleinster/größter Lead und Mitte | Beide Ränder |
| 4–6 | Beide Ränder | Beide Ränder |
| Ab 7 | Mitte | Nahe 1,5 h im ersten Bin, sonst Binmitte |

Regime verdrängen einander nicht; Gesamtzeilengrenzen gelten weiterhin. Mehrere Origins/Regime erzeugen keine zusätzlichen Iststunden. Zeitdauergewichte und Entdoppelung begrenzen häufige Mess-/Ausgabeereignisse. Im flachen Lernbericht stammen Zustand, MAE, Gewinnquote und Lead-Bins nur aus `primary_regime`: aktives NWP vor aktivem GHI. `active_regimes` und vollständige `regimes` bleiben getrennt; Gesamt-Historienzähler tragen `history_scope=deduplicated_all_regimes` und sind keine Primärregime-Trainingsmenge.

### Messintervalle und Persistenz

`join_training(as_of=...)` schließt Labels mit späterem `observed_at` vor Samplebau und Duplikaterkennung aus; Gleichheit ist zulässig. Der Lerner prüft die As-of-Grenze zusätzlich.

Anker nur bei strikt steigender Messzeit; ältere/doppelte Events ändern weder Anker noch Sperren. Negativer Vorwärtsdelta: Resetanker ohne Label. Keine Brücken über Lücken, unplausible Leistung/Abregelung. Gefilterte HA-Reports können unveränderte/Null-Stände als Empfangsgrenzen liefern, Polling gehaltener Werte nicht. HA-Empfang zertifiziert keine Quellenqualität. Ohne Abregelungssensor: optionale Unconstrained-Annahme statt bewiesener Freiheit; Messquelleneignung separat prüfen.

Angrenzende Messdifferenzen innerhalb einer UTC-Stunde werden exakt zusammengefasst; ganze gültige Stundenübertritte bleiben ungeteilt gespeichert. Der Join schneidet daraus keine unbekannte Randenergie: mindestens halbstündige Zielzelle, **mindestens 95 % Messabdeckung, höchstens 2,5 % Verlust an jedem Rand**. Istleistung verwendet die reale Messdauer als Nenner. `training_quality` nennt Zähler-/Alignment-Ablehnungen je Stufe ohne Origin-Mehrfachzählung.

HA `Store`: höchstens120 Tage,60.000 Forecast-/30.000 Istzeilen; Raster/Stufenzahl können die Dauer verkürzen. Ist-/Tagesenergien:10% Ausgangsgrenzentoleranz, echte UTC-/DST-Dauer, keine Bool-Werte. Zwei feste Keys: neuer `history_v2`-Primary, Legacy ausschließlich lesend. Dessen opaker Vollhash muss zur Migration exakt passen; sonst Original behalten/neuen Primary kalt beginnen. Moderner `history_fingerprint` bindet Physik/Zeitzone/Output/Energie-/Curtailmentquelle; Wetter/Horizontlänge/Temp/Wind/GHI/Power-Bindungswechsel erhalten valide Istintervalle und ausgegebene Tages-Snapshots. Forecastfeatures brauchen zusätzlich Vollhash und `learning_feature_contract`; deren Wechsel verwirft nur Lernfeatures/abgeleitete Modelle. Bekannte physische Änderungen beginnen den festen Primary neu, **erst nach erfolgreichem Erstrefresh/Plattform-/Service-Setup**. Zuvor kein Delay-/Close-Save; unbekannte/korrupte Primärdaten werden nicht überschrieben. Keine unbegrenzten Hash-Namespaces. AC-JSON/Fingerprint und HA-Store-Version bleiben kompatibel.

Modelle bei Iständerung/neuem lokalen Tag rekonstruieren; HA serialisiert Updates, offline kein paralleles `fit`/`predict` zugesichert. Tagesbeginnenergie: eigener vollständiger Snapshot vor Mitternacht, nie aus späterem Forecast rückdatieren. Keine Secrets/ausführbaren Modellobjekte persistieren.

### HA und native Energy

`weather.py`, `coordinator.py`, `config_flow.py`, `sensor.py`, `__init__.py`, `const.py`, `manifest.json`, Strings/Übersetzungen: Anlagen-/String-/Stufen-UI, native Entity-Selektoren, lokale Einheiten-/Zeit-/unavailable-Prüfung. Netzwerk async mit Timeout, Physik/ML im Executor, Wettercache, häufigerer Resttag-Refresh. Keine produktiven Fremdeinstellungen ändern.

AC-JSON behält unverändert Serialisierung/Fingerprint, neue DC-Stufen ändern ihn. Keine Power-/Energy-Bindung für mehrere unabhängige Stufen; gemeinsames Curtailment erlaubt. AC/DC-Typwechsel im Optionsflow verwirft alte Messbindungen. AC-Entity-IDs bleiben kompatibel, DC-/Mixed-Gesamtsensoren nutzen getrennte Historien-Namespaces.

Qualität: `SensorDeviceClass.ENUM`, keine Genauigkeits-/Konfidenzklasse. Priorität: aktive Abregelung → partielle Resttagabdeckung → beeinträchtigte konfigurierte Eingaben/unbekannte Abregelung → Physik, teilweise (`mixed`) oder vollständige Residualanwendung. Tatsächlicher Ausgabestatus gilt horizonweit; inaktives Gegenregime/Nacht-/Nullzellen verdecken aktive Tageskorrekturen nicht. `learning_horizon`: globaler Scope, Rohstatus, NWP-/GHI-Validierungsranges; `coverage_scope`: Resttag. Horizonweite Wetter-/Physikdiagnosen und letzter Abruffehler bleiben Attribute: Zusatzproviderausfall/ferne Lücke degradieren gültige heutige Ausgabe nicht; echte Resttagslücken bleiben `partial`.

Native `wh_hours`: nur vollständige UTC-Stunden **aller** Stufen homogener AC-/DC-Entries; kleinere Zellen nach Dauer integrieren. Angefangene Stunden fehlen, Resttag/Qualitätskurve behalten verbleibende Teilenergie. Keine Minutenkeys als Stunden-Wh/erfundene Vorenergie; DST behält 23/25 UTC-Stunden.

Mixed-Entries behalten Stufensensoren und `mixed_output_generation_sum` verschiedener Messpunkte, ohne AC-Netz-/Batteriefluss oder nativen Gesamtforecast einer Messgrenze. `native_energy_eligible=False` gilt der Entry-Schnittstelle, nicht fehlenden Stufenprognosen. `output_type`, `output_types`, `measurement_boundary`, `measurement_boundaries`, `output_stage_boundaries` bleiben auch ohne Zustände verfügbar. CLI nennt Stufe/nominelle W-Grenze ohne Sensorbindungen/Standort.

## Nachweis

`services.py` liest native Helios-/Open-Meteo-Wh mit Domain-Allowlist/Timeout, ohne Energy-Preferences-Write. `capture_ha.py`/`capture_actuals.py` bewahren Empfang, Rohrevision, Einheiten/Qualitätsprovenienz; spät geprüfte Altstände verdecken keine neuere Invalidierung und erzeugen keine rückdatierten Labels. Ablauf/Formate: [Aufnahmeleitfaden](benchmark-aufnahme.md).

`core/evaluation.py` bewertet archivierte statt neu rekonstruierte Prognosen auf identischen Fenstern/Cutoffs. Gemeinsamer Lead geht vom Cutoff bis Fenstermitte, Issuezeiten wählen nur zulässige Snapshots. Ganze gemessene Istintervalle bleiben ungeschnitten, Prognosemittel zuschneidbar, fehlende Werte niemals Null. `interval_task_identity=[cutoff,inverter_id,start,end]`: Intervallzählung/-energie ist Taskexposition, dauergewichtet, keine unabhängige Stichprobe/einmalige Erzeugung. Schätzer/Gates bleiben unverändert.

Je Stratum/Referenz liefern nur vollständige geplante Origins eines Zieltags mittleren Fehler/eine Stimme; Gesamtquote ist das Minimum. `statistical_validation.py` resampelt alle Strata/Referenzen desselben Tages gemeinsam. Familienkonfidenz, Bonferroni, Seed/Resamples versioniert; keine Ersatzaussage bei fehlenden Strata/gescheitertem deskriptivem Gate. [Vorabkriterien/Reviewaudit](validierung.md) und Testdatenfluss sind keine Feldgüte; fairer prospektiver Vergleich bleibt nötig.
