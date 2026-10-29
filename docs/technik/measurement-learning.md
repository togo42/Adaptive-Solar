# Messdaten und Lernfenster aus echten Zählerberichten

Stand: 27.10.2026; Datenvertrag ab Version 0.2.15. Die beschriebenen
Softwareprüfungen belegen Datenverarbeitung, keine physische Zählerqualität,
produktive Aktivierung oder bessere Prognosen.

## Kontinuität und begrenzte Zeitstempellücken

Neue Messintervalle tragen `measurement_contract=counter-lineage-support-v2`,
eine zufällige `continuity_id` und am ersten Intervall einer neuen Phase einen
`boundary_reason`. Die Kennung gilt nur für eine vom laufenden Tracker beobachtete
Phase. Reset, ungültiger/unverfügbarer Zähler, ungültige Messfreigabe,
Abregelung, unplausibler Sprung, zu lange Berichtlücke und Neustart beenden sie.
Anker und zurückgehaltene Berichte werden weiterhin nicht restauriert.

Genau aneinandergrenzende Messstücke bleiben zusammenfassbar. Unterschiedliche
bekannte Phasen oder ein expliziter Unterbrechungsgrund werden dabei nicht
verbunden. Bei gleicher nachgewiesener Phase dürfen einzelne Zeitstempellücken
höchstens **eine Sekunde** und zusammen höchstens **fünf Sekunden je Stunde
ursprünglicher Zieldauer** betragen. Ein halbstündiges Ziel hat somit höchstens
2,5 Sekunden Gesamtbudget. Tausende kleine Lücken umgehen dieses Budget nicht.
Alte Intervalle ohne diesen Herkunftsnachweis bleiben exakt zusammenhängend;
ihnen wird keine neue Unterbrechungsfreiheit zugeschrieben.

Die Toleranz verbindet nur die Auswahl von Messstücken. `measurement_support`
behält ihre wirklichen Zeitbereiche. Energie ist die Summe ganzer Zählerdeltas;
Messdauer ist die Summe ihrer Dauern. Eine Lücke liefert weder Energie noch
Messsekunden. `measurement_gap_seconds` nennt die ausgeschlossene Zeit.
Istleistung, Abdeckungsgrad, Historienstunden und Lerngewichte verwenden diesen
Support. Unverändert gelten mindestens 92 % Abdeckung, höchstens 180 Sekunden
Verlust je Rand und mindestens 30 Minuten ursprüngliche Zieldauer. Fehlende
Randenergie wird nicht interpoliert.

## Konflikte vor der Auswahl von Zielteilen

Jeder Join filtert Messstücke zunächst nach tatsächlicher Empfangsverfügbarkeit
und finalisiertem Ende. Anschließend werden exakte Duplikate entdoppelt und
Überlappungs-/Widerspruchsbereiche einmal je Stufe indiziert. Erst danach wird
für ein Prognoseziel ein vollständig enthaltener Messblock ausgewählt.

Die Konfliktprüfung umfasst **alle verfügbaren Messstücke, die das Ziel
schneiden**, einschließlich links vor Zielbeginn startender und rechts über das
Zielende laufender Stücke. Ein scheinbar passender Block 10:01–10:59 darf deshalb
kein Stundenlabel bilden, wenn ein ebenfalls verfügbares Stück 09:55–10:05 oder
10:55–11:05 ihm widerspricht. Exakt angrenzende Nachbarn sind keine
Überlappungen. Ein erst später empfangener Widerspruch sperrt die betroffene
Auswertung erst ab seiner tatsächlichen Verfügbarkeit; frühere As-of-Auswertungen
werden nicht mit zukünftiger Information kontaminiert.

Die Sperre betrifft nur Ziele, die einen Konfliktbereich schneiden. Unabhängige
spätere Stunden und Endpunktfenster bleiben nutzbar. Individuell plausible
historische Zeilen werden beim Restore nicht pauschal gelöscht; der gleiche
Joinfilter verhindert daraus widersprüchliche Trainingslabels. Fehlende oder
widersprechende Energie wird weiterhin nicht verteilt oder ersetzt.

Sortierte Startzeiten und Prefix-Maxima der Endzeiten erlauben Konfliktabfragen
in logarithmischer Zeit. Der Index entsteht einmal je Stufe und Join; die
anschließende Blockwahl liest nur Stücke mit Start im jeweiligen Ziel. Es gibt
keinen Vollscan der gesamten Historie für jede Zielzelle. Regressionen in
`tests/test_measurement_conflicts.py` prüfen beide Ränder, verschachtelte linke
Übertritte, Restore, Nachbarintervalle, Empfangscutoffs und unabhängige Ziele.

