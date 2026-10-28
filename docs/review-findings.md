# Reviewnachweise und fachliche Bearbeitung

## Abgeschlossener Vollreview des Entwicklungsstands

27.10.2026, **Codex GPT-6.1-Sol/high**, geprüfter Commit
`d1991da6a621c736abbc402bc2ebd7d5a715f707`: **mergeable, keine Findings**.
Vollständiger Textreview über **135 öffentliche Originaldateien**,
**1.842.921 Payloadbytes**, 31 Quelltextabschnitte und einen finalen
Bewertungsturn. Binäre Markenbilder liegen außerhalb der Textprüfung.

Der unabhängige Nachaudit bestätigt alle 32 abgeschlossenen Turns, unveränderte
Originaldateien und vollständige Payload-/Manifest-/Promptbytes, die tatsächliche
Endantwort, CLI-0.164.0-Bytes sowie native Modell-/High-Identität. Alle Aufrufe
entsprechen exakt den strikten 800k-Argumenten. Keine Compaction, Tools oder
Hintergrundaufgaben. **1364 Tests ohne Skips**, Ruff und Dependencycheck sauber;
Zeilenabdeckung 94,61 %, Zweigabdeckung 87,63 %, kombiniert 92,57 %.
Alle 30 Integrationsdateien stimmen byteweise mit dem isoliert installierten
Wheel überein; zwölf HA-/Kernimporte sind geprüft.

Receipt-SHA256:
`8163ebb6749d480a8481bd743a08e0ff36db5809dd393c85a051cad406c5f6dd`.
Review-SHA256:
`c99b0cb30bdfc7457bed6ddac38a8ad7213d49f7038d15de49ed53e0ce520ae9`.
Payload-SHA256:
`6f8f4688883aa0c4d35cb8c469c5edddc0ccf7f8ac07cf920a2a833006090358`.
Private Belege: `reviews/private/forecast-quality-20261027-codex-round7/`
und `artifacts/forecast-quality-closeout.json`.

