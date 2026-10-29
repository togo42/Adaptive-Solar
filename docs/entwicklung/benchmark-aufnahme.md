# Prospektive Vergleichsaufnahme

Stand: 29.10.2026. Collector mit simulierten HA-Antworten getestet; historische Adapterprüfungen sind kein gestarteter produktiver Vergleich. Annahmekriterien: [Validierungsplan](validierung.md).

Die ursprünglichen Collector sichern Prognoseergebnisse und Istwerte. Der
seit 0.2.16 veröffentlichte Archivzweig ergänzt
[Originalwetterexport, Langzeitarchiv und Replay](../archiv/archivbetrieb.md).
`archive_observations.py` legt die hier beschriebenen Recorder-/Referenzaufnahmen
verlustfrei im gemeinsamen Archiv ab; `archive.py export-observations` erzeugt
wieder die Capture-JSONL für vorhandene Auswerter. Bestehende Qualitäts- und
Verfügbarkeitsregeln gelten weiter.

`capture_ha.py` und `capture_actuals.py` benötigen den gemeinsamen Helfer
`scripts/replay_paths.py`; sie werden aus dem vollständigen Checkout ausgeführt.
Ihre Appendziele müssen eigene Dateien ohne Hardlink-Aliase unter `data/` sein.
Eingaben sowie Programm-/Ressourcendateien sind vor dem Netzabruf und nochmals
unmittelbar vor dem Schreiben geschützt. Die spätere Prüfung verwendet den
geöffneten Dateideskriptor samt Geräte-/Inode-Identität; ein nachträglich
ausgetauschter Zielpfad wird abgelehnt. Vor dem Abruf erfasste geschützte
Inodes bleiben auch nach Verschieben/Ersetzen ihrer ursprünglichen Pfade
gesperrt. Lock und Vollständigkeitsprüfung lesen
denselben Deskriptor. Ein fehlgeschlagener Append kann eine unvollständige letzte
Zeile hinterlassen; sie wird beim nächsten Lauf nicht fortgeschrieben oder
automatisch repariert. Die Datei bleibt als Fehlernachweis erhalten.

## 1. Vergleichbare Messgrenze wählen

Alle drei Anbieter müssen dieselben Module, Ausgabestufen, nominellen Grenzen und dieselbe AC-/DC-Messgrenze abbilden. Keine Aufteilung eines Anlagenwerts auf Einzelstufen. Native Adaptive-Energy-Prognosen gelten für homogene Entries; Stufen liefern eigene Qualitätskurven, Mixed-Entries keinen Gesamtforecast einer einzelnen Messgrenze.

`capture_ha.py` liest `energy/solar_forecast`, `get_states` und optional `adaptive_solar.get_reference_forecasts`. Es archiviert nur ausgewählte native Wh/Kurvenattribute und aktualisiert weder Anbieterwetter noch Einstellungen. Energy liefert bereits verknüpfte Anbieter; HA 2026.10.2/.3 akzeptiert dort kein `config_entry_ids`, daher lokale Auswahl. Nach regulärer Adaptive-Einrichtung kann die reine Antwortaktion geladene Helios-/Open-Meteo-Entries ohne Energy-Umschaltung lesen. Fehlende Installation/Service bleibt fehlend.

Der Antwortservice und der Collector prüfen `wh_hours` auf vollständige
**UTC-Stundenbeginne nach der Zeitzonennormalisierung**. Beispielsweise ist
`2026-06-01T15:30:00+05:30` derselbe gültige Stundenbeginn wie `10:00:00Z`;
`15:00:00+05:30` liegt dagegen außerhalb des UTC-Stundenrasters. Gleichwertige
Offsetdarstellungen dürfen zusammengeführt werden, doppelte absolute Stunden
innerhalb derselben Quelle bleiben ungültig. Die ursprünglichen Snapshotkeys
bleiben erhalten; normalisierte Records verwenden UTC. Energie wird dadurch
nicht verschoben, geteilt oder ergänzt.

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

Echte Auswertung braucht den vollständigen vorher deklarierten Zielplan und alle qualifizierten Istintervalle. Produktive Sensor-/Statistikzuordnung bleibt zu prüfen. Alternativ können `forecasts` direkt als `ForecastRecord` vorliegen; dann muss der Aufrufer vollständige Ausgabe-/Ausfallprovenienz liefern. Direkte `forecasts` dürfen wie bisher zusätzlich zu Prognosearchiven vorliegen und bleiben denselben Anforderungen unterworfen. Direkte `actuals` sind dagegen eine Alternative zu `--actual-captures`; nichtleere Inline-Istwerte dürfen nicht mit dem Ist-Capturearchiv kombiniert werden. Siehe [Implementierungsvertrag](../technik/implementation-contract.md) für unverändert ganze Istintervalle, zuschneidbare Prognosemittel und Revisionen.