## Langsame Berichte und kleine Energiequanten

Ein kleines positives Delta unmittelbar nach einem Bericht kann durch Rundung
vorübergehend zu hohe Leistung ergeben. Der Tracker darf es bis zum nächsten
**echten** Originalbericht zurückhalten, höchstens **15 Minuten ab dem
ursprünglichen Anker**. Damit kann auch ein Zähler mit fünf oder zehn Minuten
Meldezyklus den ganzen Abschnitt bestätigen. Es gibt keine Timerfreigabe,
zusätzliches Quellenpolling oder veränderte Berichtzeit.

Die Energiegrenze für den anfänglichen Sprung bleibt separat: höchstens die bei
der Ausgangsgrenze plus 10 % in **60 Sekunden** mögliche Energie. Längeres
Warten erlaubt keinen größeren anfänglichen Sprung. Der abschließende Bericht
prüft die mittlere Leistung der ganzen Differenz gegen dieselbe Ausgangsgrenze;
Energie wird nicht gekappt. Resetprüfung berücksichtigt den letzten
zurückgehaltenen Originalwert. Jede Unterbrechung verwirft den offenen Abschnitt.
Die maximal zulässige Zählerdifferenzdauer bleibt 15 Minuten. Ein Bericht nach
dieser Grenze ankert neu und liefert kein Label für den alten Abschnitt.

## Endpunktfenster statt erzwungener voller Stunden

Ein Zähler mit Berichten um 10:02, 10:07, …, 11:02 belegt eine ganze Stunde.
Im Ziel 10:00–11:00 passen dagegen nur 55 Minuten vollständig hinein. Die
92-%-Grenze bleibt bestehen. Zusätzlich kann der Join daher ein Fenster
**10:02–11:02** aus ganzen Messdifferenzen auswählen.

Koaleszierte neue Messzeilen behalten in `measurement_parts` die echten
Start-/End-/Empfangszeiten und Energiedifferenzen ihrer Originalberichte beziehungsweise zusammengefasster ganzer Differenzen.
Benachbarte kleine Deltas derselben lückenlosen Phase werden bis höchstens
60 Sekunden Gesamtdauer verdichtet. Beide Endpunkte bleiben echte Berichte;
Energie und Empfangszeit sind Summe beziehungsweise spätester echter Empfang.
Fünfminuten-Deltas werden nicht unterteilt oder mit Nachbardeltas verdichtet. Der
Join kann damit beispielsweise den echten Endpunkt 11:10 auch dann auswählen,
wenn die kompakte Stundenzeile bis 11:30 reicht. Es wird nur eine archivierte
Originaldifferenz wieder freigelegt; keine gemessene Energie wird interpoliert.
Restore prüft Adjazenz, Endpunkte, Empfang, Einzelkappen und Energiesumme.

Diese zusätzlichen Fenster benötigen den neuen Kontinuitätsnachweis. Sie starten
am ersten verfügbaren echten Messendpunkt und enden am ersten folgenden echten
Endpunkt nach mindestens einer Stunde, höchstens nach 75 Minuten. Danach beginnt
ein neues Fenster; Auswahl und Partitionierung hängen nur von Zeiten und
Verfügbarkeit ab. Bereits von angenommenen ursprünglichen Zellen belegter
Messsupport wird nicht erneut als zusätzliches Fenster verwendet. Überlappende
Originalziele und mehrere echte Forecast-Origins bleiben bei Historienstunden
und Gewichten ebenfalls auf ihre gemeinsame Messdauer begrenzt.

Für ein solches Fenster braucht der Join einen tatsächlich archivierten,
**gemeinsamen ursprünglichen Ausgabezeitpunkt**. Dessen Quellzellen müssen jeden
gemessenen Zeitbereich vollständig abdecken. Ihre ursprünglichen Baseline-
Intervallmittel werden über exakt diesen Support integriert; numerische
Archivfeatures werden mit denselben Zeitgewichten aggregiert. Es wird keine
historische Physik neu berechnet. Gemessene Deltas werden niemals an einer
Prognosegrenze geteilt. Verschiedene Ausgabezeitpunkte oder GHI-Regime,
fehlende Forecastbereiche, `source_partial_at_issue` und mit dem aktuellen
Schattenstand unvereinbare Quellbaselines sperren das zusätzliche Fenster.

