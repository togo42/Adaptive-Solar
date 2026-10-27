# Optionale Messquellen-Gültigkeit

Jede AC- oder DC-Ausgabestufe kann optional einen `measurement_valid_entity_id`
aus der Domain `binary_sensor` erhalten. Nur `on` bedeutet, dass die externe
Messquelle für neue Originalberichte freigegeben ist. `off`, `unknown`,
`unavailable`, ein fehlender Sensor und ein als wiederhergestellt markierter
Zustand sperren die Messungen. Ohne diesen Eingang bleiben bisheriges Verhalten,
AC-/DC-JSON und Historyfingerprints unverändert. Das neue Feld steht nach allen
bisherigen Positionsargumenten; die native ConfigFlow-Version bleibt 1.

Der Eingang ist von `curtailed_entity_id` unabhängig. Gültigkeit und Abregelung
dürfen an derselben Stufe nicht denselben Sensor verwenden: `on` hätte
widersprüchliche Bedeutungen. Mehrere Stufen dürfen einen gemeinsam qualifizierten
Gültigkeitseingang verwenden. Der Prognosekern benötigt keine Hersteller-,
Transport-, Batterie-, SoC- oder Exportdaten.

## Messgrenzen und Wiederanlauf

Ein ungültiger Gültigkeitsbericht entfernt den Energieanker sofort und verriegelt
die laufende Differenzbildung. Ein späteres `on` hebt diese Verriegelung nicht
rückwirkend auf. Erst ein echter Original-Energiebericht mit einer Berichtszeit
streng nach Beginn der neuen gültigen Phase setzt einen neuen Anker; erst der
folgende Bericht kann wieder eine Differenz ergeben. Frühere valide Intervalle
bleiben erhalten. Weder eine aktuelle Zustandsabfrage noch ein veränderter
Attributwert ersetzt einen Energiebericht. Echte unveränderte
`state_reported`-Berichte und echte Null-Differenzen bleiben zulässig.

Beim Start werden keine Anker aus dem Store übernommen. Auch ein bereits
vorhandenes `on` zertifiziert keine Zeit vor dem Start der Überwachung. Der erste
Forecast erfolgt bisher vor dem Trackingstart; mit konfiguriertem Eingang
verwendet er deshalb keine gecachte Leistungsbeobachtung. Nach dem Start und
jeder Wiederfreigabe ist auch für Power-Nowcast ein echter, streng neuerer
Leistungsbericht erforderlich. Wiederholtes `on` ohne ungültige Zwischenphase
beginnt keine neue gültige Phase. Ungültige Zwischenereignisse bleiben auch bei
rasch aufeinanderfolgenden `off`/Energie/`on`-Ereignissen wirksam.

Der konfigurierte Gültigkeitseingang gehört zur physischen Messprovenienz im
Historyfingerprint. Hinzufügen, Entfernen oder Wechseln beginnt eine neue
Historie; alte Labels werden dieser neuen Quelle nicht zugeschrieben. Die
allgemeinen Abdeckungs-, Rand-, Mindestdauer-, Reset- und Gap-Gates bleiben bestehen.

## Vertrag des externen Qualitätsadapters

`on` muss die Frische **aller** erforderlichen Originalquellen und eine gesicherte
Berichtsfolge bestätigen. Der Kern kennt die Entstehung eines beliebigen
HA-Zählerzustands nicht. Bei gepufferten oder nachträglich korrigierenden Quellen
muss deshalb vor `on` die Resynchronisierung abgeschlossen sein. Eine frische
Summenmeldung beweist nicht die Frische ihrer Teilquellen.

Für den nativ geprüften HA-Integralpfad (`left`, maximal fünf Minuten) ohne
zusätzliche Zählerpolls ist keine pauschale weitere Fünf-Minuten-Wartezeit nötig:
Der erste tatsächlich berechnete Zählerbericht nach `on` kann noch Energie aus der
ungültigen Phase enthalten und wird nur zum Ankern verwendet. Erst der folgende
Bericht ergibt die neue Differenz. Echte unveränderte Nullberichte bleiben dabei
erhalten. Die Prüfung verwendet den echten HA-Integrator und einen separaten
triggerbasierten Gültigkeitssensor mit Zehn-Sekunden-Altersprüfung; der dortige
30-Sekunden-Frischewert ist ein synthetischer Testparameter.

Ein separat nativ reproduzierter Gegenfall setzt diesem Nachweis eine konkrete
Grenze: `homeassistant.update_entity` am Integral zwischen `on` und dem noch
ausstehenden Integralflush kann einen gehaltenen Zählerstand mit neuem
HA-Berichtszeitpunkt ausgeben. Ein solcher Bericht beweist keine neue Berechnung;
der spätere Flush kann dann alte Energie in eine neue Differenz tragen. Der
geprüfte Adapterpfad schließt diese zusätzlichen Polls, Gegenwertschreibungen und
Wiederveröffentlichungen aus. Bei unbekannter Berichtsfolge ist ein abgesicherter
externer Resync nötig. Der Kern behauptet keine physische Qualifikation allein
aufgrund eines HA-Berichtszeitpunkts.

Ein Qualitätstimer prüft Original-Berichtszeiten und meldet ausschließlich den
Gültigkeitszustand. Er aktualisiert oder ersetzt keinen Energiezähler. Der
Originalzähler bleibt direkt gebunden. Der konkrete Adapter benötigt eigene
Ereignis- und Recoverytests. Die native Testmatrix einschließlich des ausdrücklich
ausgewiesenen Gegenfalls steht in
`tests/test_integrated_source_validity.py`; produktive Eingriffe oder
Ausfallversuche werden daraus nicht abgeleitet.

## Messdaten-Nachtrag vom 27.10.2026

Im lokalen, noch nicht veröffentlichten [Nachtrag](messintervalle-92-prozent.md)
gelten 92 % Messabdeckung und höchstens drei Minuten Randlücke je Seite.
Ein zurückgehaltenes kurzes Zählerdelta wird bei ungültiger Messquelle oder
Abregelung verworfen. Nach Wiederfreigabe ankert weiterhin erst ein echter
neuer Originalbericht; der bisherige Abschnitt wird nicht nachträglich gültig.

## Diagnose und Prognose

`inputs.measurement_valid_<Stufe>` meldet `valid`, `invalid` oder `unknown` für
konfigurierte Eingänge. Powerdiagnosen unterscheiden eine ungültige/nicht
überwachte Quelle von einem vor der Wiederfreigabe erhaltenen Bericht.
`learning.<Stufe>.training_quality.meter` enthält die aktuelle externe Gültigkeit,
die konfigurierte Quelle und den Status des Energieeingangs. Diese Werte sind
aktuelle Eingangszustände, keine nachträgliche Bestätigung eines ganzen Intervalls.
Ungültige konfigurierte Messquellen führen bei sonst vollständiger Ausgabe zu
`degraded`, getrennt von betrieblicher Abregelung.

Die physikalische Prognose des verfügbaren PV-Potenzials und gültige Umweltwerte
bleiben erhalten. Die nächste Prognoseausgabe verwendet keine durch den Eingang
gesperrte Leistungsbeobachtung. Bereits ausgegebene Prognosen behalten ihren
tatsächlichen Ausgabezeitpunkt; es wird keine rückdatierte Ersatzprognose erzeugt.
