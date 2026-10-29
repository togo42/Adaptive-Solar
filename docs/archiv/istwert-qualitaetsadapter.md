# Istwerte offline aus archivierten Messnachweisen qualifizieren

Stand: 29.10.2026, Entwicklungskandidat. Der Adapter gehört noch nicht zum
veröffentlichten Release 0.2.18 und ist in keinem Timer aktiviert. Er liest lokale
Originalauszüge, prüft Stundenabdeckung und erzeugt eine neue Qualitätsrevision
für den bestehenden [Recorder-Collector](../entwicklung/benchmark-aufnahme.md).
Er verändert weder HA noch Originalarchive und bescheinigt keine Prognosegüte.

## 1. Was automatisch geprüft wird

`scripts/qualify_actuals.py` verbindet die unveränderte Recorder-Stundenenergie
mit nativen `qualified_interval`-Ereignissen. Der HA-Producer exportiert diese
nach seiner Zähler-, Kontinuitäts- und gegebenenfalls Abregelungsprüfung, vor der
Zusammenfassung für das Lernen. Positive Freigabe verlangt:

- Eine eindeutige 1:1-Zuordnung des externen Scopes zu genau dem konfigurierten
  Energiezähler. Summierte Recorderstatistiken werden vorerst abgewiesen.
- Vollständige, lückenlose UTC-Stundenabdeckung. Auch eine Sekunde Lücke bleibt
  eine Lücke; die 92-%-/Randregeln des Lernens werden nicht übernommen.
- Einen gemeinsamen Quellen-, Generations- und Kontinuitätsabschnitt.
  Abweichende Überlappungen oder widersprechende Generationen sperren die Stunde.
  Identische Originalereignisse beziehungsweise identische Payloads sind
  idempotent. Geänderte Payloads gelten nicht als Duplikate.
- Bekannten Messvertrag, endliche nichtnegative Energie, höchstens 900 Sekunden
  je Originaldelta und die vorhandene 110-%-Plausibilitätsgrenze der Stufe.
- `end <= observed_at <= received_at <= as_of`. Zukünftige Evidenz schließt keine
  historische Lücke. Ein Phasenbeginn innerhalb der Stunde sperrt sie, auch bei
  einem Reset genau am Stundenanfang; ein früherer Phasenbeginn darf gültige
  stundenübergreifende Abdeckung liefern.
- Bei konfiguriertem Abregelungssignal den Vertrag `non-restored-control-v1` in
  jedem verwendeten Intervall. Ohne Signal ist eine explizit begründete Annahme
  unbeschränkten Betriebs erforderlich.

Ein Originaldelta darf die Stundengrenze überschreiten. Nur seine boolesche
Qualitätsabdeckung wird auf die Stunde bezogen; seine Energie wird nie geteilt.
Die Energie bleibt der vollständige originale Recorder-`change`-Wert. Auch
Nachtstunden benötigen belegte Abdeckung; es werden keine Nullwerte erfunden.

## 2. Warum eine zusätzliche Quellenbindung nötig ist

Ein natives `qualified_interval` enthält bisher weder Konfigurations-/Softwarehash
noch Energie-Entity. Die Journalgeneration kann einen Reload überleben.
Ein benachbarter Forecast mit Standortkonfiguration belegt deshalb allein keine
durchgehend unveränderte Zuordnung. SHA256 bestätigt unveränderte Bytes und
ersetzt keinen Herkunfts- oder physischen Qualitätsnachweis.

Der Adapter verlangt eine private, zeitlich begrenzte Quellenattestierung.
Ein Vorschlag mit ungeprüften Facetten ist zulässig: Er liefert Abdeckungsdiagnosen,
aber keine positiven Stundenmasken. Die drei getrennten Facetten bedeuten:

| Facette | Inhalt der externen Prüfung |
| --- | --- |
| `configuration` | Genau diese historische Quellen-/Generations-/Entity-Zuordnung, Konfiguration und dieser vertrauenswürdige Producerstand gelten im gesamten angegebenen Zeitraum. Der Anker-Forecast allein genügt nicht. |
| `meter` | Eignung der konkreten Messquelle einschließlich Frische, Ausfall-/Resetverhalten und Einheiten. Bei `power_integral` auch Powerquelle, Integrations-/Recoveryverhalten und unabhängiger Referenzabgleich. |
| `curtailment` | Eignung des konfigurierten Abregelungssignals oder begründete Annahme unbeschränkten Betriebs. Eine dokumentierte Betreiberangabe bleibt als solche gekennzeichnet; fehlende Telemetrie wird nicht automatisch durch einen neuen Sensorzwang ersetzt. |

Jede bestätigte Facette braucht ihre tatsächliche Prüfzeit und einen konkreten
Evidenzverweis. Der Adapter validiert diese Behauptungsstruktur, zertifiziert
aber nicht die genannten Belege. `configuration` umfasst ausdrücklich auch
die Producerkontinuität: Intervallereignisse tragen dessen Hash nicht selbst.
Vorhandene widersprechende Konfigurations-/Producer-Snapshots im gebundenen
Zeitraum sperren dessen Stunden trotz positiver Attestierung.