Die Auswertung und `forecast.py` verwenden die gemeinsame Ausgabeprüfung:
Ausgaben bleiben außerhalb der Programmverzeichnisse `scripts/` und
`custom_components/`. Eingaben und dortige Quell-/Ressourcendateien sind keine
zulässigen Ausgabeziele, einschließlich Symlink-/Hardlink-Aliasen.
Die Prüfung läuft vor Berechnung beziehungsweise Netzabruf und nochmals vor
atomarer Veröffentlichung. Ein unbeteiligter Hardlink auf einen alten Bericht
wird durch die atomare Ersetzung nicht mitverändert.

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

Positive Freigabe benötigt weiterhin eine vollständig belegte Recorderstunde;
eine klare Teilmaske genügt nicht und erneuert keine positive Qualitätsrevision.
Negative oder ausdrücklich unbestätigte Qualität wirkt dagegen bereits bei
jeder echten zeitlichen Überschneidung: Abregelung, Reset, ungültige oder
unbestätigte Messabdeckung sperren die **ganze unteilbare Stunde**. Die Energie
wird nicht in einen vermeintlich guten Rest aufgeteilt. Reine Randberührung
ist keine Überschneidung.

Der Adapter berücksichtigt negative Masken auch gegen bereits akzeptierte
Stunden aus anderen Captures, selbst wenn die aktuelle Recorderabfrage einen
anderen Zeitraum oder eine andere Stufe betrifft. Eine Negativmaske erzeugt
keine neuen Messlabels. Maßgeblich sind ihr eigener `validated_at`-Zeitpunkt
und die tatsächliche Verfügbarkeit `max(retrieved_at, validated_at)`. Vor diesem
Cutoff wirkt sie nicht. Ein neuer Rohabruf mit einer älteren positiven Maske
hebt eine neuere Qualitätsinvalidierung nicht auf. Eine tatsächlich neuere
vollständige positive Qualitätsrevision kann dieselben unveränderten Istwerte
wieder qualifizieren; konkurrierende Qualitätsaussagen gleicher Revision
bleiben gesperrt. Eine noch spätere negative Revision sperrt erneut.

Erst nach tatsächlicher Prüfung `--quality data/actual-quality.json` ergänzen. Unbekannte Qualität ausschließen; später geprüfte Masken behalten ihre echte Verfügbarkeitszeit, keine rückdatierten Labels. Integrierte Leistung ist keine native Gerätezählung: zusätzlich Verfügbarkeit, Abdeckung, Reset-/Integrationsverhalten und unabhängige Referenz prüfen. Ein Gesamtzähler qualifiziert nicht automatisch Teilzähler; nominelles Hardwarelimit ist keine betriebliche Abregelung.

Archiviert werden native WS-Millisekunden, Metadaten/Einheiten, Rohänderungen und Qualitätsprovenienz. Eine Vorläuferstunde hilft, nach Statistiklücken aufgelaufene Deltas auszuschließen. Recorder-Korrekturen bleiben eigene Revisionen; Widersprüche klären. Spät geprüfte Altstände verdecken keine neuere Invalidierung. Dateisperre schützt Ergänzungen.

Eine tatsächlich vorhandene Vorlaufzeile mit `change=None`, fehlendem Wert,
negativer oder nichtendlicher Energie ist eine eigene negative Rohrevision für
ihre Stunde, auch wenn diese nicht zum positiven Zielbereich des neuen Captures
gehört. Ihre Verfügbarkeit und Revisionsachse sind der echte Rohdatenempfang,
nicht eine spätere Qualitätsprüfung. Eine lediglich fehlende Vorlaufzeile
widerlegt dagegen keine ältere vollständige Messung. Im lokal geprüften
HA Core 2026.10.4 liest `_augment_result_with_change` die DB-Summenbasis vor
Abrufbeginn separat über `_statistics_at_time`; `change=None` entsteht bei
aktueller `sum=None`, nicht wegen eines verkürzten Abfragekontexts.