Der Sonnenazimut wird zyklisch aggregiert: `sun_azimuth_deg` folgt der Richtung
des zeitgewichteten Sinus-/Kosinusmittels, sodass 359° und 1° nach Norden zeigen.
Vorhandene Sinus-/Kosinusfeatures behalten ihre zeitgewichteten Mittelwerte;
Gradwerte und Vektorrichtung bleiben konsistent. Bei reinen Gradfeatures werden
die Vektoren vor der Mittelung daraus gebildet. Ein unvollständiger Vektor oder
eine mittlere Vektorlänge von höchstens `1e-12` liefert keine definierte Richtung
und sperrt das Endpunktfenster. Lücken erhalten auch bei den Winkelgewichten
keine Dauer. Originalfeatures und gemessene Energiedifferenzen werden dabei
nicht verändert; der Join wird aus den Originalzellen neu aufgebaut.

Ausgabezeiten müssen vor Beginn der betreffenden Originalzellen und des neuen
Messfensters liegen. Der Lead bezieht sich auf die Mitte des neuen Fensters.
Ein Label gilt erst nach seinem tatsächlichen Endpunkt und Empfang; `as_of`
filtert auch verspätete Labels. Chronologische Trainings-/Validierungs-/
Kalibrierungsgrenzen, Ausgangskappen und sonstige Datenleck-Gates bleiben aktiv.
Alle Dauern verwenden UTC, auch bei beiden Zeitumstellungen.

### Verschachtelte native Zustandsereignisse

Die geprüften Core-Pakete 2026.10.2/.3/.4 stellen verschachtelte Ereignisse in
`EventBus.async_fire_internal` in eine Warteschlange. Ein früherer Listener
kann den aktuellen HA-State schon weiter verändern; die neu ausgelösten
Zustandsereignisse werden jedoch erst nach allen Listenern des laufenden
Ereignisses verarbeitet. Ein beobachtetes `unknown`/`unavailable` wird deshalb
vor seinem so erzeugten numerischen Folgeereignis verarbeitet. Der erste
gültige Folgebericht ankert neu. Native Regressionen unter Core 2026.10.4 prüfen
auch Nullenergie, positive Deltas, ungültige Einheiten, `restored`, Entfernung
und mehrfach verschachtelte Wiederkehr sowie die tatsächlich exportierten
Intervallgrenzen. Dies gilt für diese geprüfte native Ereignisfolge;
beliebig manuell rückdatierte Ereignisse werden damit nicht zertifiziert.

## Gemeinsame archivierte Ausgabezeitpunkte

Die Auswahl gemeinsamer Origins muss bereits bei der Archivverdichtung erhalten
bleiben. Unabhängige Min-/Max-/Mittel-Origins je Stunde können durch ihren
Stundenversatz sämtliche gemeinsamen kurzfristigen oder GHI-Ausgaben entfernen.
Ein synthetischer End-to-End-Gegenfall mit 1.765 echten Archivaufrufen im
Fünfminutenraster, sechs Tagen Vorlauf und drei Messfenstern ab 10:02 bestätigte
diesen Fehler: Bei vier konfigurierten Stufen blieben nur drei lange NWP-Labels
im `96h+`-Bin; sämtliche GHI- und kürzeren NWP-Labels fehlten. Ab sieben Stufen
blieben gar keine Endpunktlabels. Das ungekürzte Kontrollarchiv enthielt dafür
geeignete ursprüngliche Ausgaben.

Bei unmittelbar benachbarten Originalzellen werden deshalb beide Zeilen einer
wirklich gemeinsamen Ausgabe zusammen aufbewahrt, je Lead-Bin und Regime. Für
bis zu sechs Stufen sind dies frühester und spätester gemeinsamer Issue; ab
sieben Stufen ist es der gemeinsame Issue am nächsten zur bestehenden festen
Binmitte (GHI im ersten Bin: 1,5 Stunden). Gleichstand nimmt die spätere echte
Ausgabe. Die Auswahl verwendet ausschließlich Zeiten und Regime, niemals
Messenergie oder Modellfehler. Isolierte Zellen und Bins ohne geeignete
Paar-Origin behalten die bisherigen Einzelzellrepräsentanten. Vorhandene
historische gemeinsame Ausgaben werden nicht nachträglich erfunden.

Paar-Origin ersetzt die unabhängige Auswahl der betroffenen Zell-Bins, statt
deren gesamte frühere Zeilenmenge zusätzlich anzuhängen. Eine Zelle gehört zu
höchstens zwei unmittelbar benachbarten Paaren. Im normalen Stundenraster mit
fünf NWP-Bins und dem kurzfristigen GHI-Bin sind damit höchstens 24 Origins je
Zelle bei bis zu sechs Stufen beziehungsweise zwölf ab sieben Stufen nötig.
Bei 16 positiven Zielstunden täglich passen beispielsweise 28 Historientage
plus sechs volle Zukunftstage für vier Stufen in 52.224 Zeilen, für sieben
Stufen in 45.696 Zeilen. Das globale Limit von 60.000 Zeilen und 120 Tagen bleibt
hart. Mehr Stufen, längere Tagesunterstützung oder zusätzliche Zellraster können
die tatsächlich gespeicherte Dauer weiterhin verkürzen.

