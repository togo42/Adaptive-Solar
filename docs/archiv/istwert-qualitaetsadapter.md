# Istwerte offline aus archivierten Messnachweisen qualifizieren

Stand: 30.10.2026, enthalten ab Release 0.2.20; eine Timeraktivierung erfolgt
separat und ausdrücklich. Der Adapter liest lokale
Originalauszüge, prüft Stundenabdeckung und erzeugt eine neue Qualitätsrevision
für den bestehenden [Recorder-Collector](../entwicklung/benchmark-aufnahme.md).
Er verändert weder HA noch Originalarchive und bescheinigt keine Prognosegüte.

Beide Qualitätsadapter verwenden `scripts/actual_quality_io.py` für begrenztes
JSON-Lesen mit Originalbytehash und die Prüfung bereits vorhandener
Qualitätsmasken beziehungsweise Normalisierungen. `continuous_quality.py`
benötigt damit keinen Import der anderen CLI. Qualifikationsregeln und
Quellenprüfung bleiben in `core/actual_quality.py`, die sichere Veröffentlichung
in `scripts/replay_paths.py`. Die gemeinsame Hilfe behält die bisherigen Grenzen
von 128 MiB pro Eingabedatei und 512 MiB insgesamt sowie die Sperre vorhandener
negativer oder widersprüchlicher Qualitätsnachweise bei. Ihr Quellhash steht im
Offlinebericht als `adapter_io_source_sha256` und im kontinuierlichen Bericht
unter `implementation_sha256.actual_quality_io.py`; auch diese Datei ist als
Ausgabeziel gegen direkte Pfade und Aliase geschützt.

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

Die bis Release 0.2.19 exportierten `qualified_interval` enthalten weder
Konfigurations-/Softwarehash noch Energie-Entity. Release 0.2.20
ergänzt diese Angaben direkt am Originaldelta (Abschnitt 5). Die Journalgeneration kann einen Reload überleben.
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
aber nicht die genannten Belege. Bei Altintervallen umfasst `configuration` ausdrücklich auch
die Producerkontinuität: Diese Intervallereignisse tragen dessen Hash nicht selbst.
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
Bindungen desselben Scopes dürfen sich zeitlich nicht überlappen. Im v1-Vertrag müssen sie
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
Maske qualifiziert keine neuen Stunden. Die optionale fortlaufende Ableitung
beschreibt Abschnitt 5; ihre produktive Aktivierung bleibt ein eigener Schritt.
Der Offlineadapter verändert weder Timer noch deren Konfiguration.


## 5. Fortlaufende Quellenbindung und Qualitätsaufnahme

Release 0.2.20 ergänzt jedes exportierte Originaldelta um
`source_binding` mit `schema: 1`, `energy_entity_id`, `config_sha256` und
`producer_sha256`. Die Hashes beziehen sich wie beim Anker auf kanonisches
`site`-JSON und den Python-Quellumfang der Integration. Die Softwareprovenienz
wird im Executor ermittelt und für die Coordinatorlaufzeit beibehalten.
Softwarewechsel benötigen einen regulären Reload/Neustart; ein Austausch von
Dateien unter einem laufenden Coordinator ist kein unterstützter Nachweis.
Die Bindung ergänzt nur das Archivereignis, keine Lernintervalle oder Gates.
Der spätere Rohbericht-Fix friert `state_changed` separat an `last_updated` ein;
`state_reported` behält seinen Ereigniszeitpunkt. Er korrigiert neue Exporte,
keine alten Originale. Historische Rohbericht-Replays müssen daher auch den
Producerstand und mögliche Berichtsbursts berücksichtigen. Der Energiepfad
verwendete bereits seine gesondert eingefrorenen Berichtszeiten.