Ein vollständig vorhandener, metadatengültiger Vorlaufsummenwert wird nur mit
einer bereits akzeptierten gleichstündigen Energie desselben Scopes verglichen.
Ein abweichender Wert ab deren letztem qualifizierten Rohdatenempfang ist ein
expliziter Revisionskonflikt. Teilwerte oder unverifizierte Einheiten ergeben
keinen solchen Summenvergleich. Ein identischer Vorlauf erzeugt kein neues
Positivlabel und erneuert keine positive Rohrevision; eine frühere Invalidierung
bleibt damit gesperrt, bis ein regulär qualifizierter Targetcapture sie aufhebt.
Ein älterer Vorlauf sperrt keinen neueren qualifizierten Targetwert.

Der Adapter normalisiert jedes Capture erneut und prüft die gespeicherte
Ableitung exakt. Alte vollständig gültige Captures bleiben lesbar. Unter der
früheren fehlerhaften Teilmaskenregel gespeicherte negative Captures können nur
`missing_quality_evidence` enthalten und stimmen dadurch nicht mehr mit dem
korrigierten Vertrag überein: Sie führen bewusst zu `CaptureError`, weil die
Integritätsprüfung vor der As-of-Auswahl erfolgt. Originale bleiben unverändert. Eine gesonderte explizite Neunormalisierung muss dieselben
ursprünglichen Rohdaten und Qualitätsmasken verwenden und deren echten
`retrieved_at`-/`validated_at`-Zeitpunkte erhalten; `normalized_at` benennt den
wahren Zeitpunkt der neuen Ableitung. Es werden weder alte
Ableitungen still ignoriert noch Empfangszeiten neu erfunden.

Für `--actual-captures` muss die Eingabedatei `actuals` weglassen oder
`"actuals": []` enthalten. Nichtleere Inline-Istwerte dürfen nicht gleichzeitig
mit dem Capturearchiv verwendet werden: Dessen spätere Invalidierungen könnten
sonst an alten Inline-Positivlabels vorbeigehen. Reiner Inlinebetrieb bleibt
möglich, er verlangt weiterhin vollständige eigene Qualitätsprovenienz.
Gemeinsame Auswertung:

```bash
.venv/bin/python scripts/evaluate.py data/vergleich.json \
    --captures data/forecast-captures.jsonl \
    --actual-captures data/actual-captures.jsonl \
    --bootstrap --output artifacts/vergleich.json
```

## 6. Ergebnis interpretieren

Der separate [Offline-Qualitätsadapter](../archiv/istwert-qualitaetsadapter.md)
kann aus Originalintervallen und expliziten Quellenattestierungen passende
Stundenmasken ableiten. Er ist ein Entwicklungskandidat, keine automatische
Qualifikation vorhandener Recorderwerte und noch keine produktive Hostanbindung.

Abdeckung, Quellenlücken und Leistungs-/Energiefehler werden nach Stufe/Horizont/Tages-/Resttagaufgabe berichtet. Intervallaggregate sind dauergewichtete **Prognoseaufgaben** unterschiedlicher Cutoffs: Exposition, keine einmalige Erzeugung/unabhängige Stichprobenzahl.

Schon ohne Bootstrap benötigt jedes Stufen-/Horizontstratum mindestens 30
Zieltage, an denen sämtliche für diesen Tag geplanten Origins vollständig
gepaart sind. `strata.*.complete_target_days` ist derselbe Nenner wie
`daily_win_by_inverter_horizon.*.paired_target_days`. Ein vollständiger Origin
kann einen fehlenden zweiten Origin desselben Tages nicht ersetzen; eine hohe
Gewinnquote auf nur 29 vollständigen Tagen reicht nicht. `paired_target_days`
auf Berichtsebene zählt dagegen Tage mit gepaarten Intervallaufgaben und ist
allein kein Bereitschaftsnachweis.

Ohne `--bootstrap`: `not_evaluated`. Policy `paired-target-day-bootstrap-v1`: mindestens30 gemeinsam vollständige Zieltage; Origins/Strata/Referenzen desselben Tages gemeinsam ziehen. Defaults:95% Familienkonfidenz/Bonferroni, mindestens20.000 Resamples, Seed`20261024`; nur Familiengröße darf die CI-Auflösung erhoehen. `--bootstrap-resamples`, `--bootstrap-seed`, `--bootstrap-confidence` vor Sichtung fixieren; Ergebnis dokumentiert sie.

Primäre Energie-Strata, deskriptives Gate,5%-Skill-Untergrenze/negative MAE-Differenz-Obergrenze sowie Grenzen von `accepted_conditional`: [Annahmekriterien](validierung.md#3-vorläufige-annahmekriterien). Repräsentative austauschbare Tage bleiben eine Annahme; keine Ganzjahres-/Produktionsfreigabe.
