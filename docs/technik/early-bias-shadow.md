# Früher Bias-Kandidat im Shadow-Betrieb

Der zusätzliche `EarlyBiasShadow` prüft einen kleinen, stark regularisierten
multiplikativen Bias-Kandidaten. Er verändert keine veröffentlichten Leistungen,
Energien, Unsicherheitsgrenzen, Qualitätszustände oder das bestehende Residualmodell.
Seine eigenen Kandidatenpunkte werden getrennt bereitgestellt. Eine erfolgreiche
interne Prüfung erlaubt ausschließlich deren prospektive Beobachtung.

## Eigene Daten- und Zeitgates

Jede Ausgangsstufe, jedes GHI-/NWP-Regime und jeder Lead-Bin benötigt unabhängig
mindestens 14 Zieltage und 48 eindeutige gemessene Stunden. Doppelte Origins
vervielfachen diese Stunden nicht. Die ursprünglichen Prospektivitäts-,
Messabdeckungs-, Schattenphasen-, Werte- und Empfangszeitgates gelten weiter;
Zielintervalle mit widersprüchlichen Labels werden ausgeschlossen.
Niedrige Baselines unter fünf Prozent der deklarierten Ausgangsgrenze trainieren
keinen instabilen Quotienten.

Die letzten mindestens drei Zieltage (bei größeren Datenmengen ein abgerundetes
Fünftel der Tage) bilden den Holdout. Er benötigt mindestens zwölf eindeutige
Messstunden. Der Trainingsblock benötigt mindestens sieben Tage und 24 Stunden;
seine Labels müssen bereits bei der frühesten Ausgabe des Holdouts verfügbar
gewesen sein. Training endet vor dessen erstem Zielintervall. Beide Blöcke
müssen dieselben Sonnenstands-/Schattenphasen unterstützen und nach dem Abgleich
mindestens ihre eigenen Tage/Stunden erreichen. Der unterstützte Leadbereich ist
die Schnittmenge der Bereiche beider Blöcke.

## Niedrige Modellkapazität

Pro Trainingszieltag wird ein mit eindeutiger Messdauer gewichteter Quotient
zwischen Messung und Baseline berechnet. Der Median dieser Tagesquotienten wird
auf 0,8 bis 1,2 begrenzt und zusätzlich mit sieben neutralen Prior-Tagen gegen
eins geschrumpft. Die Holdout-Labels beeinflussen diesen Gain nicht.

Der unveränderte Kandidat muss im Holdout mehr als fünf Prozent weniger
gewichteten absoluten Leistungsfehler als Physik und mindestens 60 Prozent
gewonnene Zieltage erreichen. Er erhält dann `shadow_ready`; einzelne unterstützte
Vorhersagen melden `shadow_bias_candidate`. Außerhalb des geprüften Regimes,
Leadbereichs oder der Schattenphase entstehen keine Kandidatenpunkte.
Die deklarierte Ausgangsgrenze bleibt eine harte Obergrenze. Es gibt keine
behaupteten kalibrierten Unsicherheitsbänder.

## HA-Einbindung und Grenzen

Der Koordinator verwendet denselben bereits berechneten Trainingsjoin.
Ein neuer Shadow-Fit wird nur für veränderte tatsächliche Samples gerechnet;
ein Fehler verwirft den alten Shadow und erlaubt beim nächsten Lauf einen Retry.
Kandidat, Fit-Signatur, Diagnose und getrennte Punkte werden erst nach erfolgreicher
verpflichtender Prognose gemeinsam übernommen. Ein Shadow-Fehler lässt deren
Ausgabe unverändert.

Die HA-Diagnosen enthalten `bias_shadow` mit `operational_use: false`, dem
ursprünglichen `fit_evaluated_at`, Modell-
und Holdoutstatus und einem gegebenenfalls aufgetretenen Fehlertyp. Der interne
Puffer `_shadow_archive_pending` enthält nur tatsächlich freigegebene
Kandidatenpunkte und wird bei jedem erfolgreichen Lauf ersetzt. Er ist keine
zusätzliche veröffentlichte Prognosekurve. Eine getrennte prospektive Archivierung
kann diese Punkte mit Ausgabezeit und Modellpolicy binden.

Die Mindesthistorie ist eine feste lokale Shadow-Policy. Sie senkt keine
Aktivierungsgates des produktiven Residualmodells. Synthetische Tests,
`shadow_ready` und ein archivierter Kandidat beweisen weder reale Überlegenheit
noch robuste Saisongüte. Dafür sind qualifizierte prospektive Messungen und die
separaten Benchmarkgates erforderlich.