Dieser Abschlussabschnitt und die zugehörige aktuelle Statusdokumentation
entstehen nach dem eingefrorenen Reviewtext; Implementierungs-, Test- und
übrige Dateibytes bleiben unverändert. Der Review erteilt keine produktive
HA-Freigabe und beweist keinen Prognosevorsprung. Während dieses Reviewabschlusses
erfolgten kein Push, Release oder produktiver Eingriff. Der anschließend ausdrücklich
beauftragte Release-/Installationsschritt ist im [Entwicklungsstand](entwicklungsstand.md)
separat nachgewiesen. Dabei trat der neue offene Startimportbefund
[AS-START-001](geplante-updates.md#as-start-001-kalten-wetter-physikimport-aus-dem-eventloop-nehmen)
auf; ein akzeptierter Review ersetzt die native Prüfung nicht.

## Entwicklungsnachtrag nach 0.2.14

Der ursprüngliche Arbeitsstand `d73fc4c` erhielt noch keine Freigabe. Ein
vollständiger Grok-4.7/high-Lauf bestätigte 29 Quelltextteile, scheiterte aber
beim Abschlussturn mit `max_tokens_truncation`: kein gültiges Reviewurteil.

Der alternative vollständige **Codex GPT-6.1-Sol/high**-Review desselben Standes
war transportgültig, aber **blocked**. 126 öffentliche Originaldateien,
1.731.723 Payloadbytes, 30 erfolgreich abgeschlossene Turns; exakte
Prompt-/Antwortbindung, Modell/High und null Compaction/Tools wurden nach dem
Abschluss unabhängig erneut geprüft. Receipt-SHA256:
`d7073a885733e1c89f12610ee48aec3c980e64f874984e81c5bdedea79acc71f`.

Die drei Findings wurden mit gezielten Regressionen bearbeitet:

- **AS-001 (hoch):** Mindesthistorie und Tagesgewinnprüfung verwenden jetzt
  dieselben Tage, an denen sämtliche geplanten Origins des Stufen-/
  Horizontstratums vollständig gepaart sind. 29 vollständige von 30 deklarierten
  Tagen reichen auch ohne optionalen Bootstrap nicht aus.
- **AS-002 (mittel):** Beide Aufrufe zur Schattenkohortenbestimmung erhalten
  die ursprünglichen Wetterintervalle. Bei Teilintervallintegration wird die
  interne Zeitform damit über dieselbe Stütze wie die operative Prognose
  normiert. Regressionen prüfen Rohphysik und GHI-Anpassung.
- **AS-003 (niedrig):** Die Vergleichsdokumentation beschreibt den ersten
  tatsächlichen Versuch ab 18 Uhr einschließlich Ausfall; ein späterer Erfolg
  ersetzt diesen Tagescapture nicht.

Der zusätzliche eigene Ende-zu-Ende-Review fand verlorene gemeinsame
Forecast-Origins durch zellweise Archivverdichtung. Die zeitliche Paarauswahl
erhält jetzt tatsächlich gemeinsam ausgegebene Nachbarzellen. Regressionen mit
wiederholtem echtem Archivierungsablauf prüfen NWP-Lead-Bins, GHI, eindeutige
Messstunden sowie die Budgets bei einer, vier und sieben Stufen.
[Vertrag und Grenzen](measurement-learning.md).

Der zweite gültige **Codex GPT-6.1-Sol/high**-Nachreview von `9e85391`
blockierte noch einen Messkonfliktfall (AS-001 dieser Runde, mittel): Links
beginnenden beziehungsweise rechts endenden überlappenden Messstücken wurde
vor der Auswahl ganzer Stundenstücke nicht ausreichend Rechnung getragen.
Die Korrektur erstellt einen gemeinsamen, nach tatsächlicher Verfügbarkeit
gefilterten Intervallindex. Die Konfliktprüfung erfolgt vor dem Randbeschnitt;
unabhängige saubere Stunden und Endpunktfenster bleiben nutzbar. 15 neue
Regressionen prüfen beide Ränder, Verschachtelungen, Restore, Zukunftsreceipts
und den Aufwand. Ein unabhängiger Gegencheck bestätigt 63.000 Abfragen gegen
eine einfache Referenzberechnung. Dieser zweite Lauf bleibt ein historischer
blockierender Befund, kein positiver Nachweis.

Der dritte gültige **Codex GPT-6.1-Sol/high**-Nachreview von `18dbbd2`
fand einen weiteren Speicherfehler (AS-001 dieser Runde, mittel): HA kann
syntaktisch beschädigtes JSON beim normalen Store-Laden umbenennen und `None`
zurückgeben. Die Integration behandelte dies wie einen fehlenden Hauptspeicher
und konnte dadurch eine alte Legacy-Historie übernehmen und den Hauptspeicher
neu beschreiben. Der Lauf umfasste 129 Originaldateien, 1.766.544 Payloadbytes
und 31 erfolgreiche Turns. Der unabhängige Nachaudit bestätigt Prompt-/
Antwortbindung, Modell/High und null Compaction/Tools; Receipt-SHA256:
`050faf278867bc4841125bc3f52b2b01dcf782bc0bb4ad0d7678f6e4843ba522`.
Die 1256 Tests dieses Standes deckten beschädigte Inhaltsdaten ab, aber nicht
diesen nativen Dateifehler. Auch dieser Review bleibt ein blockierender Befund.

Die Korrektur liest Primary und Legacy jeweils ohne verändernde HA-Load-
Operation im Executor. Nur eine wirklich fehlende Primärdatei erlaubt den
Legacy-Pfad; vorhandene beschädigte oder unbekannte Dateien bleiben unverändert
und sperren die Hauptpersistenz. 23 neue Fälle prüfen native Dateifehler,
Storehüllen, lesbare ältere Hüllen, reguläre Migration, neutrale Physik,
Schreibsperren und einen tatsächlichen verzögerten Save. Die bisherigen
Restoretests verwenden jetzt reale Dateien statt vorgefertigter Ladeantworten.
Der unabhängige Gegencheck fand und behob zusätzlich einen Fixturefehler bei
der Auswertung verzögerter Datenfunktionen; diese werden genau einmal ausgeführt.

Der vierte gültige **Codex GPT-6.1-Sol/high**-Nachreview von `1beb9da`
fand einen Fehler im Istwert-Capturewerkzeug (AS-001 dieser Runde, mittel):
Spätere negative Qualitätsevidenz für eine Teilstunde wurde nur als fehlende
Vollstundenfreigabe behandelt. Dadurch konnte ein älteres positives Stundenlabel
im Vergleich weiterverwendet werden. Dieser Lauf umfasste 131 Originaldateien,
1.784.219 Payloadbytes und 31 erfolgreiche Turns; der unabhängige Audit bestätigt
Modell/High, exakte Prompt-/Antwortbindung und null Compaction/Tools.
Receipt-SHA256:
`b69e0beb77212ef317e467d1cc37fbd3b26538c4bb4c90c91f6fbaf01aa5ce5f`.
Die **1279 Tests ohne Skips** und die Paketprüfung dieses Standes deckten diesen
Revisionsfall noch nicht ab. Seine kombinierte Komponentenabdeckung betrug
**92,48 %**; auch dieser Review bleibt ein historischer blockierender Befund.

Der gezielte unabhängige Gegencheck bestätigte zwei verwandte Pfade: Eine
negative Maske außerhalb des aktuellen Recorder-Abruffensters kann eine ältere
archivierte Stunde betreffen. Außerdem konnte ein positives Inline-Istlabel aus
`payload.actuals` eine negative Revision in `--actual-captures` umgehen. Diese
Fälle werden gemeinsam mit dem ursprünglichen Befund durch zeitlich verfügbare
Negativrevisionen über tatsächlich archivierte Stunden und eine explizite
Trennung der CLI-Istquellen abgesichert.

Auch explizit ungültige oder geänderte vorhandene Recorder-Vorlaufwerte müssen
ältere akzeptierte Stunden mit ihrer tatsächlichen Rohrevision konfrontieren.
Die native HA-Quellprüfung unterscheidet sie von bloß fehlendem Abfragekontext.
Vollständige metadatengültige Summen werden nur gegen bestehende Stundenlabels
verglichen; fehlende oder identische Vorläufe erzeugen weder neue Labels noch
eine Wiederfreigabe. 53 neue Revisionsfälle und vier CLI-Fälle ergänzen die
bestehenden Tests. Ein unabhängiger Gegencheck bestätigt 110 Ablaufprüfungen
und 4.729 Maskenindexvergleiche gegen eine einfache Referenzberechnung.

Der damalige gemeinsam korrigierte Stand bestand lokal **1336 Tests ohne Skips**,
Ruff und die Paketprüfung. Seine kombinierte Komponentenabdeckung betrug **92,48 %**.

Der fünfte gültige **Codex GPT-6.1-Sol/high**-Nachreview von `44aec9d`
fand zwei weitere Fehler mittlerer Schwere. **AS-001**: Bei einer über Mitternacht
laufenden Berechnung konnte der vor dem Executor gesetzte Ausgabezeitpunkt eine
erst danach verfügbare Tagesstartprognose zulassen. Derselbe Verfügbarkeitsfehler
betrifft Trainingszellen an normalen Stundengrenzen. **AS-002**: Der
Vergleichsloader verwendete für fehlende Dateien noch `exists()` und erkannte
deshalb einen vorhandenen defekten Symlink fälschlich als neuen Speicher.
134 Originaldateien, 1.817.258 Payloadbytes und 32 erfolgreiche Turns wurden
vollständig geprüft. Der unabhängige Nachaudit bestätigt die Quell-/Promptbindung,
Modell/High und null Compaction/Tools; Receipt-SHA256:
`626e266247f610a6cc1475c8b417bb074611f3fe8f854fe255a4b4cc8083c484`.
Dieser Lauf bleibt ein historischer blockierender Befund für den damaligen Stand.

Die Korrektur prüft für neue Tagesstartwerte und Trainingszellen zusätzlich
die tatsächliche lokale Verfügbarkeit des vollständig zurückgekehrten
Executor-Ergebnisses. Der ursprüngliche Berechnungsissue bleibt erhalten;
historische Werte oder Operatorimporte werden nicht nachträglich umgedeutet.
Der Vergleichsloader erlaubt eine Neuanlage nur bei echter Abwesenheit des
Verzeichniseintrags gemäß `lstat()`. Vorhandene defekte Symlinks bleiben nach
Setup, Capture, Save und Close schreibgeschützt erhalten.

Der damalige erneut korrigierte Stand bestand **1349 Tests ohne Skips**, Ruff und die
Paketprüfung. Zeilenabdeckung **94,61 %**, Zweigabdeckung **87,63 %**, kombinierte
Komponentenabdeckung **92,57 %**. Zehn neue Executor-/Archivierungsfälle und drei
Dateisystemregressionen ergänzen die bisherigen Tests; ein unabhängiger Gegencheck
bestätigt DST, Trainingszellen, vorhandene Snapshots und Operatorimporte.

Der sechste Codex-Lauf von `2f78698` ist **kein gültiger Review**: Der
Kontextaudit brach mit ungültigen `token_usage_record`-Metadaten ab; die native
Sitzung enthält eine tatsächliche Compaction und nennt ein effektives
Kontextfenster von 475.000 Tokens. Auch der Reviewer selbst meldete einen
unvollständigen, komprimierten Quellkontext und keine Mergefreigabe. Daraus
folgt weder ein positiver Nachweis noch ein neuer bestätigter Codebefund.
Der vollständige Quellumfang muss mit ausreichend großem, nativ überprüftem
Kontext erneut gelesen werden; diese Sitzung wird nicht als Referenz verwendet.

Der Reviewhelfer fordert für neue Codex-Aufrufe deshalb 800.000 Kontexttokens
an; Grok bleibt bei 500.000. Historische 500k-/800k-Codex-Referenzen werden
ausschließlich mit ihren exakt gebundenen Budgetwerten und unveränderten
strikten Flags akzeptiert. Scope, Quell-/Prompt-/CLI-Hashes sowie die Ablehnung
von Compaction, Tools oder unvollständigem Abschluss bleiben unverändert.
Ein echter einzelner Konfigurationsprobelauf mit Codex 0.164.0 und
GPT-6.1-Sol/high bestätigt 760.000 effektive Tokens, einen abgeschlossenen Turn
und null Compaction/Tools. Er enthält keinen Quellreview und erteilt keine
Mergefreigabe. Private Belege: `reviews/private/forecast-quality-codex-800k-probe/`.
176 Transporttests und 14 zusätzliche unabhängige Gegenchecks prüfen die
Budgetbindung, historischen Referenzen und die unveränderten Sperren.

Die anschließende Gesamtsuite besteht **1364 Tests ohne Skips**; Ruff und
Diffprüfung sind sauber. Die Komponentenabdeckung bleibt **92,57 %**. Alle
30 Integrationsdateien sind seit `2f78698` unverändert und entsprechen weiterhin
dem isoliert installierten und geprüften Wheel.

Die in diesem Entwicklungsnachtrag beschriebenen früheren Läufe sind keine
Freigabe späterer Korrekturen. Der gültige aktuelle Vollreview ist im
vorangestellten Abschlussabschnitt an seine tatsächlichen Quellen gebunden.
Rohpayloads und native Sitzungsbelege bleiben unter ignoriertem `reviews/private/`.

## Gültiger Grok-Nachreview der Ablehnungsdiagnose

27.10.2026, **Grok 4.7/high**, Arbeitsstand auf Basis `1634e08`:
**mergeable, keine Findings**. AS-001 aus dem ersten Lauf ist behoben und
erneut geprüft. Vollständiger Textreview über **106 öffentliche Originaldateien**,
einschließlich aller sechs Forschungstexte und beider Lizenzkopien,
**1.446.687 Payloadbytes**, `all/chunks` mit 25 Textabschnitten und einem finalen
Reviewaufruf. Binäre Bilder sind außerhalb des Textreviews.

Native Kontextprüfung nach Abschluss unabhängig wiederholt: alle 26 Turns
erfolgreich, `grok-4.7` mit Effort `high`, exakte Benutzer-Promptbytes und
tatsächliche Endantwort. Keine Compaction, Tools oder aktiven Hintergrundaufgaben.
Quell-, CLI-1.0.62-, Payload-, Prompt-, Stdout-/Stderr- und Reviewhashes geprüft.
**1057 Tests ohne Skips**, Ruff und Dependencycheck erfolgreich; zusätzlich
20 bestehende Verbrauchertests und vier aus dem Producer erzeugte Vertragsfälle.

Receipt-SHA256: `4440e49db1b0ebb26e61f962f3f2941799d4abb40e93d610d8dcc6de77a41610`;
Review-SHA256: `495b496b8f36533beda3a9b3a4fa23ac263d3ec3fb157a885628c776374f3fd7`;
Payload-SHA256: `58f5aa5f866ddb9aefbb858b94ff9539005ff5e8461ab6fc72a12545cbae38a4`.
Rohbelege: `reviews/private/rejection-details-20261027-round2/`;
unabhängiger Nachweis: `artifacts/rejection-details-20261027/review-closeout.json`.
Diese nachträgliche Nachweisdokumentation liegt außerhalb des eingefrorenen
Reviewtexts; geprüfte Implementierungs- und Testbytes bleiben unverändert.
Ein Release, Push und HA-Update sind anschließend ausdrücklich beauftragt;
sie benötigen eigene Paket-, CI- und Laufzeitnachweise. Der Review belegt
keinen Prognosevorsprung.

## Lokale Ablehnungsdiagnose: erster Review und Doku-Korrektur

27.10.2026, **Grok 4.7/high**, Arbeitsstand auf Basis `1634e08`:
**blocked**, ein Befund mittlerer Schwere (**AS-001**). Der vollständige
Textreview umfasst **106 öffentliche Originaldateien**, einschließlich aller
Forschungstexte und beider Lizenzkopien, **1.443.131 Payloadbytes**, `all/chunks`
mit 25 Textabschnitten und einem finalen Aufruf. Binäre Bilder sind außerhalb
des Textreviews. Es wurden keine Implementierungsfindings gemeldet.

Der Forschungstext `solarprognose_datenquellen_feature_engineering.md`, Abschnitt 6,
nannte noch die früheren 95-%-/2,5-%-Projektgates. Der Absatz ist auf mindestens
92 % der ursprünglichen Zieldauer und höchstens 180 Sekunden je Rand korrigiert;
die relative Randregel ist ausdrücklich abgelöst und der lokale, noch nicht
installierte Stand verlinkt. Die übrigen 95-%-Angaben in der Validierungsdoku
bezeichnen statistische Familienkonfidenz und bleiben unverändert.

Der native Kontextaudit wurde nach Abschluss unabhängig wiederholt: alle
26 Abschlussturns erfolgreich, `grok-4.7` mit Effort `high`, exakte Promptbytes
und tatsächliche Endantwort, keine Compaction, Tools oder aktiven
Hintergrundaufgaben. Unveränderte Quellen, Payload, Prompts und CLI 1.0.62
sowie Stdout-/Stderr-/Reviewhashes geprüft.

Receipt-SHA256: `7e245fd3ef1f88d9dfb6be2ec14082e17596e15e914157acf7a7cfdb6e3008fb`;
Review-SHA256: `b18235eca443e37a5951d5183485267e5c32755dc9b27a9545479a75a8b85a41`;
Payload-SHA256: `f98742b5942bf355105d7c7c9f85a9de683159b819cf53085cacd72434ff0177`.
Lokale Belege: `reviews/private/rejection-details-20261027-round1/` und
`artifacts/rejection-details-20261027/review-round1-closeout.json`.

Zum Abschluss dieses ersten Laufs stand ein frischer, gültiger Nachreview noch
aus; der oben gebundene zweite Lauf hat AS-001 inzwischen bestätigt behoben.
Diese Korrektur und die nachträgliche Nachweisdokumentation liegen außerhalb
des eingefrorenen ersten Reviewtexts; die Implementierungs-/Testbytes bleiben
unverändert und die **1057 bestandenen Tests ohne Skips** weiterhin gebunden.
Kein Release, Push, Deploy oder Nachweis verbesserter Prognosegüte.

## Gültiger Grok-Nachreview des korrigierten GHI-Paar-Gains

26.10.2026, **Grok 4.7/high**, Commit `507ab4ecf5af0c205038ca15716f055def00a433`:
**mergeable, keine Findings**. Der vollständige Textreview umfasst **100 öffentliche
Originaldateien**, einschließlich aller sechs Forschungsdateien und beider
Lizenzkopien, **1.365.834 Payloadbytes**, `all/chunks` mit 23 Datenabschnitten und
einem finalen Reviewaufruf. Binäre Bilder sind außerhalb des Textreviews.
Der vorangegangene AS-001-Befund zum Schatten-Decay ist damit behoben und erneut geprüft.

Der native Kontextaudit wurde nach Abschluss unabhängig wiederholt: `grok-4.7`,
Effort `high`, 24 eindeutige erfolgreiche Abschlussturns, exakte Promptbytes und
tatsächliche Endantwort; keine Compaction, Tools oder aktiven Hintergrundaufgaben.
Quellsnapshot, unveränderte CLI 1.0.62, Payload, sämtliche Originaldateien, Prompts,
Stdout-/Stderr- und Reviewhashes erneut geprüft. Erfasste globale Grok-Konfiguration
während des gesamten Laufs unverändert.

Receipt-SHA256: `98bc3f6dead25e76fc2acd32eb6281526d693b058ba570888395504a23656027`;
Review-SHA256: `a25d2d3c6618422d0f6d6e1ca6f5c6927cd427bcb76adaf5e5b654b7ba5faeb8`;
Payload-SHA256: `0f2a44b9cfa34e34c5d48e259db3f9e890febd9a6b137f8a07a3493fa92ef20c`.
Lokale Rohbelege: `reviews/private/grok-ghi-pair-gain-fix-r1/`;
unabhängiger Abschlussnachweis: `artifacts/grok-ghi-pair-gain-fix-closeout.json`.
Diese nachträgliche Statusdokumentation liegt außerhalb des eingefrorenen Reviewtexts;
die geprüften Implementierungsbytes bleiben unverändert. Tests und Review belegen
keinen Prognosevorsprung und autorisieren keine produktive HA-Änderung.

## Korrektur des GHI-Paar-Gains und erneute Prüfung

Der nachfolgende Grok-Befund AS-001 ist im neuen Arbeitsstand korrigiert:
`shade_reference_powers` verwendet den vollen normierten GHI-Paar-Gain ohne
zeitliche Dämpfung. Der veröffentlichte Leistungsnowcast behält seinen bisherigen
Decay. Regressionsfälle prüfen beide Gainrichtungen (0,6/1,4), frühere,
gleichzeitige und spätere GHI-Paare sowie AC/DC-Ausgänge anhand unabhängig
berechneter `P0/P1` und eines konstanten gelernten Faktors 0,45. Zwei weitere
Gegenproben sichern den unveränderten Decay der Nowcast-Referenz ab. Vor der
Korrektur scheiterten die vier Fälle mit älterer GHI-Meldung erwartungsgemäß.
Lokale Validierung: **101 gezielte Tests**, anschließend **978 bestandene Tests
ohne Skips** unter HA Core **2026.10.4** / Testplugin **0.13.375**; Ruff,
`pip check`, Markdown-Rendering, relative Dateilinks und `git diff --check`
erfolgreich. JUnit-Beleg: `artifacts/ghi-pair-gain-fix-ha-2026.10.4-tests.xml`.
Der vorstehend gebundene externe Nachreview prüft diesen korrigierten Stand;
frühere Receipts gelten ausschließlich für ihren jeweiligen Quellstand.

## Historischer Grok-Vollreview des Schattenlernstands `ae5a56b`: blockiert

26.10.2026, **Grok 4.7/high**, Commit
`ae5a56b0fa3d55d76859da55f452bf574f6c5bff`: **blocked**, damals ein offener Befund
mittlerer Schwere. Umfang: **100 öffentliche Originaltextdateien**, einschließlich
aller sechs Forschungsdateien und beider Lizenzkopien, **1.358.067 Payloadbytes**,
`all/chunks` mit 23 Datenabschnitten und einem finalen Reviewaufruf. Binäre Bilder
sind außerhalb des Textreviews.

**AS-001 (mittel), `core/engine.py`:** Die Schattenreferenz verwendet den gemeinsamen
Momentan-Proxy mit `allow_paired_future_ghi=True`. Ist die zulässig gepaarte GHI-Messung
älter als die Leistung, dämpft der Proxy ihren Gain dennoch mit der 30-Minuten-
Nowcast-Zeitkonstante Richtung 1. Diese kurzlebige Dämpfung lässt einen Wetterfehler
in `P0/P1` zurück und verzerrt dadurch den dauerhaft gespeicherten Schattenfaktor.
Die Richtung der Verzerrung hängt vom Gain ab. Codeprüfung und eine synthetische
Reproduktion bestätigen den Befund: Bei vier Minuten Abstand wird ein ungekappter
Paar-Gain von 0,6 als rund **0,64993** angewendet. Gleichzeitige Paare verdecken den
Fehler. Die damals **offene** Korrektur: Schattenreferenz mit dem vollen Paar-Gain rechnen,
Decay im veröffentlichten Nowcast erhalten und einen zeitversetzten Gegenfall ergänzen.
Lokaler Reproduktionsbeleg: `artifacts/grok-ae5a56b-as001-reproduction.json`.

Abschlussaudit unabhängig wiederholt: native Modellkennung `grok-4.7`, Effort `high`,
24 eindeutige erfolgreiche Abschlussturns, exakte Promptbytes und Endantwort,
keine Compaction, Werkzeugaufrufe oder aktiven Hintergrundaufgaben. Quellsnapshot,
CLI-, Payload-, Prompt-, Stdout-/Stderr- und Reviewhashes stimmen; erfasste globale
Grok-Konfiguration während des geprüften Laufs unverändert. Die frühere Einzelprompt-
Vorprüfung scheiterte lokal am 1.250.000-Byte-Limit. Ein Versuch mit CLI 1.0.70 wurde
wegen des unbekannten nativen Ereignisses `current_mode_update` geschlossen verworfen.
Der abgeschlossene Review nutzt die unveränderte, hashgeprüfte **CLI 1.0.62** in
einer neuen Sitzung; Auditregeln und globale Konfiguration wurden dafür nicht angepasst.

Receipt-SHA256: `3b553331d0d4f588a5ee17e53587cbda093f32ff8b3777350692713989caec38`;
Review-SHA256: `7d6f47ec4203a9de6e149ef756a6b3cc25901f6fbb23a55bd77d34c1b03be9c2`;
Payload-SHA256: `43d1eee388efb6757012ba72138801c552fdbf524b2f74f924442da6311a1ca0`.
Lokale Rohbelege: `reviews/private/grok-ae5a56b-cli62-full/`;
unabhängiger Abschlussnachweis: `artifacts/grok-ae5a56b-review-closeout.json`.
Diese nachträgliche Statusdokumentation liegt außerhalb des eingefrorenen Reviewtexts.
Der Review ist keine Freigabe und kein Nachweis eines Prognosevorsprungs.

## Lokaler Codeaudit der Änderungen seit `4ac18e2`

Stand: 26.10.2026. Der neue Arbeitsstand ergänzt die Direktstrahl-Schattentabelle,
deren Physik-/Nowcast-Anwendung, Persistenz, Diagnose und die Abstimmung mit dem
Residuallernen. Er ändert außerdem Istwert-Revisionen und den Codex-Reviewtransport.
Die folgenden Korrekturen sind ein lokaler Codeaudit; sie erteilen keinen neuen
externen Freigabenachweis und ändern die historischen Receipts nicht.

Die beiden letzten abgeschlossenen Reviews stammen von **Codex GPT-6.1-Sol/high**,
jeweils `all/chunks`, 100 öffentliche Originaldateien, Urteil **blocked** mit je drei
Findings. Die lokalen Archive `reviews/private/20261026T181410.618324Z/` und
`reviews/private/20261026T184424.953641Z/` wurden erneut anhand der nativen Sitzungen,
aller Promptbytes, des tatsächlichen Abschluss-JSON sowie der Payload-, Datei- und
Reviewhashes geprüft: keine Compaction, Tools oder Hintergrundaufgaben.
Das ist ein Nachweis dieser historischen Prüfungen, keine Freigabe neuer Quellen.

| Review / Befund | Bearbeitung und Gegenprobe |
| --- | --- |
| 18:14 UTC AS-001, hoch: NWP-Fehler als Schatten lernen | Eigenständige GHI-Momentanreferenz aller Kohortenmitglieder ist Pflicht, auch bei 10–15° Sonnenhöhe. Fehlende/zu schwache Referenzen verhindern Aufnahmen. Zusätzlich werden jetzt gekappte GHI-Normalisierungen ausgeschlossen. |
| 18:14 UTC AS-002, mittel: Medianrauschen verwirft Lernhistorie | Verschattete Baselines bleiben innerhalb der expliziten Toleranz 0,10 kompatibel; der Wechsel zwischen unverschattet und verschattet bleibt strikt. Synthetische Trainings-, Validierungs- und Kalibrierungsblöcke mit schwankenden Faktoren prüfen lernbare Historie ohne doppelte Schattenkorrektur. |
| 18:14 UTC AS-003, mittel: Holdout umgeht Schattenstützung | Holdout verwendet denselben Schattenrückfall wie die öffentliche Vorhersage; Kalibrierung verwendet nur unterstützte Anwendungen. Unbelegte verschattete Fenster dürfen das Aktivierungsgate nicht durch scheinbare Residualgewinne bestehen. |
| 18:44 UTC AS-001, hoch: Rohdatenreread überdeckt Qualitätsinvalidierung | Positive und negative Qualität werden nach ihrer eigenen Revision verglichen. Eine alte positive Maske bleibt nach neuer Invalidierung gesperrt, auch mit neuerem Recorderabruf. Tests prüfen beide Reihenfolgen, As-of-Grenzen und spätere echte Neuqualifikation. Zusätzlich laufen positive Qualitätsrevision und gültiger Rohdatenempfang unabhängig vorwärts, damit eine späte Prüfung alter Rohdaten neuere gültige Rohdaten nicht verdeckt. |
| 18:44 UTC AS-002, mittel: selbst erzeugter Store überschreitet Restoregrenze | Intervallaufnahme und jeder Speichervorgang erzwingen Retention und Zeilengrenzen, auch ohne erfolgreichen Wetterabruf und beim Beenden. Der Intervallindex wird neu aufgebaut; entfernte Lernhistorie invalidiert den Fit. Neustart am reduzierten Testlimit prüft normale sowie stundenübergreifende Zusatzintervalle, Wetterausfall, erhaltene Tages-Snapshots und anschließendes Koaleszieren. |
| 18:44 UTC AS-003, mittel: Revision passt nicht zum Worker-Snapshot | Revision wird gemeinsam mit Intervallen vor dem Executor-Aufruf eingefroren. Ein Bericht während der Übergabe erzwingt beim nächsten Refresh ohne weitere Ereignisse einen neuen Fit. Ein unveränderter dritter Refresh benötigt keinen weiteren Fit. |

Gesamtbewertung: Die Erweiterung trennt direkte Verschattung, Diffuslicht und
kurzlebige Beobachtungskorrekturen nachvollziehbar. Messhistorie und ausgegebene
Tages-Snapshots bleiben von inkompatiblen Forecastfeatures getrennt. Die zusätzlichen
Baseline-, Regime- und Holdoutregeln erhöhen allerdings die Komplexität und verlangen
ausreichend wiederkehrende Sonnenstandsfenster. Die 0,10-Toleranz ist eine deklarierte
Modellannahme, keine empirisch optimierte Schwelle. Der Fit-Schlüssel enthält auch
unfreigegebene Tabellensamples und garantiert daher keine messbare Refitersparnis.
Reale Forecastgüte, saisonale Übertragbarkeit und Laufzeitnutzen sind hier nicht
gemessen; der prospektive Vergleich gegen beide Referenzen bleibt offen.

Validierung: **107 gezielte Tests**, anschließend jeweils **964 bestandene Tests
ohne Skips** unter echtem HA Core **2026.10.3** / Plugin **0.13.374** sowie dem
Repository-Pin **2026.10.4** / Plugin **0.13.375**, Python **3.14.4**, pvlib
**0.16.1**, scikit-learn **1.9.1**. Zehn neue Regressionsfälle gegenüber dem
vorgefundenen Arbeitsstand. Ruff, `pip check` und `git diff --check` erfolgreich;
geänderte Markdowntexte gerendert und relative Dateilinks geprüft. Lokale
JUnit-Belege: `artifacts/review-fixes-20261026-tests.xml` (Core .3) und
`artifacts/review-fixes-20261026-ha-2026.10.4-tests.xml` (Core .4).
Zum Abschluss dieses lokalen Audits gab es keinen neuen externen Reviewlauf;
der danach beauftragte Grok-Review ist oben gesondert dokumentiert.
Keine Veröffentlichung und keine produktive HA-Änderung.

Stand: 26.10.2026. Der neue vollständige Review 0.2.11 erfasst die ergänzten
Anleitungen, die GPL-Lizenztexte und alle sechs konsolidierten Forschungstexte.
Ältere Urteile bleiben ausschließlich an ihre eingefrorenen Quellen gebunden;
die geänderte Forschung wird nicht über frühere Forschungs-SHAs geerbt.

## Gültiger vollständiger Review 0.2.11

Grok **4.7/high**, 26.10.2026: **mergeable, keine Findings** für Commit
`9070886a70e29a843189fa1b2a2fc76ecaae355a`. **96 öffentliche Originaltextdateien**,
alle sechs überarbeiteten Recherchen und beide GPL-Lizenztexte vollständig erneut
in einem Einzelprompt mit **1.147.460 Bytes**. PNGs sind außerhalb des Textreviews;
das bestehende Logo wurde separat visuell geprüft.

Nativer Audit: genau ein Prompt und erfolgreicher Abschlussturn, `end_turn`,
native Modellkennung `grok-4.7`, Effort `high`, null Compaction/Tools/Hintergrundaufgaben.
Originalquellen, CLI, vollständiger Prompt und tatsächliche native Endantwort wurden
zum Abschluss und unabhängig erneut geprüft. Globale CLI-Konfiguration bytegleich;
ausschließlich prozesslokale 500k-Kontextanforderung. Ein früherer kompaktierter
Versuch wurde verworfen, der gültige zweite Versuch war wegen AS-001 blockiert.
Die Korrektur und der Bestandsdatenvertrag sind im folgenden Abschnitt dokumentiert.

Receipt-SHA256: `7cd1c9f94dad7d51d4bae7dfd4cf96335f9aafcae9e595b158175a2eb75ab188`;
Review-SHA256: `646f38eaab21951d51b27f0bdc21ca376bbfb673387204dd556ce1bbadded1ff`;
Payload-SHA256: `0e8c01264b7b171b61e6b3bace5f18257b1ddd25f8efaed095b8e3ad1fbee12a`.
CLI 1.0.62, SHA256 `2a46d9e4d7ebd7a9cff7f95716714b19dad5f21dd2a497822400b1fb128969aa`.
Unabhängiger Nachweis lokal: `artifacts/release-0.2.11/accepted-review-closeout.json`.
Quellarchiv-SHA256 `a21bb7d326bf801dc3c457da5b8869fed94bceb5f0857ee8460980a81fcc9d62`.

Die spätere Statusdokumentation zu Prüfung, Veröffentlichung und Installation ist
außerhalb des eingefrorenen Reviewtexts; die Implementierung bleibt identisch.
Tests, Review und HA-Rücklese belegen keine Prognoseüberlegenheit. Der Review ersetzt
keine gesonderte produktive Quellenqualifikation oder Betreiberentscheidung.

## Vollreview 0.2.11: Befund und Korrektur

Am 26.10.2026 erhielt Commit `32d1d0e` im vollständigen neuen Grok-4.7/high-Review
(96 öffentliche Textdateien einschließlich aller sechs Recherchen und beider Lizenzen)
einen **blocked**-Befund AS-001 (hoch): wiederhergestelltes Abregelungssignal `off`
gab Lern-/Powerbeobachtungen frei. Transportprüfung erfolgreich: ein echter
Abschlussturn, null Kontextkürzung/Tools/Hintergrundaufgaben. Der Lauf ist kein
freigegebener Stand.

Korrektur: zentrale Statusprüfung lehnt restaurierte Signale ab; echte Entfernung
des Restore-Attributs definiert die neue Freigabegrenze. Native HA-Regressionsfälle
prüfen AC/DC, laufenden Betrieb und Monitoringstart nach Wiederherstellung, Power-
und Energie-Wiederanlauf. Vorhandene Intervalle bleiben auf ausdrücklichen Wunsch
und Bestätigung des Betreibers abregelungsfreier letzter Tage erhalten; neue Marker
werden alten Zeilen nicht zugeschrieben. [Upgradegrenzen](release-0.2.11.md#upgrade-von-0210).
Der korrigierte Stand ist durch den vorstehenden neuen Vollreview ohne Findings gebunden.

## 0.2.10: Implementierungsreview abgeschlossen

Am 26.10.2026 mit **Grok 4.7/high**, unverändertem CLI 1.0.62 und strikt geprüftem Einzelprompt abgeschlossen: **mergeable, keine Findings**. Geprüfter Commit: `5a7da69d98f4d8aea037dd45a53694a81c4a4393`. Umfang: **83 aktuelle Originaldateien** einschließlich Code, Tests, Dokumentation und Helfern; die sechs unveränderten Forschungstexte waren ausschließlich über einen erneut geprüften vollständigen Vorgängerreview gebunden. Kein erneuter Volltextreview der Forschung und keine PNG-Renderingprüfung.

Der vorherige gültige Lauf fand zwei Punkte: restaurierte Umweltsensor-/Leistungswerte im Nowcast und zusammengefasste Trainings-Ablehnungsgründe. `8b40414` behebt beide und führt den Featurevertrag v2 mit getrenntem Erhalt qualifizierter Messintervalle und Tagesbeginn-Snapshots ein. Anschließend bestanden je **893 Tests** unter Core 2026.10.2/.3/.4 und drei reguläre, bytegeprüfte Wheel-Installationen.

Transportaudit: ein tatsächlicher Abschlussturn, `end_turn`, native Modellkennung `grok-4.7`, Effort `high`, **keine Compaction, Tools oder Hintergrundaufgaben**; gesendete Promptbytes und Endantwort stimmen mit dem Receipt überein. Originalquellen und CLI blieben während des Laufs unverändert. Receipt-SHA256: `da2a9d20cb1df53b699d8e5b9847c8bbf3e8549215b3d5c4df85f0cac0560d53`; Review-SHA256: `ca5a8c00cc0bf44a3171b918fd096c7a2a06ac92884fa78240012e543d5db5cf`.

Diese nachträgliche Statusdokumentation gehört nicht zum eingefrorenen Prüftext; die ausgelieferten Implementierungsbytes bleiben mit dem geprüften Commit gebunden. Produktive Installation über HACS und Rückleseprüfung sind im Entwicklungsstand separat dokumentiert. Tests und Review beweisen keine reale Prognosegüte.


Stand: 25.10.2026. Historischer Implementierungsstand **0.2.7** mit positivem Vollreview; Implementierungsstände **0.2.8** (`0285445`) und **0.2.9** (`38c05d5`) mit positivem gebundenem Implementierungsreview. Die nachfolgende Statusdokumentation nennt deren unveränderlichen Umfang.

## Gebundener Implementierungsreview

Grok **4.7**, Effort `high`, 25.10.2026, 07:56–08:14 UTC: 79 vollständige Originaldateien, Urteil **mergeable**, null Findings. Ein Modellaufruf, erfolgreicher nativer Abschluss/Exit0, bytegleicher Benutzertext, null Compaction/Tools/Hintergrundaufgaben. Payload-SHA256: `0c53642d17feef997af7f92de8e0c998410c8b177fb0204bef4f12c3dd5d5cfa`.

Unveränderliche Quellen/Receipts: `artifacts/releases/0.2.7-reviewed/`; maschinenlesbare Bindung: `artifacts/review-summary-0.2.7.json`. Die späteren Änderungen erhalten einen eigenen Reviewreceipt, ohne den ursprünglichen Beleg umzuschreiben. [Verfahren](validierung.md#4-lokale-prüfung-und-review).

## Nachreview und Korrektur0.2.8

Der spätere79-Dateien-Vollreview ist transportgültig, aber mit **AS-001 (medium)** blockiert: `join_training(as_of=...)` meldete verspätete Beobachtungen als abgelehnt, gab sie jedoch als Samples zurück. Der separate Fit-Filter schloss sie weiterhin aus; kein produktiver Zukunftslabel-Trainingsvorfall ist belegt, Lernbindungen sind leer.

0.2.8 verwirft diese Zeilen vor Samplebau/Deduplizierung; Gleichheit am Stichtag und unvervielfachte Diagnostik bleiben erhalten. Der gültige neue Review ist nachfolgend gebunden. Unveränderte Nachlaufquellen/Receipts: `artifacts/releases/0.2.7-status-docs-blocked/`; Payload-SHA256 `6db275e7e2760a4d08561c26a649e3b4f09444ecbc24f0ef9717863af1a81565`.

## Ungültiger0.2.8-Lauf und aktueller Reviewumfang

Der erste0.2.8-Volltextlauf über79 Originaldateien wurde nativ kompaktiert und ist deshalb **ungültig**, unabhängig von einem möglichen Teilurteil. Sein unveränderliches Archiv liegt unter `artifacts/releases/0.2.8-context-window-invalid/`; Payload-SHA256 `75cc0cfbfded63776fbfa9ab27e0900fc61e50caaa785b3f5aaf7cac9cb0dbc2`.

Der neue Lauf nutzte das ausdrücklich ausgewiesene Implementierungsprofil: alle aktuellen Code-, Test-, Dokumentations- und Helferdateien vollständig; nur sechs bytegleiche ältere Forschungsdateien sind über den unabhängig erneut validierten positiven 0.2.7-Vollreview gebunden. Ihr Text wurde im neuen Lauf nicht erneut gelesen. Der gebundene Workspace enthält 82 öffentliche Textdateien, davon 76 vollständige Originale und sechs Forschungsreferenzen. Das PNG-Logo erhielt keinen visuellen Review. Strengere Transportprüfungen sichern vollständige Benutzerbytes vor der ersten Modellantwort und die direkte Ausführung der gebundenen CLI-Datei. 137 gezielte Tests und unabhängige Reproduktion dieser beiden Grenzen bestanden.

**Gültiger Abschluss:** Grok **4.7/high**, 25.10.2026, 13:25–13:44 UTC, Urteil **mergeable**, null Findings. Ein Modellaufruf, ein vollständiger Benutzereingang vor Modelloutput, ein erfolgreicher nativer Abschlussturn, Exit 0, keine Compaction/Tools/Hintergrundaufgaben. Modell-/Effortbeleg, vollständige Promptbytes, alle Quellen, unveränderliche Referenz und Endantwort wurden zum Abschluss sowie unabhängig erneut geprüft. Payload-SHA256 `85e12e119a548740c46509772d8eeff81700d0a5d674b5f1fba71dec9fbf2bef`; Receipt-SHA256 `48a47133fcae7ce6d1cc0ac8c81674b5b5e99568514d67b9cf8a5f6d1786fdda`. Lokaler Nachweis: `artifacts/review-summary-0.2.8-implementation-20261025.json`, eingefrorene Quellen/Review/native Belege: `artifacts/releases/0.2.8-implementation-20261025T132350Z/`. Dies ist kein erneuter Volltextreview der sechs Forschungstexte.

## Gültiger Implementierungsreview 0.2.9

Grok **4.7/high**, 25.10.2026, 14:32–14:44 UTC: **mergeable**, null Findings. Gebunden sind Commit `38c05d5`, 79 vollständige Originaldateien mit aktuellem Code, Tests, Doku und Helfern sowie sechs bytegleiche Forschungsreferenzen aus dem erneut unabhängig geprüften 0.2.7-Vollreview. Die sechs Forschungstexte wurden in dieser Sitzung nicht erneut gelesen, das PNG-Logo nicht visuell geprüft.

Ein Modellaufruf, vollständiger Benutzertext vor Modelloutput, erfolgreicher nativer Abschlussturn/Exit 0, null Compaction/Tools/Hintergrundaufgaben. Modell/High, Endantwort, Quellen, vollständige Prompts und Referenz wurden zum Abschluss und unabhängig erneut nachgeprüft. Payload-SHA256 `f4a2e1f2d6f6edd09de3687ecb3cbcf4cc9a936e60c1ed9643a400cc180feb44`; Receipt-SHA256 `db231084ae1fbf6e2d871a8d0ca1e96b9178d7d9ff4def7deb96fb01cbaea8e3`. Lokaler Nachweis `artifacts/review-summary-0.2.9-implementation-20261025.json`; unveränderliches Archiv `artifacts/releases/0.2.9-implementation-20261025T143145Z/`.

## Historische Bearbeitung

Gültige blockierende Vollreviews0.2.0–0.2.6 führten zu Korrekturen an Zeit-/Messgrenzen, Nowcast, Lernregimen, Persistenz, Vergleichsstrata und nativen Recorder-Einheiten. Die vollständige Bearbeitung vor diesem Statusupdate bleibt lokal unter `artifacts/releases/0.2.7-reviewed/source/docs/review-findings.md` erhalten. Frühere formal positive, durch Kontextkürzung ungültige Reviews werden nicht als Vollnachweis verwendet. [Aktueller Implementierungsvertrag](implementation-contract.md).

## Grenzen

[Live-Stand und Tests](entwicklungsstand.md): 0.2.11 über GitHub/HACS installiert, vier geladene Anlageneinträge unter Core 2026.10.4. Jeweils 900 bestandene Tests unter Core .2/.3/.4 und abgeschlossener Vollreview einschließlich der überarbeiteten Recherchen. Core-ML-Fit auf qualifizierter Messhistorie und fairer prospektiver Vorsprung gegenüber **beiden** Referenzen sind offen. Ein Review belegt keine Prognosegüte.

Archive und rohe Receipts bleiben lokal; die genannten `artifacts/`-Pfade sind keine öffentlichen Downloads. Die optionale Messgültigkeits-Erweiterung hat einen eigenen 0.2.9-Review, einen separaten unabhängigen Codeaudit und native Integrator-Gegenfälle. Die Testmatrix dokumentiert ausdrücklich auch eine außerhalb des sicheren Adaptervertrags liegende Zählerpoll-Sequenz. Der Review belegt den generischen Eingangsvertrag, keine konkrete produktive Quellenzuordnung. [Vertrag und Grenze](measurement-validity.md).

## Gültiger Grok-Review der Prognosereparaturen 0.2.14

Geprüfte Implementierung `af3df57`: **1102 Tests ohne Skips**, Ruff und Dependencycheck erfolgreich. Vollständiger Grok-4.7/high-Textreview über **111 Originaldateien**, 1,500,456 Payloadbytes und 27 erfolgreiche Turns: **mergeable, keine Findings**. Separater Nachaudit bestätigt identische Original-/Promptbytes, Quell-/CLI-Hashes, native Modell-/High-Identität, erfolgreichen Abschluss und null Compaction/Tools. Private Belege: `reviews/private/forecast-repairs-20261027-round2/` und `artifacts/forecast-repairs-20261027/review-closeout.json`; Receipt-SHA256 `56788cd17274a57645bbc676ded073ff07c8792625d6baf3aca949e93ce64724`.

Ein voriger Lauf wurde nach einem aktiven Self-Review-Befund zur nativen
HA-Speicherfehlerbehandlung durch die Quellkorrektur ungültig; er ist kein
akzeptierter Review. Der neue Lauf prüft die echte Dateirückleseprüfung und ihre
Regressionen erneut im vollständigen Kontext. Dieser Review ist weder HA-
Aktivierung noch Genauigkeitsnachweis.
