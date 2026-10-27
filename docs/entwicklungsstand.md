# Entwicklungsstand und offene Nachweise

## Lokaler Entwicklungsstand nach 0.2.14

Basis ist `6193efc39b4da87a5fad3252b991493c8b9fcda4` auf dem Entwicklungszweig
`feat/forecast-quality-20261027`. Drei Subagenten mit GPT-6.1-Sol und Reasoning
`high` haben die Änderungen implementiert und gegenseitig geprüft.

- [Messkontinuität](measurement-learning.md): begrenzte Zeitstempeltoleranz,
  unveränderte echte Energie, längeres Warten auf Zählerberichte und zusätzliche
  Lernfenster an erhaltenen Messendpunkten.
- [Fehlerbehandlung](forecast-resilience.md): Physikfallback bei gescheitertem
  Fit, begrenzter alter Wettercache bei Abruffehlern und Laufzeitdiagnosen.
- [Früher Bias-Kandidat](early-bias-shadow.md) und
  [Vergleichsarchiv](model-comparison-archive.md): ausschließlich prospektive
  Prüfung, keine automatische Änderung der Modellgewichte oder Aktivierung.
- [Physik und Schatten](physics-learning-options.md): optionale Parameter und
  Teilintervallintegration, zeitlich qualifizierte Schattentabelle und optionale
  Glättung normalisierter Leistungsabweichungen.

Der gegenseitige Review führte unter anderem zu Regressionstests für den Verlust
echter Messendpunkte beim Zusammenfassen, zeitlich rückwirkende Schattenberichte,
unbeabsichtigt verfallende Schattenfreigaben und beschädigte Historien. Alte
Schattenproben ohne belegte Beobachtungs-/Empfangszeit bleiben als zeitlich
unqualifizierte Altdaten erhalten und beeinflussen die neue Schattentabelle nicht.
Gültige bisherige Messhistorie und ausgegebene Tagesstartprognosen bleiben nach
ihren bisherigen Bindungsprüfungen erhalten.

Lokale Abschlussprüfung mit Python 3.14.4 und HA Core 2026.10.4:
**1256 Tests bestanden, keine Skips**, Ruff und Dependencycheck sauber.
Die kombinierte Zeilen-/Zweigabdeckung beträgt **92,36 %**; das neue CI-Gate
verlangt mindestens 90 % über den gesamten Komponentenquelltext. Ein reguläres
Wheel wurde isoliert installiert: alle 30 Integrationsdateien sind bytegleich
zum Arbeitsstand, zwölf HA-/Kernmodule importieren aus dieser Installation.
Private Prüfartefakte liegen unter `artifacts/forecast-quality-*`. Der gebundene
externe Fachreview ist ein separater Nachweis; die Tests beweisen keinen
Genauigkeitsvorsprung und keine produktive HA-Stabilität.