Ab sieben Stufen begrenzt der einzelne zeitliche Mittelrepräsentant den
belegbaren Lead-Bereich stärker. Außerhalb der tatsächlich separat validierten
Trainings-/Validierungsunterstützung bleibt die Physik maßgeblich. Bei exakt
periodischen Ausgaben und konstanter Messphase kann dieser Bereich sogar
punktförmig sein: ein Messmittelpunkt zwei Minuten nach der Quellstundenmitte
kann beispielsweise 3,033 Stunden Lead belegen, während die operative
Stundenprognose 3,0 Stunden trägt. Auch dann entsteht keine automatische
Residualfreigabe; angenommene Endpunktlabels sind kein Nachweis produktiver
ML-Anwendung. Es werden weder Lead-Gates noch Chronologie gelockert. Bei feineren oder unregelmäßigen
Forecastzellen, deren Messfenster mehr als zwei Originalzellen umfasst, reicht
ein gemeinsames benachbartes Paar nicht notwendigerweise für das ganze Fenster;
fehlende gemeinsame Ausgabe bleibt dann konservativ eine Trainingslücke.
`tests/test_endpoint_origin_retention.py` prüft die reale wiederholte
Archivierung und anschließend verbundene NWP-/GHI-Endpunktlabels für ein, vier
und sieben konfigurierte Stufen gegen das ungekürzte Kontrollarchiv.

## Persistenz, Aufwand und Grenzen

Der optionale Messvertrag erweitert Zeilen im bestehenden `history_v2`-Store;
HA-Store-Version, physischer Historyhash und gültige bestehende Mess-/
Forecastzeilen werden dafür nicht pauschal zurückgesetzt. Unbekannte oder
beschädigte neue Herkunftsfelder lassen sich nicht als gültiger Nachweis laden.
Zusätzlich gelten höchstens 200.000 originale Messdifferenzen insgesamt und
10.000 Teile je koaleszierter Zeile. Regelmäßige Einsekundenberichte benötigen
nach Verdichtung höchstens einen Teil je Minute. Bei vier Stufen passen dadurch
etwa 34 Tage statt nur 14 Stunden unter die 200.000-Teile-Grenze; der Test prüft
für alle vier Stufen mehr als 28 erhaltene Zieltage und Energieerhalt.
Bei höherer Ereignisdichte bleibt die
Aufbewahrung entsprechend kürzer. Vier Stufen mit echten Fünfminutenberichten
brauchen in 120 Tagen 138.240 Originalteile und bei beliebigem Stundenversatz
höchstens etwa 23.040 kompakte Stunden-/Übertrittszeilen; beides liegt innerhalb
der Grenzen. Der Retentiontest prüft diese tatsächlich erhaltene Historie.

Alte passende Historie bleibt unter ihren bisherigen strengeren Voraussetzungen
nutzbar. Früher verworfene Energie und nie archivierte Prognosen bleiben fehlend.
Ein nach einem Neustart neuer Tracker erhält neue Phasenkennungen, auch bei
unverändertem Zählerstand.

Zeitgewichte berechnet ein Sweep über Start-/Endereignisse und verteilt jede
wirklich gemessene Sekunde insgesamt einmal auf ihre unterstützten Samples.
Doppelte Origins und überlappende Fenster erzeugen keine zusätzlichen unabhängigen
Stunden. Die Originalprognosen werden bei den Endpunktfenstern über aktive
Quellzellen ausgewählt. Bestehende Zeilen- und Aufbewahrungsgrenzen bleiben gültig.

Tests: `tests/test_measurement_lineage.py`, ergänzt durch
`test_measurement_windows.py`, `test_training_alignment.py`, die nativen
HA-Messgültigkeits-/Integratorfälle und die Persistenztests. Abgedeckt sind
1-/5-/10-Minuten-Zyklen mit unregelmäßigen Berichten und Stundenversatz,
Millisekunden- und kumulierte Lücken, Energieerhalt, langsame Burstabschlüsse,
echte Unterbrechungen, Neustart, beide DST-Übergänge und spätere Labelverfügbarkeit.
Ein neuer Datenvertrag oder mehr angenommene Samples ist kein empirischer
Genauigkeitsnachweis.
