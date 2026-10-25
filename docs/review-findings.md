# Reviewnachweise und fachliche Bearbeitung

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

[Live-Stand und Tests](entwicklungsstand.md): 0.2.7, vier geladene Anlageneinträge unter Core 2026.10.4, aktuelle Prognosekurven geprüft. Entwicklungsstand 0.2.9 mit jeweils 852 bestandenen Tests unter Core .2/.3/.4. Core-ML-Fit auf qualifizierter Messhistorie und fairer prospektiver Vorsprung gegenüber **beiden** Referenzen sind offen. Ein Review belegt keine Prognosegüte.

Archive und rohe Receipts bleiben lokal; die genannten `artifacts/`-Pfade sind keine öffentlichen Downloads. Die optionale Messgültigkeits-Erweiterung hat einen eigenen 0.2.9-Review, einen separaten unabhängigen Codeaudit und native Integrator-Gegenfälle. Die Testmatrix dokumentiert ausdrücklich auch eine außerhalb des sicheren Adaptervertrags liegende Zählerpoll-Sequenz. Der Review belegt den generischen Eingangsvertrag, keine konkrete produktive Quellenzuordnung. [Vertrag und Grenze](measurement-validity.md).
