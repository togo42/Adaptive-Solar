# Prospektive Vergleichsaufnahme

Stand: 25.10.2026. Collector lokal mit simulierten HA-Antworten getestet; native Adapter/Statistikquellen lesend geprüft. Kein produktiver Vergleich gestartet und keine HA-Einstellung verändert. Diese Anleitung konsolidiert den lokal archivierten Vorgänger `artifacts/releases/0.2.5-blocked/source/docs/benchmark-aufnahme.md`; das Archiv wird nicht veröffentlicht. Annahmekriterien: [Validierungsplan](validierung.md).

## 1. Vergleichbare Messgrenze wählen

Alle drei Anbieter müssen dieselben Module, Ausgabestufen, nominellen Grenzen und dieselbe AC-/DC-Messgrenze abbilden. Keine Aufteilung eines Anlagenwerts auf Einzelstufen. Native Adaptive-Energy-Prognosen gelten für homogene Entries; Stufen liefern eigene Qualitätskurven, Mixed-Entries keinen Gesamtforecast einer einzelnen Messgrenze.

`capture_ha.py` liest `energy/solar_forecast`, `get_states` und optional `adaptive_solar.get_reference_forecasts`. Es archiviert nur ausgewählte native Wh/Kurvenattribute und aktualisiert weder Anbieterwetter noch Einstellungen. Energy liefert bereits verknüpfte Anbieter; HA 2026.10.2/.3 akzeptiert dort kein `config_entry_ids`, daher lokale Auswahl. Nach regulärer Adaptive-Einrichtung kann die reine Antwortaktion geladene Helios-/Open-Meteo-Entries ohne Energy-Umschaltung lesen. Fehlende Installation/Service bleibt fehlend.

## 2. Private Zuordnung erstellen

`data/benchmark-map.json`, ausschließlich fiktive Platzhalter:

```json
{"mappings":[
  {"inverter_id":"roof","source":"adaptive","quality_entity_id":"sensor.PRIVATE_adaptive_roof_quality"},
  {"inverter_id":"roof","source":"helios","reference_entry_ids":["PRIVATE_HELIOS_ROOF_ENTRY"]},
  {"inverter_id":"roof","source":"open_meteo","reference_entry_ids":["PRIVATE_OPEN_METEO_EAST","PRIVATE_OPEN_METEO_WEST"]}
]}
```

Je Gruppe genau eine alternative Auswahl; keine ID mehrfach zuordnen:

| Selektor | Quelle/Regel |
| --- | --- |
| `quality_entity_id` | Native Adaptive-Kurve, auch je Stufe. |
| `reference_entry_ids` | Original-Wh der reinen Leseaktion; höchstens 16 explizite geladene Helios-/Open-Meteo-Entries. |
| `entry_ids` | Original-Wh aus vorhandener Energy-Verknüpfung. |
| `wh_period_entities` | Native Open-Meteo-Tagesattribute; z. B. `[["sensor.PRIVATE_east_today","sensor.PRIVATE_east_tomorrow"],["sensor.PRIVATE_west_today","sensor.PRIVATE_west_tomorrow"]]`. Tage innerhalb einer Liste vereinigen, zwischen Listen gleich abgedeckte Arrays summieren. |
| `wh_period_15m_entities` | Originale Viertelstunden-Wh gemeinsamer DC-Arrays; `output_cap_w` und `measurement_boundary="dc_charge_controller_output"` erforderlich. |

Summen benötigen vollständige identische Raster; fehlende Beiträge ergeben keine Teilsumme. Gerundete Helios-Leistungspunkte werden nicht als Original-Wh integriert.

### Gemeinsame DC-Begrenzung

Synchronisierte Array-Wh je 900-s-Slot summieren, gemeinsam auf `output_cap_w / 4` begrenzen, danach vier vollständige Slots zur Stunde addieren. Nachträglicher Stundenclip ist bei variablem Verlauf nicht gleichwertig. Fiktives Mapping:

```json
{"inverter_id":"controller","source":"open_meteo",
 "wh_period_15m_entities":[["sensor.PRIVATE_facade_today","sensor.PRIVATE_facade_tomorrow"],["sensor.PRIVATE_roof_today","sensor.PRIVATE_roof_tomorrow"]],
 "output_cap_w":2500,"measurement_boundary":"dc_charge_controller_output",
 "measurement_boundary_evidence":"PRIVATE_VERIFIED_CONFIG_AND_METER_REFERENCE"}
```