Format `adaptive-solar-actual-quality-bindings-v1`, ausschließlich Platzhalter:

```json
{
  "schema": "adaptive-solar-actual-quality-bindings-v1",
  "bindings": [{
    "id": "roof-source-period-1",
    "inverter_id": "roof",
    "statistic_id": "sensor.PRIVATE_energy",
    "source": "ha-PRIVATE-source",
    "generation": "PRIVATE-native-generation-uuid",
    "source_inverter_id": "roof",
    "config_event_id": "PRIVATE-native-forecast-event-id",
    "config_sha256": "PRIVATE-sha256-of-canonical-original-site-json",
    "producer_sha256": "PRIVATE-original-software-source-sha256",
    "valid_from": "2026-06-01T00:00:00+00:00",
    "valid_to": "2026-06-02T00:00:00+00:00",
    "measurement_kind": "native_counter",
    "curtailment_mode": "signal",
    "qualification": {
      "configuration": {"verified": false, "evidence": null, "validated_at": null},
      "meter": {"verified": false, "evidence": null, "validated_at": null},
      "curtailment": {"verified": false, "evidence": null, "validated_at": null}
    }
  }]
}
```

`measurement_kind` erlaubt `native_counter` oder `power_integral`,
`curtailment_mode` erlaubt `signal` oder `unconstrained` und muss zur
Konfiguration passen. `config_sha256` verwendet die kanonischen JSON-Bytes von
`payload.site`; `producer_sha256` ist der archivierte `software.source_sha256`.
Originale und Hashes können die übrigen Facetten nicht selbst auf `true` setzen.
Bindungen desselben Scopes dürfen sich zeitlich nicht überlappen. Sie müssen
abgelaufene Zeiträume beschreiben und die gesamten verwendeten Originaldeltas
einschließlich deren Stundenrandüberschreitungen abdecken.

### Historische Bindungen nachträglich prüfen

Eine belastbare Nachprüfung kann vorhandene Stunden freigeben, ohne die
ursprünglichen Recorderwerte oder deren Empfangszeit zu ändern. Dafür sind
getrennte, zeitlich begrenzte Nachweise erforderlich:

1. **Originalbestand einfrieren.** Capture, vollständige ausgewählte Ereignisse
   und Konfigurationshistorie mit Dateihashes erhalten. Die Auswahl und ihre
   Grenzen dokumentieren; widersprechende Ereignisse bleiben Teil der Prüfung.
2. **Historische Zuordnung belegen.** Original-Zählerberichte an beiden
   Intervallenden mit Entity, Generation, Zeit und Delta verknüpfen. Für eine
   Zuordnung über `continuity_id` zusätzlich den tatsächlich eingesetzten Code
   prüfen: Entsteht die Kennung neu, wird sie nicht wiederhergestellt, und
   erzwingen Konfigurationswechsel einen neuen Tracker? Nur dann kann eine
   durch Originalintervalle beidseitig umschlossene Konfigurationsaufnahme
   zusammen mit belegten Installationsständen eine begrenzte Attestierung
   stützen. Das ist eine externe Prüfung, keine automatische Eigenschaft des
   Adapters. Gleiche Snapshots oder Journalgenerationen allein genügen nicht.
3. **Messquelle und Betrieb getrennt prüfen.** Einheiten, echte Quellberichte,
   Frische, Reset-/Recoverygrenzen und gegebenenfalls Integrationsverhalten für
   genau die beanspruchten Intervalle prüfen. Referenzvergleiche müssen dieselbe
   Messgrenze betreffen. Summenkonsistenz ersetzt keine Prüfung einzelner Stufen;
   ein Abgleich von Eingangsleistung und Ausgangsenergie liefert ohne weitere
   Annahmen keine Fehlergrenze. Betreiberangaben bleiben erkennbare Annahmen.
4. **Nur belegte Supports binden.** Eine Stundenfreigabe muss auch die vollständigen
   Originaldeltas vor und nach ihrer Stundengrenze einschließen. Überlappende
   Supports benachbarter Stunden dürfen nur bei gleicher Quelle, Generation,
   Kontinuität, Konfiguration, Software und passender Qualifikation vereinigt
   werden. Lücken dürfen dabei nicht überbrückt werden. Eine bestandene
   Einzelstunde qualifiziert weder den ganzen Tag noch künftige Stunden.
5. **Neue Revision zeitlich ehrlich auswerten.** Facetten erhalten ihren echten
   Prüfzeitpunkt; `as_of` muss die verwendeten späteren Nachweise einschließen.
   Die erzeugte Maske wird erst mit ihrem neuen `validated_at` verfügbar.
   Kontrollieren, dass eine Auswertung zum ursprünglichen Capturezeitpunkt
   weiterhin keine nachträglich freigegebenen Labels erhält.

Als zusätzlicher Konsistenzcheck lässt sich die Recorder-Stundenenergie mit
zwei Grenzen vergleichen: der Summe aller vollständig enthaltenen nichtnegativen
Originaldeltas und der Summe aller die Stunde berührenden Originaldeltas. Dabei
wird kein Delta aufgeteilt. Ein Wert innerhalb dieser Grenzen widerspricht
der Zählerfolge nicht; das ist noch kein unabhängiger Genauigkeitsnachweis.

