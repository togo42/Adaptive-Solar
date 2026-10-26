# Reviewnachweise und fachliche Bearbeitung

## Grok-Vollreview des Schattenlernstands `ae5a56b`: blockiert

26.10.2026, **Grok 4.7/high**, Commit
`ae5a56b0fa3d55d76859da55f452bf574f6c5bff`: **blocked**, ein offener Befund
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
Fehler. Die Korrektur ist **offen**: Schattenreferenz mit dem vollen Paar-Gain rechnen,
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