`wh_period_15m` ist **startgelabelt**: `[t,t+15min)`. Der Producer hat API-Endzeiten bereits umgerechnet; kein weiterer Offset. Geprüft: native Adapter und veröffentlichte Distribution 0.1.32, nicht die installierte Core-Dependencyversion. Der [Primärquellstand](https://github.com/rany2/open-meteo-solar-forecast/blob/5a8f3da2620c163e6f360f3c063823e273a7e140/src/open_meteo_solar_forecast/open_meteo_solar_forecast.py#L510) bestätigt dies.

Originalattribute bleiben erhalten; Normalisierung `native_15m_sum_shared_cap_then_hour_sum`. Native Arraylimits werden nicht rückgängig gemacht; fehlende/null/bool/negative Slots bleiben Lücken. Helios-Wh unverändert. Alle Selektoren erlauben deklarierte `measurement_boundary`/private `measurement_boundary_evidence`. Native Metadaten bleiben in `entity_snapshots`/`native_metadata`; widersprüchliche Deklaration ist ungültig. Legacy-Captures ohne Metadaten sind lesbar, kein Messgrenzenbeweis.

## 3. Aufnahme ausführen

`HA_URL`/`HA_TOKEN` lokal über die Umgebung bereitstellen; Zugangsdaten nicht in Dateien, Beispiele, Git oder Reviewpayloads schreiben. Fristen vorab festlegen: Ein Cronstart genau zur Frist ist zu spät, denn der tatsächliche Gruppenempfang muss davor liegen. Fiktiven Termin ersetzen und zunächst nur lokal prüfen:

```bash
.venv/bin/python scripts/capture_ha.py \
    --config data/benchmark-map.json \
    --output data/forecast-captures.jsonl \
    --cutoff 2026-11-02T09:00:00+01:00 --preflight
```

Preflight: kein HA-Aufruf/Archivwrite; verlangt deklarierte Messgrenzenbelege und mindestens `timeout + cutoff-margin` Vorlauf, standardmäßig 30 + 5 Sekunden. `forecast_capture_ready` betrifft nur diese Bedingungen, keine Anbieter-/Quellenqualität oder Annahme. Für echte Aufnahme `--preflight` entfernen, Frist beibehalten. Hier wird kein Zeitplan aktiviert.

JSONL wird exklusiv gesperrt ergänzt, nie ersetzt; auch gleiche Kurven behalten separate Empfangszeiten, unvollständige letzte Zeilen werden nicht repariert. Tatsächliches `retrieved_at` gilt konservativ als `issued_at`, keine erfundene frühere Provider-/NWP-Vintage. Späte Antworten bleiben roh erhalten: `cutoff_eligible=false`, `timing_status=late`, Exit 1; für die frühere Frist unzulässig. Ausfälle als Status bewahren, damit ältere Erfolge sie nicht verdecken.

## 4. Messwerte und erwarteten Zeitplan ergänzen

`actuals.power_w` ist ein echtes gemessenes Intervallmittel: `Energie_kWh * 1000 / Dauer_Stunden`, keine Momentanleistung. Reset/Lücken/Abregelung kennzeichnen; ganze lokale Tage brauchen auch belegte Nachtabdeckung. Gekürztes **synthetisches**, nicht annahmefähiges `data/vergleich.json`:

```json
{"as_of":"2026-06-02T01:00:00+02:00","timezone_name":"Europe/Berlin",
 "sources":["adaptive","helios","open_meteo"],
 "actuals":[{"inverter_id":"roof","start":"2026-06-01T12:00:00+02:00","end":"2026-06-01T13:00:00+02:00","power_w":2000,"observed_at":"2026-06-01T13:05:00+02:00","curtailed":false}],
 "windows":[{"inverter_id":"roof","cutoff":"2026-05-31T18:00:00+02:00","start":"2026-06-01T12:00:00+02:00","end":"2026-06-01T13:00:00+02:00","daylight":true}]}
```

Echte Auswertung braucht den vollständigen vorher deklarierten Zielplan und alle qualifizierten Istintervalle. Produktive Sensor-/Statistikzuordnung bleibt zu prüfen. Alternativ können `forecasts` direkt als `ForecastRecord` vorliegen; dann muss der Aufrufer vollständige Ausgabe-/Ausfallprovenienz liefern. Direkte `actuals`/`forecasts` zusätzlich zu Archiven bleiben denselben Anforderungen unterworfen. Siehe [Implementierungsvertrag](implementation-contract.md) für unverändert ganze Istintervalle, zuschneidbare Prognosemittel und Revisionen.

## 5. Istwerte lesend archivieren

`capture_actuals.py` liest Recorder-Metadaten und stündliche `change`-Energie. Native `statistics_unit_of_measurement` belegt die gespeicherte Energieeinheit; Legacyalias bleibt lesbar. Displayeinheit darf anders skaliert sein. Zahlen werden ausschließlich aus `request.units.energy` umgerechnet. Fiktive `data/actual-map.json`: `{"mappings":[{"inverter_id":"roof","statistic_ids":["sensor.PRIVATE_production_energy"]}]}`. Summierte IDs brauchen dieselbe erklärte Messgrenze und identische Stundenabdeckung.

```bash
.venv/bin/python scripts/capture_actuals.py \
    --config data/actual-map.json \
    --start 2026-06-01T00:00:00+02:00 --end 2026-06-02T00:00:00+02:00 \
    --output data/actual-captures.jsonl
```

Ohne Qualitätsdatei nur Rohdaten: vollständiges Statistikraster beweist keine physische Verfügbarkeit. Aus geprüften Quellen müssen Abdeckung, Abregelung und Reset für das **ganze** Intervall belegt sein; der Collector zertifiziert diese Quellen nicht. Fiktive `data/actual-quality.json`:

```json
{"schema_version":1,"validated":true,
 "provenance":{"source":"PRIVATE_REFERENCE_TO_VERIFIED_MEASUREMENT_AND_CURTAILMENT_LOG","validated_at":"2026-06-02T01:00:00+02:00"},
 "intervals":[{"inverter_id":"roof","start":"2026-06-01T00:00:00+02:00","end":"2026-06-02T00:00:00+02:00","quality":"valid","complete_coverage":true,"curtailed":false,"counter_reset":false}]}
```

Erst nach tatsächlicher Prüfung `--quality data/actual-quality.json` ergänzen. Unbekannte Qualität ausschließen; später geprüfte Masken behalten ihre echte Verfügbarkeitszeit, keine rückdatierten Labels. Integrierte Leistung ist keine native Gerätezählung: zusätzlich Verfügbarkeit, Abdeckung, Reset-/Integrationsverhalten und unabhängige Referenz prüfen. Ein Gesamtzähler qualifiziert nicht automatisch Teilzähler; nominelles Hardwarelimit ist keine betriebliche Abregelung.

Archiviert werden native WS-Millisekunden, Metadaten/Einheiten, Rohänderungen und Qualitätsprovenienz. Eine Vorläuferstunde hilft, nach Statistiklücken aufgelaufene Deltas auszuschließen. Recorder-Korrekturen bleiben eigene Revisionen; Widersprüche klären. Spät geprüfte Altstände verdecken keine neuere Invalidierung. Dateisperre schützt Ergänzungen. Gemeinsame Auswertung:

```bash
.venv/bin/python scripts/evaluate.py data/vergleich.json \
    --captures data/forecast-captures.jsonl \
    --actual-captures data/actual-captures.jsonl \
    --bootstrap --output artifacts/vergleich.json
```

## 6. Ergebnis interpretieren

Abdeckung, Quellenlücken und Leistungs-/Energiefehler werden nach Stufe/Horizont/Tages-/Resttagaufgabe berichtet. Intervallaggregate sind dauergewichtete **Prognoseaufgaben** unterschiedlicher Cutoffs: Exposition, keine einmalige Erzeugung/unabhängige Stichprobenzahl.

Ohne `--bootstrap`: `not_evaluated`. Policy `paired-target-day-bootstrap-v1`: mindestens30 gemeinsam vollständige Zieltage; Origins/Strata/Referenzen desselben Tages gemeinsam ziehen. Defaults:95% Familienkonfidenz/Bonferroni, mindestens20.000 Resamples, Seed`20261024`; nur Familiengröße darf die CI-Auflösung erhoehen. `--bootstrap-resamples`, `--bootstrap-seed`, `--bootstrap-confidence` vor Sichtung fixieren; Ergebnis dokumentiert sie.

Primäre Energie-Strata, deskriptives Gate,5%-Skill-Untergrenze/negative MAE-Differenz-Obergrenze sowie Grenzen von `accepted_conditional`: [Annahmekriterien](validierung.md#3-vorläufige-annahmekriterien). Repräsentative austauschbare Tage bleiben eine Annahme; keine Ganzjahres-/Produktionsfreigabe.
