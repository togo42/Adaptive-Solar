# Messintervalle: 92 Prozent Abdeckung und drei Minuten Randlücke

Stand: 27.10.2026. Mit Version 0.2.13 veröffentlichter Nachtrag zum bisherigen
Release 0.2.12. Veröffentlichung und HA-Rollout sind separat nachgewiesen.
Der aktuelle [Prüf-/Reviewstand](entwicklungsstand.md) ist separat gebunden.
Die Änderungen betreffen die Messaufbereitung und Lernlabelauswahl, nicht die
Wetter-/PV-Baselines oder die Annahmekriterien des externen Prognosevergleichs.

Dieser Text beschreibt den **historischen Vertrag von 0.2.13**. Der
[aktuelle Implementierungsnachtrag](measurement-learning.md) erhält dessen
Abdeckungs-/Randgrenzen und erweitert ihn um belegte Kontinuität mit begrenzten
Zeitstempellücken, separate 15-Minuten-Wartezeit und echte Endpunktfenster.
Insbesondere ist die unten beschriebene 60-Sekunden-Wartefrist historisch.

## 1. Abdeckungsregeln

Ein ursprüngliches Prognoseziel muss mindestens 30 Minuten dauern. Daraus wird
der längste zusammenhängende, vollständig gemessene Block gewählt. Er braucht
mindestens **92 % der ursprünglichen Zieldauer**. Vor und nach ihm dürfen jeweils
höchstens **180 Sekunden** fehlen. Beide Bedingungen gelten gleichzeitig:

| Ursprüngliches Ziel | Kürzester zulässiger Messblock | Zusätzliche Randbedingung |
| --- | --- | --- |
| 30 Minuten | 27 Minuten 36 Sekunden | Je Rand höchstens 3 Minuten; insgesamt wegen 92 % höchstens 2 Minuten 24 Sekunden fehlend |
| 60 Minuten | 55 Minuten 12 Sekunden | Je Rand höchstens 3 Minuten; insgesamt höchstens 4 Minuten 48 Sekunden fehlend |
| 180 Minuten | 174 Minuten | Die beiden festen Randgrenzen erlauben zusammen höchstens 6 Minuten Verlust; 92 % allein würden mehr erlauben |

Leistung des Lernlabels ist gemessene Energie geteilt durch die tatsächliche
Messdauer. Fehlende Randenergie wird nicht ergänzt. Messstücke, die eine
Zielgrenze überschreiten, werden nicht aufgeteilt; getrennte Blöcke werden nicht
über eine interne Lücke hinweg addiert.

Die Auswahl hängt von Dauer und bei Gleichstand vom früheren Start ab, nicht
von Ertragswerten oder Modellfehlern. Ein früher kurzer Block kann einen späteren
59-Minuten-Block deshalb nicht mehr verdecken. Exakte Messduplikate zählen einmal;
widersprüchliche oder überlappende Messungen sperren das Ziel. Verspätete Labels
werden vor Auswahl und Duplikatprüfung ausgeschlossen. Bei gesetztem `as_of`
muss auch das ursprüngliche Ziel bereits beendet sein.

`ResidualLearner` prüft dieselben Grenzen noch einmal. Neue Samples tragen
`measurement_edge_seconds` sowie weiterhin die relative
`measurement_edge_fraction`. Alte Samples ohne Sekundenfeld werden aus ihrer
Randfraktion und ursprünglichen Zieldauer geprüft. Mindesthistorie,
chronologische Aufteilung, Lead-Gates und MAE-/Gewinntagsanforderungen ändern
sich nicht.

## 2. Kurze Zählerschritte und Plausibilität

Zählerrundung und eng aufeinanderfolgende HA-Berichte können rechnerisch eine
zu hohe Leistung aus einem sehr kleinen Delta ergeben. Bei einem solchen
positiven Delta behält der Tracker den letzten angenommenen Anker vorläufig,
statt sofort eine Lücke zu erzeugen. Dafür gelten zwei feste Grenzen:

- Vom Anker bis zum endgültigen Originalbericht höchstens **60 Sekunden**.
- Zurückgehaltene Energie höchstens das in 60 Sekunden bei deklarierter
  Ausgangsgrenze plus bisheriger 10-%-Toleranz mögliche Energiequantum.

Erst ein weiterer echter, strikt neuerer Zählerbericht kann den vollständigen
Deltaabschnitt freigeben, wenn dessen mittlere Leistung plausibel ist. Energie
wird weder gekappt noch rückwirkend in bereits angenommene Intervalle verteilt.
Die Verfügbarkeit des Labels ist die echte Empfangszeit des abschließenden
Berichts. Ein Forecastrefresh oder Timer erzeugt keinen Zählerbericht.

Große Sprünge werden sofort abgewiesen. Bleibt die mittlere Leistung überhöht,
wird das Delta spätestens am 60-Sekunden-Endpunkt abgewiesen. Kommt der nächste
Bericht erst danach, gibt es ebenfalls kein Label für den zurückgehaltenen
Abschnitt; dieser Bericht ankert neu. Resets werden gegen den neuesten echten
Bericht einschließlich zurückgehaltener Werte geprüft. Ungültige Quelle,
Abregelung, Wiederfreigabe und Neustart dürfen keine Brücke über den Abschnitt
bilden. Die allgemeine maximale Zählerdifferenzdauer bleibt 15 Minuten.

Das ist eine begrenzte Behandlung quantisierter Berichte, keine physikalische
Zertifizierung des Zählers. Ein kleiner realer Zählersprung ist nicht allein
anhand zweier HA-Empfangszeiten von einer Rundungsstufe unterscheidbar.

## 3. Diagnose, Historie und Nachweis

`training_quality.policy` nennt `min_coverage_fraction=0.92`,
`max_missing_edge_seconds=180` und `counter_plausibility_window_seconds=60`.
Die bisherige globale Randfraktion entfällt als Policywert, weil die Grenze nun
absolut ist. `training_quality.meter.pending_counter_aggregation` zeigt einen
vorläufig zurückgehaltenen Abschnitt. Ereigniszähler unterscheiden
`deferred_power_check`, `accepted_deferred_delta`, `counter_aggregation_timeout`
und weiterhin endgültiges `power_above_output_cap`.

Archivfeatures, unabhängig gültige Messintervalle und Tagesbeginn-Snapshots
werden nicht pauschal verworfen. Passende vorhandene Messblöcke können unter der
neuen Auswahl-/Abdeckungspolitik neu verbunden werden. Früher verworfene
Zählerenergie wird aus bestehenden Stores nicht erfunden oder nacherfasst.
Anker und zurückgehaltene Berichte sind ausschließlich flüchtig.

Verhaltenstests stehen in `tests/test_measurement_windows.py`, ergänzt durch
bestehende HA-, Messgültigkeits-, Persistenz- und Alignmenttests. Sie prüfen
synthetische Rundungsbursts, echte HA-Ereignisse, Resets/Abregelung, beide
Zeitumstellungen, neue Grenzwerte, As-of-Verfügbarkeit und unveränderte Energie.
Mehr akzeptierte Labels allein beweisen keine bessere Prognose.
