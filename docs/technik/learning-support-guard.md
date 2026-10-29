# Trainingsabdeckung des Residual-Lerners offline prüfen

Stand: 29.10.2026, Entwicklungskandidat; keine produktive Aktivierung und kein
Bestandteil des unveränderten Release-Tags 0.2.18.

## Zweck und Grenze

Der bisherige Residual-Lerner prüft Eingabegültigkeit, NWP-/GHI-Regime,
validierten Vorlauf und Schattenkompatibilität. Er prüft nicht allgemein, ob
eine neue Merkmalslage durch seine Trainingsdaten gestützt ist. Der zusätzliche
`SupportGuardLearner` untersucht diese Grenze als separater Offline-Kandidat.

Die HA-Integration verwendet weiterhin `ResidualLearner`. Weder veröffentlichte
Prognosen noch Historiengates, Sensorattribute oder Optionen werden durch das
Vorhandensein des Kandidaten geändert. Es gibt keine automatische Aktivierung,
keinen neuen Dienst und keine zusätzliche Netzwerkabfrage.

Ein Guard erkennt unbekannte Eingaben; er erkennt nicht zuverlässig eine
veränderte Ertragsbeziehung bei identischen Eingaben, etwa nach Reinigung oder
bei Schnee. Physik-Fallback ist eine nachvollziehbare Rückfallebene, kein
Nachweis einer besseren Prognose.

## Datenbestand zuerst beurteilen

Eine aktuelle Bestandsaufnahme liest vorhandene HA-Lerndiagnosen und
Archivnachweise. Je Stufe, Regime und Vorlauf sind mindestens zu unterscheiden:

- tatsächlich aktive Modelle und Freigaben;
- eindeutige gemessene Dauer und Zieltage;
- Training, Validierung und Kalibrierung mit ihren jeweiligen Zeitgrenzen;
- Ausschlussgründe und Messlücken;
- vorhandene Originalwetter-, Prognose-, Fit- und spätere Istnachweise.

Eine gültige Leistungsbeobachtung ersetzt keine zusammenhängende
Energiemessung. Mehrere Prognoseausgaben erzeugen keine zusätzlichen Iststunden.
Erfassungszeit und Quellstand gehören zum Bericht; private Anlagen- und
Hostdetails bleiben unter ignoriertem `data/docs/betrieb/`.

## Kandidat und zeitliche Trennung

`core/learning_support.py` ergänzt die bestehende Fit-/Predict-Schnittstelle.
Ein ausschließlich für Ableitungen vorgesehener Hook im Lerner erhält nach
erfolgreicher Freigabe den tatsächlich verwendeten Trainingsblock. Beim normalen
Lerner ist dieser Hook wirkungslos. Damit benötigt der Kandidat keine zweite,
möglicherweise abweichende Implementierung der Zeit- und Qualitätsgates.

Die Stützung wird getrennt je Stufe, Regime und Lead-Bin aufgebaut. Validierungs-
und Kalibrierungsdaten werden nicht zum Anpassen der Merkmalsgrenzen verwendet.
Die Policy besitzt eine eigene Version und wird mit dem Auswertungsbericht
gebunden. Sie ist eine zu prüfende Modellannahme, keine kalibrierte
Ausreißerwahrscheinlichkeit.

Die anfängliche Policy `residual-training-support-v1` ist ausdrücklich noch nicht
an realer Prognosegüte validiert:

| Bestandteil | Festgelegte Kandidatenregel |
| --- | --- |
| Einzelmerkmale | Dauergewichtete 1.-/99.-Perzentile des Trainingsblocks, erweitert um 10 % ihrer Spannweite oder mindestens den jeweiligen Auflösungsboden |
| Gemeinsame Merkmalslage | Abstand zur nächsten tatsächlich vorhandenen Trainingslage; Maximum der normierten Einzel-/Kreisabstände höchstens 1 |
| Lineare Abstandsskalen | 25 % der Trainingsperzentilspanne, mindestens der Auflösungsboden |
| Azimut | Gemeinsamer Sinus-/Kosinus-Kreisabstand für 20° |
| Saison | Gemeinsamer Sinus-/Kosinus-Kreisabstand für 60 Tage; kein künstlicher Sprung am Jahreswechsel |
| Prototypen | Höchstens 4.096 eindeutige Merkmalsvektoren je Zelle, deterministisch reduziert; eine Reduktion wird ausgewiesen |