Für fortlaufende Aufnahmen gibt es den ausdrücklich optierten Vertrag
`adaptive-solar-actual-quality-bindings-v2`. Er hat dieselben Felder wie v1,
erlaubt jedoch ein zukünftiges `valid_to`. `configuration.verified` bestätigt
hier eine **bedingte Freigabe der exakt gepinnten Quelle**, keine Kenntnis
zukünftiger Messungen. Die [synthetische Vorlage](../../examples/actual-quality-bindings-v2.json)
enthält ausschließlich Platzhalter und ungeprüfte Facetten. Alle drei Facetten
benötigen weiterhin echte Prüfzeiten
und Evidenzverweise. Messquelle und Betriebsannahmen müssen für den ausdrücklich
begrenzten Zeitraum qualifiziert sein. Es gibt keine automatische Verlängerung,
Übernahme neuer Softwarehashes oder Neuerstellung bestätigter Facetten.

Zusätzlich zu allen v1-Prüfungen muss jedes verwendete Originaldelta seine
passenden Pins tragen. Fehlende Pins liefern keine Freigabe; widersprechende
Pins erzeugen bei bestätigter Konfigurationszuordnung negative Stundenmasken.
Auch v1 wertet vorhandene widersprechende Pins aus. Generation, Kontinuität,
Randabdeckung und vollständige Originaldeltas bleiben erforderlich. Ein
beobachteter Konfigurations-/Producerwechsel sperrt vorsichtshalber die gesamte
betroffene Bindungsperiode. Danach Perioden anhand belegter Grenzen aufteilen
und die neue Quelle gesondert qualifizieren. Eine aktuelle Installation von
0.2.18 kann durch v2 allein noch keine Stunden freigeben: ihren Originaldeltas
fehlen die neuen Pins. Historische v1-Nachqualifikation bleibt getrennt möglich.

`scripts/archive_observations.py --quality-bindings data/quality/policy.json`
leitet nach jedem Recorder-Abruf eine neue Qualitätsrevision aus dem lokalen
Originalarchiv ab. Der Hostschlüssel dafür heißt `quality_bindings`; er verlangt
`actual_config` und schließt `quality` aus. Die HA-Collectorquellen müssen zuvor
die nötigen Originalintervalle und Anker eingesammelt haben. Der vorhandene
Writerlock umfasst Aufnahme und Ableitung. HA wird dabei nur gelesen.

Die Auswahl umfasst alle aufbewahrten Originalintervalle der gebundenen Quellen,
die Zielstunden berühren, sowie Anker und alle Konfigurationsaufnahmen in den
Bindungsperioden. Andere Generationen werden als Widersprüche mitgeprüft.
Payload-Chunks werden quellen-/generationsgebunden aufgelöst. Die Auswahl ist
auf 500.000 Ereignisse und 512 MiB kanonische Ereignisbytes begrenzt; ein
fehlender Anker oder überschrittenes Budget erzeugt keine Ersatzfreigabe.
Sehr lange Policies können vor Ablauf am Budget oder an der Retention scheitern;
Perioden und Ankererhalt gehören zur Betriebsplanung. Die Auswahl scannt
die aufbewahrten Batches der gebundenen Quellen; ihre Laufzeit muss im
Host-Probelauf am tatsächlichen Archivvolumen gemessen werden.

Der archivierte Capture enthält die unveränderten Recorder-Rohdaten und deren
ursprüngliche Empfangszeit, eine neue Normalisierung und `quality_derivation`
mit Policykopie, Eingabe-/Programmhashes, Stundendiagnosen und Evidenzreferenzen.
`validated_at` wird erst nach abgeschlossener Stundenprüfung, Evidenzsortierung
und Hashberechnung erfasst. Beide Helfer übernehmen diese Abschlusszeit auch
für Normalisierung und Labelverfügbarkeit; ein Cutoff während der Berechnung
erhält die neuen Labels noch nicht. Eine rückwärts springende Uhr bricht die
Ableitung ab. Vor diesem Zeitpunkt bleiben
die neuen Labels für historische Auswertungen unsichtbar. Ein Bericht oberhalb der 32-MiB-Grenze für Beobachtungscaptures wird ebenfalls
als Ableitungsfehler behandelt. Eine fehlgeschlagene
Ableitung wird als fehlerhafter Job gemeldet, der Rohcapture dennoch bewahrt.
Eine erfolgreiche Aufnahme mit null freigegebenen Stunden bleibt als solche
sichtbar (`quality_summary` zählt Abdeckung, Freigaben und Invalidierungen).
Bestehende negative Masken werden auch beim lokalen Probelauf nicht freigegeben.