Der erste gültige Codex-Review von `d73fc4c` fand drei behebungsbedürftige Punkte:
vollständige Tage bei mehreren Vergleichs-Origins, ursprüngliche Wetterstützen
der Schattenreferenz und die Beschreibung fehlgeschlagener Tagescaptures. Die
Korrekturen und ein zusätzlicher Ende-zu-Ende-Befund zur gemeinsamen Aufbewahrung
benachbarter Forecast-Origins sind in den Tests enthalten. Der zweite Nachreview
von `9e85391` fand einen weiteren Randfall mit überlappenden Messstücken jenseits
der ursprünglichen Zielgrenzen. Ein gemeinsamer zeitlich gefilterter
Konfliktindex schützt nun ursprüngliche und verschobene Lernfenster, ohne
unabhängige saubere Zeitbereiche zu sperren. 15 zusätzliche Regressionen und
ein unabhängiger Vergleich von 63.000 Intervallabfragen mit einer einfachen
Referenzberechnung prüfen diese Korrektur.
[Reviewbearbeitung](review-findings.md#entwicklungsnachtrag-nach-0214).

Dies ist ein lokaler Implementierungsstand; Paketversion und veröffentlichter
Stand bleiben 0.2.14. Produktive Einstellungen, HACS und HA wurden in diesem
Arbeitsauftrag nicht geändert. Eine bessere reale Prognose und eine Freigabe
des frühen Bias-Kandidaten brauchen die getrennte prospektive Auswertung.

## Veröffentlichter und installierter Stand 0.2.14

Stand: 27.10.2026. [Nachtstrahlung und historische Tagesstartwerte](forecast-repairs.md)
sind implementiert und vollständig geprüft. [Releasebeschreibung](release-0.2.14.md).

Geprüfte Implementierung `af3df57`: **1102 Tests ohne Skips**, Ruff und Dependencycheck erfolgreich. Vollständiger Grok-4.7/high-Textreview über **111 Originaldateien**, 1,500,456 Payloadbytes und 27 erfolgreiche Turns: **mergeable, keine Findings**. Separater Nachaudit bestätigt identische Original-/Promptbytes, Quell-/CLI-Hashes, native Modell-/High-Identität, erfolgreichen Abschluss und null Compaction/Tools. Private Belege: `reviews/private/forecast-repairs-20261027-round2/` und `artifacts/forecast-repairs-20261027/review-closeout.json`; Receipt-SHA256 `56788cd17274a57645bbc676ded073ff07c8792625d6baf3aca949e93ce64724`.

[v0.2.14](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.14) aus Commit
`b5bff6ba7deff3a9b7831cdc77bcc595a7942353` veröffentlicht. Wheel, Sdist,
Integrations-ZIP und SHA256-Liste gebaut und nach Veröffentlichung bytegleich
zurückgeladen. Alle **26 Integrationsdateien** sind bytegleich zum akzeptierten
Reviewstand; reguläre Wheelinstallation und **zwölf HA-Modulimports** geprüft.
[Branch-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40534533990) und
[Tag-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40534536271)
erfolgreich, jeweils 1102 Tests ohne Skips.

Neue geschützte native Konfigurations-/App-Sicherung ohne Recorder-DB angelegt;
Create-Timeout durch native Auflistung geklärt, Metadaten und vollständiger äußerer
SHA256 geprüft. Entschlüsselung/Wiederherstellung nicht getestet. Zusätzlich
Komponentenbytes und vier aktuelle Historienstores für einen gezielten Rückweg
gesichert. Native HACS-Übernahme, exakter 26-Dateien-Readback und **ein Core-Neustart**;
Core selbst, Runtimepins und `beam-shade-table-v1` bleiben unverändert.

Vier Einträge geladen, **80 Entity-/Unique-IDs mit Benutzeranpassungen, vier Geräte,
sämtliche Optionen und Energy-Einstellungen identisch**. Vorhandene abgeschlossene
Messintervalle und Fingerprints erhalten. Nach natürlichen Quellenberichten nur
die vier eigenen Prognosestatusanzeigen aktualisiert; alle vier Physik/kalt mit
gültigen Umwelt-/Leistungseingängen. Keine Originalmessquelle erzwungen.

Die native Wetterdiagnose bestätigt bei allen vier Stufen exakt eine kleine
negative Nachtstrahlungsnormalisierung. **Drei vollständige lokale Folgetage mit
je 24 Stunden pro Stufe**, keine Kurvenlücken, Energiebezug und nominelle Grenzen
geprüft. Die heutigen vier Original-Tagesstartwerte wurden ausschließlich über
die neue Administratoraktion aus zusammengehörigen alten Snapshots und ihren
Originalkonfigurationen importiert, tatsächlich gespeichert zurückgelesen und mit
`source=operator_restore` sowie geändertem Original-Konfigurationsstand gekennzeichnet.
Keine alten Lernzeilen importiert und keine Prognose aus heutigem Wetter rückdatiert.

Anzeige für heute und die nächsten drei Tage visuell gerendert geprüft;
Dashboardkonfiguration unverändert. Konfiguration gültig, keine aktiven Repairs,
keine aktuellen Systemlogeinträge im Filter `adaptive_solar`. HACS installiert und
angeboten v0.2.14, kein Update offen. Private Belege:
`data/release-0.2.14-20261027/`; Laufzeitaudit-SHA256
`8aef546af70cd07692320c7a14bfd6a90b96dcfcd74ff04200977e215acca526`.

Dieser nachträgliche Status liegt außerhalb von Release-Tag und eingefrorenem
Reviewtext; ausgelieferte Integrationsbytes und Tag bleiben unverändert.
Qualifiziertes produktives ML und ein Prognosevorteil gegenüber Referenzen bleiben
eigene offene Nachweise. Die nachfolgenden 0.2.13-Belege sind historisch.

## Veröffentlichter und installierter Stand 0.2.13

Stand: 27.10.2026. [v0.2.13](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.13)
aus Commit `79794cad9a4e54d9c21f52b204c3d71d02d7287e` veröffentlicht und über
HACS auf Core **2026.10.4** installiert. [Releaseinhalt](release-0.2.13.md):
92 % Mindestabdeckung, feste 180 Sekunden Randlücke, begrenzte Behandlung
kurzer Zählerbursts, längster gültiger Messblock und Ablehnungsdetails mit
Originalzeiten. Geprüfte Implementierung: `9259903`; außer der Manifestversion
bleiben die Integrationsbytes gleich zum akzeptierten Grok-4.7/high-Nachreview.

**1057 lokale Tests ohne Skips**, Ruff und Dependencycheck erfolgreich.
Gültiger Volltextreview über 106 öffentliche Originaldateien, 1.446.687
Payloadbytes und 26 erfolgreiche Turns; native Kontext-/Hashprüfung unabhängig
wiederholt, keine Compaction, Tools oder aktiven Hintergrundaufgaben.
Die dauerhafte Freigabe für Grok-Reviews öffentlicher Repositoryquellen steht
in AGENTS.md. Private Installationsdaten und Zugangsdaten bleiben ausgeschlossen.

Wheel, Sdist, Integrations-ZIP und SHA256-Liste veröffentlicht und nach Download
bytegleich geprüft. **25 Integrationsdateien**, beide GPL-Lizenzkopien und
Paketmetadaten kontrolliert; reguläres Wheel separat installiert und elf Module
mit HA Core importiert. [Branch-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40522629895)
und [Tag-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40522628968)
vor HACS-Download erfolgreich, jeweils 1057 Tests ohne Skips.
Lokale Paket-/Reviewbelege: `artifacts/release-0.2.13/` und
`artifacts/rejection-details-20261027/`.

Neue geschützte native Sicherung von HA-Konfiguration und Apps ohne Recorder-DB
angelegt. Der Create-Aufruf meldete Timeout; Abschluss über native Liste bestätigt,
Archivmetadaten und voller äußerer SHA geprüft. Entschlüsselung/Wiederherstellung
nicht getestet. Zusätzlich bisherige Komponente und vier Lernstores lokal für
einen gezielten Rückweg gesichert. Nach HACS-Download alle 25 Dateien geprüft,
genau ein Core-Neustart; Core selbst und die Runtimepins bleiben unverändert.

Vier geladene Einträge melden nativ **0.2.13** und erfolgreiche Updates. **80
Entity-/Unique-IDs samt Benutzeranpassungen, vier Geräte, sämtliche Optionen und
Energy-Einstellungen unverändert.** Physische/volle Fingerprints,
`beam-shade-table-v1`, zuvor abgeschlossene Messintervalle und beim Update noch
vorhandene Tagesbeginn-Snapshots erhalten. Die heutigen Snapshots fehlten bereits
vor dem Update nach vorherigen Optionsänderungen; der Updatevergleich belegt
keine Wiederherstellung dieser Daten. Kein Historienreset durch dieses Update.

Alle vier neuen Ablehnungsdiagnosen liefern Schema 1, echte Fit-Cutoffs,
vollständige passende Ziel-/Zeilenzähler und höchstens 50 eindeutige Einträge
je Gruppe. Die live sichtbare Policy ist 0,92 / 180 Sekunden / 60 Sekunden
Plausibilitätsfenster. Nach echten Quellenberichten nur die vier eigenen
Prognosestatusanzeigen aktualisiert; Originalmessquellen nicht gepollt.
Alle vier anschließend **Physik/kalt**, gültige Umweltwerte, keine Wetterfehler.
Konfiguration gültig, keine aktiven Repairs, keine aktuellen Einträge im
Systemlogfilter `adaptive_solar`. HACS: installiert/angeboten v0.2.13, kein Update offen.

**Laufzeitgrenze:** Zwei vollständige lokale Folgetage je Stufe geprüft.
Am dritten Folgetag fehlt in allen vier nativen Prognosekurven am 30.10.2026
19–20 Uhr UTC eine Stunde; direkt im HA-Zustand zusätzlich bestätigt.
Die Lücke bleibt fehlend. Die nachfolgende Ursachenanalyse klärt den Auslöser;
der Nachweis behauptet ausdrücklich keine drei vollständigen Folgetage oder
geklärte Prognosegüte.
Verfügbare Intervalle halten nominelle Grenzen, Einheiten und Energiebezug ein.

### Ursachenanalyse: Stundenlücke und fehlender heutiger Tageswert

Read-only-Nachprüfung am 27.10.2026 gegen native HA-Zustände, Recorder-Historie,
gespeicherte Historien, Optionsvergleiche und einen frischen Wetterabruf:

- Die Stundenlücke betrifft alle vier Stufen am 30.10.2026 von **19–20 Uhr UTC**
  (**20–21 Uhr Europe/Berlin**). Open-Meteo `best_match` liefert am zugehörigen
  Endzeitstempel 20 Uhr UTC `shortwave_radiation=-1.0 W/m²`; DNI und DHI sind null.
  Alle anderen abgefragten Wetterwerte liegen im zulässigen Bereich.
- `weather.parse_forecast()` verwirft negative Strahlungswerte und dadurch die
  vollständige betroffene Stunde. Open-Meteo-Strahlung beschreibt den Mittelwert
  der vorhergehenden Stunde ([Parameterdefinition](https://open-meteo.com/en/docs#hourly-parameter-definition),
  geprüft am 27.10.2026). Die Zuordnung ist daher kein Zeitzonenversatz.
  Ein Diagnoseversuch ausschließlich auf einer Kopie der frischen Antwort,
  mit genau diesem einen Wert von −1 auf 0 gesetzt, stellt genau die fehlende
  Parserstunde wieder her. Dies belegt den technischen Auslöser; die Entstehung
  des negativen Werts beim Anbieter wurde nicht untersucht.
- `ForecastResult.energy_kwh()` verlangt lückenlose Abdeckung. Deshalb ist auch
  `prognose_tag_3` nicht verfügbar, obwohl die Lücke nachts liegt. Die native
  Kurve enthält die Lücke bereits vor der Dashboarddarstellung. Leere
  `weather_errors` schließen solche verworfenen Einzelwerte nicht aus; der
  aktuelle Qualitätsstatus prüft die Abdeckung des verbleibenden heutigen Tages.
- `prognose_tag_0` verwendet ausschließlich einen vor Tagesbeginn ausgegebenen
  vollständigen Snapshot. Bei Änderungen des physischen Historienfingerprints
  lädt `async_restore()` bisher auch diese Snapshots nicht mehr. Dämpfung,
  Horizont und die Energiezähler-Anbindung gehören zu diesem Fingerprint.
  Optionsvergleich und Recorder zeigen den Verlust der heutigen Werte nach
  solchen Änderungen; in allen vier aktuellen Stores fehlt der heutige Schlüssel.
  Die Werte fehlten schon vor dem Download von 0.2.13, während dessen
  vorheriger/nachheriger Vergleich die vorhandene Historie erhielt.
- Nach Tagesbeginn erzeugt `_archive()` keinen nachträglichen heutigen
  Tagesstartwert. Resttag und zukünftige Tage können trotzdem verfügbar sein.
  Frühere heutige Tageswerte sind noch im Recorder und in privaten
  Voränderungsbelegen nachweisbar, gehören aber zum damaligen Konfigurationsstand.

Private Analysebelege: `data/forecast-gap-analysis-20261027/`. Keine produktiven
Schreibzugriffe, keine Interpolation und keine Datenwiederherstellung. Mögliche
Folgearbeiten sind eine eng begrenzte, explizit diagnostizierte Behandlung kleiner
negativer Nachtstrahlung sowie die separate Erhaltung historischer
Tagesstartprognosen mit ihrer ursprünglichen Konfigurationsprovenienz. Beides ist
hier weder implementiert noch freigegeben; echte Lücken dürfen nicht pauschal
mit null gefüllt werden.

Private Rohbelege: `data/release-0.2.13-20261027/`;
Laufzeitaudit-SHA256: `1b1854520cb9e586f31330675fa41c46dc7ec51cfb9fe3e86a06c07d077549b0`.
Diese nachträgliche Statusdokumentation ist außerhalb von Tag/Reviewtext;
ausgelieferter Code und Tag bleiben unverändert. Dashboardressourcen und HA-Config
wurden nicht geändert. Qualifiziertes produktives ML und ein realer Vorteil
genüber Referenzintegrationen bleiben offen.

## Ursprünglicher lokaler Diagnose-Nachtrag vom 27.10.2026

Die [Diagnoseschnittstelle](ablehnungsdiagnose.md) ergänzt Originalzeiten und
Gründe für eindeutige abgelehnte Ziele und die schon gezählten Learner-Zeilen.
Schema 1, maximal 50 eindeutige Einträge je Gruppe, vollständige Rohzähler,
keine erfundenen Zeitwerte. Zwei mit dem Auftraggeber abgestimmte
Präzisierungen: Der bereits gezählte Schattenfilter wird erklärt; Alignment
und beide Detailgruppen bleiben als gemeinsamer Fit-Snapshot einschließlich
seines Cutoffs erhalten. Trainingsauswahl, Fits, Prognosen und Gates bleiben
unverändert. Bei diesem ursprünglichen lokalen Arbeitsabschluss gab es noch
keinen Deploy, Push oder Release; der spätere Rollout steht oben. HA-Config
bleibt unverändert.

**1057 Tests ohne Fehler oder Skips** unter Core 2026.10.4 bestanden, darunter
40 neue Diagnose-Regressionen. Ruff, Dependencycheck und Markdownziele geprüft.
Die 20 bestehenden HA-Config-Verbrauchertests und vier aus dem Producer erzeugte
Vertragsbeispiele bestehen ebenfalls; HA-Config bleibt unverändert.
Lokale Belege: `artifacts/rejection-details-20261027/`.
Der [erste externe Review](review-findings.md#lokale-ablehnungsdiagnose-erster-review-und-doku-korrektur)
mit Grok 4.7/high fand einen veralteten Schwellenwertabsatz in der
Datenquellenrecherche (AS-001, mittel), keine Implementierungsfindings.
Die Dokumentationsstelle ist korrigiert. Der [frische Nachreview](review-findings.md#gültiger-grok-nachreview-der-ablehnungsdiagnose)
ist **mergeable ohne Findings**: 106 Originaltexte, 1.446.687 Payloadbytes,
26 erfolgreiche Turns, native Kontext-/Hashprüfung unabhängig wiederholt.
Keine Compaction, Tools oder aktiven Hintergrundaufgaben. Push und HA-Update
sind inzwischen ausdrücklich beauftragt und werden separat nachgewiesen.
Frühere Receipts werden nicht auf neue Dateien erweitert.

## Lokaler Messdaten-Nachtrag vom 27.10.2026

Zusätzlich zur unveränderten veröffentlichten Version 0.2.12 ist die
[Messaufbereitung](messintervalle-92-prozent.md) im Repository angepasst:
92 % Mindestabdeckung, höchstens drei Minuten Lücke je Rand, Auswahl des
längsten gültigen zusammenhängenden Messblocks und begrenztes Zurückhalten
kurzer auffälliger Zählerdifferenzen bis zu einem echten Folgebericht.
Resets, ungültige/abgeregelte Phasen, überhöhte Dauerdifferenzen, große Sprünge,
Überschneidungen und zukünftige Labels bleiben ausgeschlossen.

**1017 Tests ohne Fehler oder Skips** unter Core 2026.10.4 bestanden, darunter
39 neue Regressionen für Grenzwerte, Rundungsbursts, echte HA-Ereignisse,
Wiederfreigabe, As-of-Verfügbarkeit und beide Zeitumstellungen. Ruff und
Dependencycheck erfolgreich. Lokale Nachweise:
`artifacts/measurement-windows-20261027/`.

Zum Abschluss dieses Messdaten-Nachtrags in `1634e08` lag noch kein neuer
externer Review vor; der spätere Diagnosereview ist oben separat gebunden.
Der damalige Nachweis enthielt keinen neuen Release, Push oder produktiven
HA-Rollout; der spätere Stand 0.2.13 ist oben separat dokumentiert.
Bestehende Release-/Reviewbelege gelten dem jeweils eingefrorenen Stand;
sie werden nicht auf diesen Nachtrag erweitert. Die Lernhistorie wird nicht
pauschal zurückgesetzt; früher verworfene Energie wird nicht rekonstruiert.
Mehr angenommene Lernlabels sind kein Nachweis besserer Prognosegüte.

## Historischer Veröffentlichungs- und Installationsstand 0.2.12

Stand: 27.10.2026. [v0.2.12](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.12)
ist aus Commit `7c2b4be3315ebc062b5b09a8237f94649cf7d034` veröffentlicht und nativ
über HACS installiert. [Releaseinhalt](release-0.2.12.md) basiert auf der mit Grok 4.7/high
erneut vollständig geprüften Implementierung `507ab4e`: 100 Originaltextdateien,
keine Findings, nativer Kontext-/Hashaudit unabhängig wiederholt. Die
Releasevorbereitung ändert nur Versionsmetadaten und öffentliche Release-/Statushinweise.
Alle übrigen Integrationsdateien bleiben bytegleich zum geprüften Stand.

Erneut **978 Tests ohne Fehler oder Skips** unter Core **2026.10.4** / Plugin
**0.13.375**, Ruff und Dependencycheck erfolgreich. Wheel, Sdist und Integrations-ZIP
gebaut; **24 Integrationsdateien**, beide GPL-Kopien und Paketmetadaten geprüft.
Das Wheel wurde separat regulär installiert; zehn Module aus diesem Paket wurden
mit echtem HA Core importiert. Bestehende Runtimepins und Musl-Binärbasis bleiben.
Lokale Paket-/Testnachweise: `artifacts/release-0.2.12/`.

Die drei Pakete und `SHA256SUMS` sind als Releaseassets veröffentlicht und nach
Download bytegleich zu den geprüften lokalen Artefakten. Wheel-SHA256:
`98a00ee83a7e322c81f3cdded765dc5f379b36e320a89aa3d46da56d094153e3`.
Vor Installation vollständig erfolgreiche CI für
[main](https://github.com/togo42/Adaptive-Solar/actions/runs/40470798170) und
[Tag](https://github.com/togo42/Adaptive-Solar/actions/runs/40470797964).
Der bestehende Tag 0.2.11 und der neue Tag 0.2.12 bleiben unverändert.

Frische geschützte native HA-Sicherung einschließlich Konfiguration/Apps und ohne
Recorderdatenbank; ihr Abschluss wurde nach einem Create-Timeout über die native
Liste bestätigt. Archivmetadaten und vollständiger äußerer SHA geprüft;
Entschlüsselung/Wiederherstellung nicht getestet. Zusätzlich wurden bisherige
Komponente und vier ausgewählte Lernstores unter ignoriertem `data/` gesichert.

Nach HACS-Download alle **24 Komponentendateien** gegen Release geprüft; genau
ein Core-Neustart. Vier geladene Einträge und native Diagnosen bestätigen
**0.2.12**, Core bleibt **2026.10.4**. HACS meldet installierte/angebotene Version
0.2.12 ohne weiteres Update. **80 Entity-/Unique-IDs und Benutzeranpassungen,
vier Geräte, sämtliche Optionen und Energy-Einstellungen unverändert.**

Alle vier Historienstores tragen nun `beam-shade-table-v1`; vollständiger und
physikalischer Konfigurationsfingerprint, zuvor abgeschlossene Messintervalle
sowie tatsächlich ausgegebene vergangene/heutige Tagesbeginn-Snapshots sind
erhalten. Alte Forecastfeatures wurden erwartungsgemäß verworfen, neue prospektive
Features werden archiviert. Die Schattentabellen beginnen neutral und noch ohne
freigegebenes Fenster. Ausreichende qualifizierte Lernhistorie liegt noch nicht vor.

Drei vollständige lokale Folgetage je Anlage, nominelle Ausgangsgrenzen, Energie
und Einheiten geprüft. Nach echten Quellenberichten nur die vier eigenen
Prognosequalitätsanzeigen aktualisiert; keine Originalmessquelle erzwungen.
Alle vier melden gültige Eingänge und **Physik/kalt**. Konfiguration gültig,
keine aktiven Repairs und keine Einträge im aktuellen Systemlogfilter
`adaptive_solar`. Das ist eine gebundene Betriebsprüfung, keine Garantie
langfristiger Warnungsfreiheit oder physikalische Quellenzertifizierung.

Private Rohbelege: `data/release-0.2.12-20261027/`; Laufzeitaudit-SHA256:
`53c5c2cbb398e8706d809a48a9a5d533eccc992b0658b1f3893d7edb5220e72a`.
Die nachgetragene Statusdokumentation ist außerhalb des eingefrorenen Reviews
und Tags; die Implementierungsdateien bleiben unverändert. Qualifiziertes
produktives Lernen und realer Prognosevorsprung bleiben offen.

## Veröffentlichter und installierter Stand 0.2.11

Stand: 26.10.2026. [v0.2.11](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.11)
ist aus Commit `9070886a70e29a843189fa1b2a2fc76ecaae355a` veröffentlicht und nativ
über HACS installiert. Der neue Gesamtblick deckt Code, alle sechs konsolidierten
Recherchen, GPL-Mitlieferung, öffentliche Anleitungen, Plattform-/Versionsgrenzen,
Mess-/Energy-Verträge und den strikten Reviewtransport ab. [Releaseinhalt](release-0.2.11.md).

Je **900 Tests ohne Fehler oder Skips** unter Core **2026.10.2/.3/.4**, Plugins
**0.13.373/.374/.375**, Python **3.14.4** bestanden. Laufzeit **85,70 / 87,90 / 85,54
Sekunden**. Ruff und Dependencychecks erfolgreich. Bestehende Umgebungen wurden
nicht neu installiert; die Tests laden Repositoryquellen. Das neu gebaute Wheel
wurde separat regulär installiert und mit sieben nativen Core-.4-Modulimporten,
allen **23 Paketdateien** und GPL-Metadaten geprüft. Wheel-SHA256:
`792ba45f9c414c365d8ecbc9709cfed3b507838da9fca75c98c4c6d01b34fab9`.
Prüfbelege lokal: `artifacts/release-0.2.11/`. 24 Markdowntexte mit 169 gültigen
lokalen Links; Scan veröffentlichter Dateien ohne erfasste Geheimnisse/private
Endpunkte; vorhandenes Logo zusätzlich visuell geprüft.

Der vollständige Grok-4.7/high-Review aller **96 öffentlichen Originaltextdateien**
einschließlich beider Lizenztexte ist **mergeable ohne Findings**. Alle sechs
Recherchen wurden erneut vollständig eingebettet; keine geerbten Forschungsreferenzen.
Ein nativer Abschlussturn, keine Compaction/Tools/Hintergrundaufgaben; unabhängiger
Audit von Originalbytes, CLI, Endantwort und Receipt erfolgreich. Globale
CLI-Konfiguration unverändert. Details und verworfener/blockierender Vorlauf im
[Reviewnachweis](review-findings.md). Die nachfolgende Statusdokumentation liegt
außerhalb dieses eingefrorenen Reviews; die Implementierungsdateien bleiben bytegleich.

GitHub-CI für [main](https://github.com/togo42/Adaptive-Solar/actions/runs/40324170165)
und [Tag](https://github.com/togo42/Adaptive-Solar/actions/runs/40324170286) war vor
Installation erfolgreich abgeschlossen. Vor Download frische geschützte native
HA-Sicherung einschließlich Konfiguration/Apps und ohne Recorderdatenbank erstellt;
Abschluss, Archivmetadaten und vollständiger äußerer SHA geprüft. Entschlüsselung
oder Wiederherstellung wurden nicht getestet. Zusätzlich bisherige Komponente und
vier ausgewählte Lernstores lokal für den gezielten Rückweg gesichert.

Nach HACS-Download alle **23 Komponentendateien** gegen Release geprüft; genau ein
Core-Neustart. Vier Einträge geladen, native Diagnosen bestätigen **0.2.11** bei
unverändertem **Core 2026.10.4 / Python 3.14.9**. Runtimepins/Binärpayload unverändert.
**80 Entity-/Unique-IDs und Benutzeranpassungen, vier Geräte, sämtliche Anlagenoptionen
und Energy-Einstellungen identisch**. Alle Historienfingerprints, zuvor abgeschlossene
Intervalle und Tagesanfangs-Snapshotdaten erhalten; die bisherige Historie bleibt
auf ausdrücklichen Betreiberwunsch und dessen Bestätigung abregelungsfreier letzter
Tage weiter nutzbar. Alte Kontrollprovenienz wird nicht nachträglich als technisch
geprüft markiert. Neue Intervalle werden an den drei angebundenen Energiequellen
angenommen. [Upgradegrenzen](release-0.2.11.md#upgrade-von-0210).

Drei vollständige lokale Folgetage je Anlage sowie Grenzen, Energie und Einheiten
rückgelesen. Nach echten Quellenberichten ausschließlich die vier eigenen
Prognosequalitätsanzeigen aktualisiert; keine Originalmessquelle erzwungen. Alle
vier melden gültige Eingänge und **Physik/kalt**. Konfiguration gültig, keine aktiven
Repairs, keine Einträge im aktuellen Systemlogfilter `adaptive_solar`. Das ist eine
gebundene Betriebsprüfung, kein Nachweis langfristiger Warnungsfreiheit. Lokaler
Laufzeitaudit-SHA256: `dcb67d435d51a340d47e42223423bbf58e3a842614f344c72e98e5ac51749594`.
Private Rohbelege verbleiben unter `data/release-0.2.11-20261026/` und werden nicht veröffentlicht.

Qualifiziertes produktives Lernen, physikalische Quellenqualifikation und ein fairer
prospektiver Genauigkeitsvorsprung gegenüber **beiden** Referenzen bleiben eigene
offene Nachweise. Tests, Review und Installation ersetzen diese nicht.

## Freigegebener Stand vor 0.2.11

Historischer Stand am 26.10.2026 vor dem oben dokumentierten Update: **Adaptive Solar 0.2.10 war veröffentlicht und über HACS unter Core 2026.10.4 installiert.** Der gebundene Grok-4.7/high-Review ist ohne Findings abgeschlossen; GitHub-CI erfolgreich. Vier Anlageneinträge, native Einrichtung und installierte Paketbytes sind zurückgelesen. Ein qualifizierter produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## Dokumentations- und Konsistenzpflege nach dem Release

Am 26.10.2026 wurden öffentliche [Installation](installation.md), [Bedienung](bedienung.md),
[Datenschutz](datenschutz.md) und [Entwicklung](entwicklung.md) ergänzt. Der HAOS-Weg
nennt nun Payloadvorbereitung, konkreten Core-User-Site-Pfad, Transfer, Prüfung und
Rückweg. Die Payloadvorbereitung mit den fünf unveränderten vorhandenen Musl-/Python-
Wheels wurde lokal offline ausgeführt; dies ist kein neuer Compilerlauf oder Deploy.

HACS beginnt jetzt beim ältesten geprüften Core 2026.10.2; eine ungenutzte veraltete
Versionskonstante entfällt. README und Entwicklungsschritte verwenden dieselben
Runtimepins wie CI. Der Horizont ist korrekt als einschließlich heute beschrieben.
Die sechs Forschungstexte wurden konsolidiert: unbelegte Fehlerbereiche, Ranglisten
und Prozentversprechen entfernt, Datenarten und Methoden mit direkten Primärquellen
verknüpft. Die frühere Breite der Literaturnotizen bleibt in der Git-Historie verfügbar.
Der Lizenzcommit `7f8d426` stellt eigene Inhalte unter GPL-3.0-only.

Frische Prüfung dieses Nachtrags: **893 Tests, null Fehler/Skips, 76,52 Sekunden** unter
Core **2026.10.3**, Testplugin **0.13.374**, Python **3.14.4**, pvlib **0.16.1** und
scikit-learn **1.9.1**. Ruff und `pip check` erfolgreich. Die übrigen Matrixarme wurden
hier nicht erneut ausgeführt. JUnit: `artifacts/documentation-audit-tests.xml`.
23 Markdown-Dateien mit vollständig geprüften lokalen Verweisen/Ankern, Tabellen und Codeblöcke
gerendert bzw. syntaktisch geprüft; 68 unterschiedliche verlinkte externe HTTP-Ziele
erreichbar. HTTP-Erreichbarkeit ist keine vollständige Inhalts- oder Tarifprüfung.
Versionsbezogene Primärdokumentationen und Quellen an den geänderten Aussagen ergänzen
diesen Linkcheck. Keine Zugangsdaten/private IPs in der Mustersuche über veröffentlichbare
Dateien gefunden; kein vollständiger Git-Historienscan behauptet.

Das nach der Pflege neu gebaute Wheel enthält alle 23 Integrationsdateien bytegleich
zum Arbeitsstand, einschließlich des Lizenztexts; GPL-3.0-only und die Lizenzkopie
in den Distributionsmetadaten sind geprüft. Die HAOS-Payloadvorbereitung enthält
nur die fünf vorgesehenen Distributionen samt Metadaten und gebündelten Bibliotheken,
keine überdeckenden NumPy-/SciPy-/Pandas-Pakete.

Diese Nachpflege enthält keine Änderung der Forecast-/Lernalgorithmen und keine
produktive HA-Aktion. Historische Release-, CI- und Grok-Angaben unten beziehen sich
weiterhin auf die eingefrorenen damaligen Quellen. Die neuen Forschungsbytes können
nicht mehr über die alten Forschungs-SHAs geerbt werden; ein neuer externer Review
oder eine Veröffentlichung dieses Nachtrags ist damit nicht behauptet.

## Update 0.2.10

Morgen-/Abenddämpfungen sind pro String in Modell und Einrichtung ergänzt, mit neutralen Altdefaults und Anwendung vor gemeinsamer AC-/DC-Begrenzung. Das bestehende Horizontmodell bleibt je String konfigurierbar. [AS-UI-001](geplante-updates.md) ist umgesetzt: neue Einträge mit einer Ausgangsstufe erzeugen ein Gerät; bestehende Gesamt-Sensoren bleiben unter ihren IDs als ausgeblendete Kompatibilitätsanzeigen am Einzelgerät erhalten. Mehrere Ausgangsstufen behalten Einzel- und Gesamtanzeigen. [Versionsinformationen](release-0.2.10.md).

Je **893 Tests ohne Fehler oder Skips** bestanden mit Core **2026.10.2/.3/.4**, Testplugins **0.13.373/.374/.375**, Python 3.14.4/glibc. Laufzeiten: **95,96 / 93,99 / 94,61 Sekunden**. Drei Kopien der bestehenden Prüfumgebungen wurden regulär mit demselben 0.2.10-Wheel installiert; ursprüngliche Umgebungen blieben unverändert. Isolierter Paketimport und sämtliche **22 Paketdateien einschließlich Markenbild** wurden außerhalb des Repositorypfads gegen den Wheel geprüft; `pip check` jeweils erfolgreich. Belege: `artifacts/compatibility-ha-2026.10.2-0.2.10-r2/` und entsprechend .3/.4.

Die Migrationstests prüfen AC/DC, mehrere Strings je Stufe, stabile Entity-/Unique-IDs und Benutzeranpassungen, native Energy-Ausgaben und unveränderte Messhistorie nach Reload sowie wiederholte Einzel-/Mehrfachstufenwechsel. Die Physiktests prüfen Dämpfungsgrenzen, Neutraldefaults, Zeitumstellungen, Mitternacht überschreitende Sonnentage, Polartag/-nacht und die Reihenfolge vor dem gemeinsamen Clip. Diese Nachweise ersetzen keine reale Genauigkeitsauswertung.

### Produktive Rücklese vom 26.10.2026

Die Veröffentlichung `v0.2.10` wurde nativ aus dem öffentlichen GitHub-Repository in HACS registriert und heruntergeladen; kein manueller Ersatz der ausgelieferten Komponentenbytes. Alle 22 Dateien stimmen mit dem geprüften Stand überein. Nach einer neuen geschützten Sicherung und einem Core-Neustart sind alle vier Einträge geladen. Drei Optionsflows übernahmen die passenden Open-Meteo-Horizont-/Dämpfungswerte; beim vierten Eintrag waren die entsprechenden Nullwerte bereits vorhanden. Die übrigen numerischen Einstellungen, Messbindungen und Energy-Präferenzen blieben erhalten.

Die Laufzeitrücklese bestätigt 80 unveränderte Entity-/Unique-IDs und Benutzeranpassungen bei vier Geräten statt acht. Alte Gesamtanzeigen bleiben als ausgeblendete Kompatibilitätsanzeigen am Einzelgerät. Die nächsten drei vollen lokalen Tage sind je Anlage vollständig, alle modellierten Leistungen innerhalb der nominellen Grenzen. Temperatur, Wind, Globalstrahlung und vorgesehene Leistungseingänge sind gültig; alle vier Anlagen melden Physik/kalt. HA-Konfiguration gültig, keine aktiven Repairs. Native GitHub-CI vor Installation auf Hauptbranch und Tag erfolgreich; die spätere Statusdokumentation ist von der eingefrorenen Implementierungsprüfung getrennt.

Bekannte nicht blockierende Hinweise: Core meldete die für 2027.10 angekündigte Abkündigung des verwendeten Geräte-Zuordnungszugriffs; die geprüften 2026.10-Versionen funktionieren. Eine bereits aus der Quellqualifikation bekannte MQTT-UTF8-Warngruppe trat beim Start erneut auf; nachfolgend sind alle benötigten Eingänge gültig. Es wird weder ein vollständig warnungsfreies Log noch die physische Zertifizierung der Quellen behauptet. Alte Komponentenbytes und die vier Historienstores vor der Korrekturübernahme sind zusätzlich lokal gesichert.

Die folgenden Abschnitte dokumentieren den historischen Stand 0.2.9 und dessen getrennte Nachweise.

Der erste vollständige Implementierungsreview der neuen Version fand zwei behebungsbedürftige Punkte: restaurierte Umweltsensor-/Leistungswerte im Nowcast und zusammengefasste Ablehnungsgründe kurzer beziehungsweise nicht prospektiver Trainingszellen. Beide sind in `8b40414` korrigiert und durch Regressionen abgedeckt. Der Featurevertrag v2 verwirft ältere unqualifizierbare Archivfeatures, erhält aber separat geprüfte Messintervalle und ausgegebene Tagesbeginn-Snapshots. Der erneute gebundene Grok-Review ist auf Commit `5a7da69` ohne Findings abgeschlossen; [Umfang und Hashbindung](review-findings.md).

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch Subagenten mit hohem Aufwand.

**Implementierung 0.2.9:** optionaler generischer Messgültigkeitseingang für jede AC-/DC-Stufe. Ohne Bindung bleiben alte JSON-Daten und Fingerprints erhalten; gesetzte Quellen trennen die Messprovenienz. Physik und Umweltdaten bleiben bei Messausfällen verfügbar. [Messgültigkeitsvertrag und Grenzen](measurement-validity.md).

| HA Core | Testplugin | Bestandene Tests | Laufzeit |
|---|---|---:|---:|
| 2026.10.2 | 0.13.373 | 852 | 92,17 s |
| 2026.10.3 | 0.13.374 | 852 | 92,15 s |
| 2026.10.4 | 0.13.375 | 852 | 92,70 s |

Null Fehler/Skips; Python 3.14.4/glibc, normale 0.2.9-Wheel-Installation in getrennten Kopien der geprüften Umgebungen. Isolierter Import außerhalb des Repositories, alle 21 installierten Paketdateien und `pip check` je Umgebung geprüft; frühere Umgebungen erhalten. JUnit und Versions-/Hashbelege: `artifacts/compatibility-ha-2026.10.2-0.2.9/` (entsprechend .3/.4). Testextra nun Core .4/Plugin .375. Ruff grün.

26 neue Messgültigkeitsfälle; acht zusätzliche unabhängige native HA-.3-Gegenfälle ohne zwingende Findings. Zwölf native HA-.4-Integrator-/Template-Fälle umfassen elf normale Sicherheitsfälle und einen ausdrücklich reproduzierten `update_entity`-Gegenfall. Ein bestandener Gegenfalltest belegt die dokumentierte Grenze, keine Sicherheit dieses Pollpfads. Lokale Belege: `data/measurement-quality-audit-20261025/`, `data/integrated-source-validity-20261025/`. Keine produktive Ausfallinjektion.

Von sieben Kernmodulen ändert sich nur die Datenklasse um das optionale Feld; Physik-/Lernalgorithmen und Binärabhängigkeiten bleiben unverändert. ZIP und Wheel sind mit allen 21 Komponenten verglichen (`artifacts/package-source-validation-0.2.9.json`). Buildbackend setuptools 84.2.1 in isolierter Umgebung. Kein neuer Musl-Lauf und kein nativer produktiver 0.2.9-Fit behauptet. Grok-4.7/high-Implementierungsreview ohne Findings im gebundenen Commit `38c05d5`: 79 vollständige Originale und sechs unveränderte Forschungsreferenzen, keine Kontextkürzung; [Nachweis](review-findings.md).

Historische Stände bleiben getrennt: 0.2.8 je 814 Tests und positiver Implementierungsreview im gebundenen Commit `0285445`; 0.2.7 je 752 Tests und zuvor installierter Stand. Der ursprüngliche 231er-Musl-Nachweis betrifft die damalige Kernfassung, nicht die neue Datenklasse. Unveränderliche Quellen/Belege unter `artifacts/releases/0.2.7-reviewed/` und `artifacts/releases/0.2.8-implementation-20261025T132350Z/`.

## 2. Live-Stand und Grenzen

Freigegebene Aktivierung von 0.2.9: frisches geschütztes Konfigurations-/App-Backup ohne Recorder-Datenbank vollständig gelesen und gehasht; alle 21 neuen Integrationsdateien und drei betroffenen Konfigurationsdateien zurückgelesen. Altcode und ursprüngliche Timerdatei liegen außerhalb der aktiven HA-Lader. Binärabhängigkeiten wurden nicht ersetzt. Genau ein Core-Neustart, anschließend native Subentry-/Optionsflows mit Eintragsreloads.

Core 2026.10.4/Python 3.14.9, Konfiguration gültig, null aktive Repairs und vier geladene Entries mit Prognosekurven. Der vollständige unabhängige Readback umfasst 75 Prüfungen: vier erhaltene Sites, exakt neun erlaubte Bindungsänderungen, 21 Codehashes, drei Quellenhashes und zwei native MQTT-Gültigkeitskonfigurationen. Temperatur, Wind und Globalstrahlung werden verarbeitet; bei niedrigem Sonnenstand bleibt die GHI-Korrektur aus. Der Abregelungseingang bleibt erhalten. Eine visuelle Prüfung der Verwaltungsoberfläche ist damit nicht belegt.

Zwei Paket-Leistungskopien mit genau zwei Recorder-Ausnahmen und zwei Gültigkeitssignale sind aktiv. Für die Originalintegrale ist eine Minute als maximales Teilintervall konfiguriert; fortschreitende Berichtszeiten bei unveränderten Nachtwerten und angenommene Null-Deltas sind nativ beobachtet. Die tatsächlichen Timer unterliegen der HA-Ereignisplanung. Der lokale Konfigurationsreview durch Grok 4.7/high hat nach drei Dokumentationskorrekturen im Kandidaten `439373b` keine Findings. Empfangs-TTL, Retain-/Cachepoll-Grenzen und bestehender Quellendrift bleiben dokumentierte Betriebsannahmen; dies ist keine physikalische Vollqualifikation.

Die freigegebenen Lernquellen sammeln neue Originalintervalle. Ein bewusst nur mit Leistung angebundener Eintrag erhält keine Energielabels. Alle Modelle benötigen weiterhin ausreichende qualifizierte Historie; es ist kein produktiver ML-Fit oder Genauigkeitsvorsprung belegt. Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage. Die aktuellen privaten Aktivierungs-/Readbackbelege liegen unter `data/activation-0.2.9-20261025/` und werden nicht veröffentlicht. Dieser Statusnachtrag ergänzt die geprüften Quellstände um aktuelle Betriebsnachweise und verändert keinen Modellcode.

Keine Energy-Umschaltung und kein dauerhafter Vergleichsjob. Die gesondert freigegebenen West-Referenzen wurden auf dieselbe Ausgangsgrenze angeglichen. Ein erster prospektiver Einmal-Capture enthält ausschließlich künftig vollständige gemeinsame Stunden; er gehört nicht zur vorab festgelegten Hauptkohorte. Ein lokaler90-Tage-Walk-forward mit60 Tagen Anlauf und30 Auswertungstagen ist abgeschlossen. Er verwendet nachträglich beschaffte ursprüngliche Wetterläufe und angenommene Verfügbarkeitszeiten; Messqualifikation und vollständige lernende Helios-Referenz fehlen. Er ist bedingte historische Diagnose, kein produktiver oder prospektiver Genauigkeitsnachweis. Private Parameter/Ergebnisse bleiben außerhalb Git/Review. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Die dokumentierte Erstveröffentlichung stellte Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereit. Sie änderte keine produktive HA-Installation. Der anschließend gültig abgeschlossene Implementierungsreview bindet Commit `0285445`, 76 vollständige Originale und sechs unveränderte Forschungsreferenzen; Umfang und Grenzen stehen im [Reviewnachweis](review-findings.md). Die lokale Aktivierung von 0.2.9 ist keine neue Veröffentlichung.

Vorprüfung dieser Erstveröffentlichung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