Die Auflösungsböden betragen 20 W für Baseline, 2° Sonnenhöhe, 2 °C Temperatur,
0,5 m/s Wind, 5 Prozentpunkte Bewölkung, 0,25 Stunden Vorlauf, 0,05 GHI-Gain und
30 Sekunden GHI-Alter. Der Baselineboden beträgt mindestens 2 % ihres oberen
Trainingsperzentils. Das sind deklarierte Toleranzen dieses Kandidaten, keine
gemessenen Sensorunsicherheiten. Prototypreduktion kann zusätzlichen Fallback
auslösen; ein 1.-/99.-Perzentil bedeutet keine gemeinsame 98-%-Abdeckung.
Die Saisontoleranz berücksichtigt die konstruktive Lücke zum Training:
120 Historientage können 24 Validierungs- und 24 Kalibrierungstage enthalten,
danach folgt noch der Prognosevorlauf. Eine engere rein kalenderbasierte Grenze
könnte deshalb trotz unverändertem Anlagenverhalten sämtliche aktuellen Fälle
ablehnen.

Vor einer zusätzlichen Supportentscheidung gelten sämtliche bisherigen
Physik-Fallbacks. Ein unterstützter Punkt behält die bisherige Vorhersage. Ein
vom Guard abgelehnter Punkt erhält die begrenzte Physikbaseline, einen eigenen
Status und keine übernommenen Fehlergrenzen.

Der Kalibrierradius ist das empirische Quantil des Fehlers **nach** der
ML-Korrektur. Er begrenzt deshalb nicht die Höhe dieser Korrektur. Eine große,
zutreffende Bias-Korrektur darf einen kleinen verbleibenden Fehler haben.

## Offline-Vergleich

`scripts/analyze_learning_support.py` verarbeitet explizit eingefrorene lokale
Eingaben. Die drei Vergleichsarme sind:

| Arm | Bedeutung |
| --- | --- |
| Physikbaseline | Die zur Aufgabe gehörende Baseline vor Residualkorrektur |
| Bisheriger Lerner | Unveränderte Residualentscheidung mit den ursprünglichen Fit-Eingaben |
| Guard-Kandidat | Dieselbe Residualentscheidung mit zusätzlicher Supportprüfung |

Dies ist ein Vergleich der **Residualstufe vor Leistungs-Nowcast**. Die
Physikbaseline kann bereits GHI- und Schattenkorrekturen enthalten. Sie wird
nicht als reine NWP-Prognose bezeichnet; eine rekonstruierte Residualentscheidung
ist auch nicht automatisch die damals veröffentlichte HA-Endprognose.

Fit-Labels müssen am Fit-Cutoff vorliegen. Die geprüften Aufgaben müssen erst
danach ausgegeben worden sein. Spätere Istwerte dürfen die Bewertung, niemals
Fit oder Supportgrenzen beeinflussen. Originalquellstände und die aktuelle
Auswertungssoftware werden getrennt ausgewiesen; numerische Übereinstimmung
ersetzt keinen identischen Original-Replaynachweis.

Die CLI benötigt keine HA-Verbindung und öffnet keinen Archivindex. Sie liest
entweder den eingefrorenen Eingabevertrag oder zuvor exportierte native
Original-Envelopes einschließlich referenzierter Wetter-/Fit-Chunks:

```bash
.venv/bin/python scripts/analyze_learning_support.py \
    --input data/support/frozen-input.json \
    --output data/support/report.json

.venv/bin/python scripts/analyze_learning_support.py \
    --events-json data/support/original-events.json \
    --event-id ORIGINAL_FORECAST_EVENT_ID \
    --as-of 2026-11-02T18:00:00Z \
    --output data/support/native-report.json
```

Zeit und Event-ID durch die tatsächlichen Werte des Exports ersetzen. Mehrere
`--event-id` sind für dieselbe Archivquelle und unveränderte Standortkonfiguration
möglich. Gleiche Konfigurationswerte beweisen keine gemeinsame Quellenidentität.
Ohne Quellnamen dürfen nur Ereignisse derselben Originalgeneration gemeinsam
importiert werden; bekannte und unbekannte Quellen werden nicht vermischt.
Optional ergänzen `--actuals-json` und `--schedule-json` qualifizierte
Istintervalle und den deklarierten Prüfplan. Ohne Istwerte bleibt die Diagnose
ausführbar; Fehlerkennzahlen bleiben unbelegt. Ausgabe- und Eingabepfade müssen
verschieden sein; die CLI schützt auch Symlink-/Hardlink-Aliase und veröffentlicht
den Bericht atomar.

Der eingefrorene JSON-Vertrag trägt
`schema: "adaptive-solar-support-evaluation-v1"` und folgende Felder:

| Feld | Inhalt |
| --- | --- |
| `timezone`, `as_of` | Anlagenzeitzone und tatsächlicher Auswertungs-/Labelverfügbarkeits-Cutoff |
| `fits` | Liste mit `id`, `fit_as_of`, `learner_available`, `output_caps_w` je Stufe und originalen `fit_samples` im `TrainingSample`-Format |
| `tasks` | `fit_id`, `issued_at`, `available_at`, `start`, `end`, `inverter_id`, `baseline_w` und ursprüngliche `features` |
| `actuals` | `start`, `end`, `inverter_id`, `power_w` als Intervallmittel, `observed_at`, `curtailed`, `qualified` und `quality_source` |
| `schedule` | Optional vorab deklarierte `EvaluationWindow`-Liste mit `cutoff`, `start`, `end`, `inverter_id` und optionalem `daylight` |