### Lokalen Probelauf vorbereiten und abnehmen

1. Den Kandidatenstand samt Abhängigkeiten einfrieren und die später eingesetzte
   HA-Version mit diesem Producerhash abgleichen. Keine bestehenden Timer auf
   die neue Policy umstellen, bevor diese Quelle Originaldeltas mit Pins liefert.
2. Eine private v2-Policy mit exakter 1:1-Messgrenze, Quelle, Generation,
   archiviertem Konfigurationsanker, Pins und begrenztem Zeitraum erstellen.
   Ungeprüfte Facetten bleiben `verified: false`; ihr Lauf dient der Diagnose.
3. Mit einer eingefrorenen lokalen Archivkopie und unverändertem Recorder-Capture
   prüfen. Während des lokalen Laufs dürfen Collector/Retention diese Kopie
   nicht verändern; der spätere Hostjob verwendet dafür den gemeinsamen Writerlock:

```bash
.venv/bin/python scripts/continuous_quality.py \
    --archive data/archive \
    --bindings data/quality/policy.json \
    --actual-capture data/quality/raw-capture.json \
    --output data/quality/rehearsal-derived.json
```

Dieser Befehl stellt keine Netzwerkverbindung her und ändert keine Originale.
Die Ausgabe ist ein separat auswertbarer Capture einschließlich Prüfbericht;
Ausgabealias auf Eingaben, den Helfer selbst oder die verwendeten
Implementierungsdateien sowie ein Ziel innerhalb des Originalarchivs ist gesperrt.
Die gemeinsame Ausgabeprüfung hält Berichte außerdem aus `scripts/` und
`custom_components/` fern und schützt deren Quell-/Ressourcendateien gegen Aliase. Gleiche Pfade und
Symlink-/Hardlink-Aliase werden vor der Ableitung und erneut
vor der Veröffentlichung geprüft.
Erfolg des Befehls bestätigt die Durchführung, auch bei null freigegebenen Stunden.

4. `quality_derivation.summary`, Ausschlussgründe, Rohdatenhash und echte
   Qualitätszeit prüfen. Positive Stunden benötigen vollständige Originaldeltas;
   Lücken, alte Producer und abgelaufene Supports bleiben ausgeschlossen.
   Die Auswertung vor `validated_at` muss die neuen Labels weiterhin auslassen.
5. Erst für einen gesondert autorisierten Host-Probelauf den bestehenden
   Beobachtungsjob mit `quality_bindings` konfigurieren. Vorher Konfiguration
   sichern; HA-Collector zuerst lesen lassen, danach einen einzelnen
   Beobachtungslauf ausführen und archivierte Captures sowie privaten Hoststatus
   zurücklesen. Anschließend erst über die reguläre Taktung entscheiden.
   Rücknahme: vorherige Hostkonfiguration wiederherstellen; neue Capture- und
   Qualitätsrevisionen als historische Evidenz erhalten. Explizite negative
   Revisionen benötigen fachliche Klärung, kein Löschen zur Ergebnisverbesserung.

Dieser Arbeitsstand installiert oder aktiviert weder HA noch Hostdienste.
Ein lokaler synthetischer Probelauf belegt die Verkabelung, keine physische
Messgüte, produktive Stabilität oder Prognoseüberlegenheit.