Prüfergebnis und Masken sollten die übernommenen Betriebsannahmen sowie die
weiterhin ausgeschlossenen Stunden nennen. Technisch geeignete Messwerte sind
keine Kalibrierbescheinigung und ergeben allein noch keine vollständigen
gepaarten Tage für einen Prognosevergleich.

## 3. Lokalen Prüflauf ausführen

Eingaben sind Arrays vollständiger nativer Envelopes mit zusätzlichem `source`,
einschließlich der referenzierten Konfigurations-Forecasts und nötiger
Payload-Chunks. Historische Konfigurations-/Producerwechsel und widersprechende
Ereignisse dürfen bei der Auswahl nicht weggelassen werden. Ein solcher Auszug
ist keine Vollarchivprüfung. Die CLI öffnet keinen Archivindex, stellt keine
Netzverbindung her und erzeugt keine automatische Quellenattestierung.

```bash
.venv/bin/python scripts/qualify_actuals.py \
    --events-json data/quality-input/events-roof.json \
    --bindings data/quality-input/bindings.json \
    --actual-capture data/quality-input/actual-capture.json \
    --as-of 2026-06-02T01:00:00+00:00 \
    --output artifacts/quality-check/report.json \
    --quality-output artifacts/quality-check/quality.json \
    --normalized-output artifacts/quality-check/derived-capture.json
```

`--events-json` ist wiederholbar. Je Eingabe gelten 128 MiB, zusammen 512 MiB
und maximal 500.000 Ereignisse. Die Zielstunden und Zählerzuordnungen kommen aus
dem originalen `ha_actuals`-Capture. Eingaben, Ausgabeziele, Symlink-/Hardlink-Aliase
und ineinander verschachtelte Ausgabeziele werden vor Veröffentlichung geprüft.
Dateien werden einzeln atomar geschrieben; die drei Ausgaben bilden keine
gemeinsame Transaktion. Bericht und Inhalts-Hashes erlauben deren Abgleich.

Der ursprüngliche Rohdatenempfang bleibt erhalten. `as_of` begrenzt die verfügbare
Evidenz, während die neue Qualitätsmaske den echten Ausführungszeitpunkt als
`validated_at` erhält. Eine spätere Offlineprüfung erzeugt keine rückwirkend
damals bekannten Labels. Bereits vorhandene explizite negative/unbestätigte
Qualitätsmasken werden nicht automatisch durch ältere positive Messintervalle
überschrieben: Solche Eingaben benötigen zuerst eine gesonderte Klärung.
Vorhandene Normalisierungen werden gegen ihre ursprüngliche Ableitung geprüft.

## 4. Ergebnis lesen und später anbinden

`summary` enthält je Stufe `total_hours`, `covered_hours`, `qualified_hours`,
`invalidated_hours` und Ablehnungsgründe. `covered_hours` zählt die zeitliche Vereinigung
der gelieferten positiven Intervalle; das ist allein noch keine Freigabe bei
Konflikten oder ungeprüfter Quelle. `hours` enthält Zeitgrenzen, Bindung,
Abdeckungssekunden, Gründe und Originalereignis-IDs. Der Bericht bindet außerdem
Eingabebytes, Quellenattestierungen und die verwendeten Programmdateien per Hash.

`normalization_comparison` zeigt die Recorderannahme ohne Maske und mit der neu
abgeleiteten Maske. Rohdatenfehler können auch bei vollständig belegter Qualität
weiterhin Stunden ausschließen. `quality.intervals` enthält freigegebene ganze
Stunden sowie ausdrücklich negative Masken bei belegten Widersprüchen. Letztere
verlangen eine bestätigte und verfügbare Konfigurations-/Quellenzuordnung; ein
ungeprüfter Vorschlag darf auch keine andere Stundenfreigabe widerrufen.
Überlappungskonflikte, Phasenwechsel, widersprechende Generationen oder
Konfigurationen erhalten `quality: invalid` mit unbestätigten Detailflags.
Der vorhandene Captureauswerter sperrt dadurch auch ältere positive Revisionen
und fordert deren explizite Klärung. Reine Datenlücken oder fehlende
Attestierungen werden ausgelassen und widerrufen keine frühere belegte Freigabe.
`hours.mask_status` unterscheidet `valid`, `invalid` und `omitted`.
Eine leere Liste ist ein gültiges Prüfergebnis; `validated: true` bestätigt dann
nur die Durchführung der Ableitung.

Nach belegter Quellenqualifikation und geprüftem lokalen Ergebnis kann die
Maskendatei über das vorhandene `--quality` beziehungsweise den Hostschlüssel
`quality` angebunden werden. Zuvor müssen Aktualisierung, Aufnahmezeitplan und
Konfigurationswechsel für den jeweiligen Host festgelegt sein. Eine statische
Maske qualifiziert keine neuen Stunden. Diese automatische Betriebsanbindung
und produktive Aktivierung sind eigene Schritte; der Offlineadapter verändert
weder Timer noch deren Konfiguration.