Alle Zeitstempel benötigen eine Zeitzone. Bei selbst erstellten Eingaben ist
ein fehlendes `available_at` die explizite Annahme, dass die Aufgabe bereits
bei `issued_at` verfügbar war. Der native Import verwendet immer den echten
Archivempfang. Ein nicht verfügbarer Lerner darf keine Fit-Samples oder einen
Fit-Cutoff vortäuschen. Unveränderte Duplikate vermehren keine Aufgaben;
widersprüchliche Aufgaben werden abgewiesen.

Ein expliziter Prüfplan wählt je Cutoff die jüngste verfügbare Ausgabe. Er muss
die unveränderten Zielintervalle verwenden; dieses Werkzeug erfindet keine
Residualmerkmale für zusammengefügte oder geteilte Intervalle. Fehlende
Prognoseaufgaben bleiben im Plan sichtbar. Ohne `schedule` ist der abgeleitete
Plan ausdrücklich nachträglich (`posthoc_task_schedule`), auch wenn vollständige
Tagesfenster rein deskriptiv auswertbar sind.

Der Bericht bindet Eingabedateien, Kandidatenpolicy und Auswertungssoftware per
Hash. Er enthält die bisherigen Fit-/Freigabestatus, die Supportdiagnose sowie
gemeinsam gepaarte Fehler- und Abdeckungskennzahlen. Die Statusfelder
`operational_use: false`, `supports_activation: false` und
`statistical_acceptance: "not_evaluated"` erlauben keine operative Annahme.
Der vorhandene empirische Radius wird auf unterstützten NWP-Punkten beobachtet;
die GHI-Bänder bleiben entsprechend dem bisherigen Enginevertrag entzogen.

`qualified: true` mit `quality_source` in einer Istzeile ist eine explizite
Behauptung des Aufrufers über das gesamte Messintervall. Die CLI qualifiziert
keine physische Quelle durch Setzen dieses Flags. Ein Recorder-Energiedelta
ohne Abdeckungs-, Reset- und Abregelungsnachweis reicht dafür nicht aus.
`observed_at` muss die tatsächliche Verfügbarkeit einschließlich einer späteren
Qualifikation berücksichtigen, also mindestens das Maximum aus Datenempfang,
Intervallende und Qualitätsprüfung. Ein nachträglich geprüfter Messwert wird
nicht auf seine frühere Messzeit zurückdatiert.

Fehlende oder unqualifizierte Istwerte bleiben fehlend. Ohne ausreichende
Istdeckung ist nur eine Supportdiagnose möglich. Tagesenergiemetriken setzen
vollständig gepaarte Tages-/Resttagsfenster voraus; eine Summe beliebiger
vorhandener Tageslichtstunden ist kein vollständiger Tagesertrag. Ohne vorab
deklarierten Prüfplan bleibt auch ein vollständiges Fenster rein nachträglich
deskriptiv und trägt keine Annahmeentscheidung.

## Vorab festgelegte Bewertung und weitere Arbeit

Dieses Arbeitspaket liefert eine ausführbare Kandidatenprüfung und deskriptive
Ergebnisse. Es erteilt keine operative Freigabe. Vor einem prospektiven Versuch
sind Quell-/Policyhash, physische Konfiguration, Ausgabezeiten, Zielintervalle,
Primärmetrik, Prüfperiode und Annahme-/Abbruchregeln einzufrieren.

Support-Ausschlüsse, Fallbackanteil, Fehler und Bias sind je Stufe, Regime und
Vorlauf auszuwerten. Dabei zählen auch die vom Guard verworfenen Aufgaben zum
Vergleich der gesamten Prognosepolitik. Eine bessere Fehlerzahl allein durch
Entfernen schwieriger Fälle ist keine Verbesserung.

Für einen beanspruchten Gütenachweis gilt weiterhin der
[Validierungsplan](../entwicklung/validierung.md). Fünf oder zehn erfolgreiche
Validierungstage begründen keine festgelegte Fehlaktivierungsrate. Wiederholte
Fits und mehrere geprüfte Zellen müssen bei einer späteren statistischen
Entscheidungsregel berücksichtigt werden.

Eine spätere Fehlerüberwachung benötigt qualifizierte abgeschlossene Messungen
und muss Konzeptänderungen von fehlerhaften Quellen und Abregelung trennen.
Automatisches Abschalten nach wenigen schlechten Stunden ist hier nicht
implementiert. Strahlungszerlegung, Ensemblegewichte, Schattenbins und
Nowcast-Unsicherheitsbänder bleiben eigenständige Vergleichsversuche.
