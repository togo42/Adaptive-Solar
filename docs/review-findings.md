# Reviewnachweise und fachliche Bearbeitung

Stand: 25.10.2026. Historischer Implementierungsstand **0.2.7** mit positivem Vollreview; der aktuelle Stand **0.2.8** benötigt einen frischen gebundenen Review.

## Gebundener Implementierungsreview

Grok **4.7**, Effort `high`, 25.10.2026, 07:56–08:14 UTC: 79 vollständige Originaldateien, Urteil **mergeable**, null Findings. Ein Modellaufruf, erfolgreicher nativer Abschluss/Exit0, bytegleicher Benutzertext, null Compaction/Tools/Hintergrundaufgaben. Payload-SHA256: `0c53642d17feef997af7f92de8e0c998410c8b177fb0204bef4f12c3dd5d5cfa`.

Unveränderliche Quellen/Receipts: `artifacts/releases/0.2.7-reviewed/`; maschinenlesbare Bindung: `artifacts/review-summary-0.2.7.json`. Die späteren Änderungen erhalten einen eigenen Reviewreceipt, ohne den ursprünglichen Beleg umzuschreiben. [Verfahren](validierung.md#4-lokale-prüfung-und-review).

## Nachreview und Korrektur0.2.8

Der spätere79-Dateien-Vollreview ist transportgültig, aber mit **AS-001 (medium)** blockiert: `join_training(as_of=...)` meldete verspätete Beobachtungen als abgelehnt, gab sie jedoch als Samples zurück. Der separate Fit-Filter schloss sie weiterhin aus; kein produktiver Zukunftslabel-Trainingsvorfall ist belegt, Lernbindungen sind leer.

0.2.8 verwirft diese Zeilen vor Samplebau/Deduplizierung; Gleichheit am Stichtag und unvervielfachte Diagnostik bleiben erhalten. Frischer Review erforderlich. Unveränderte Nachlaufquellen/Receipts: `artifacts/releases/0.2.7-status-docs-blocked/`; Payload-SHA256 `6db275e7e2760a4d08561c26a649e3b4f09444ecbc24f0ef9717863af1a81565`.

## Ungültiger0.2.8-Lauf und aktueller Reviewumfang

Der erste0.2.8-Volltextlauf über79 Originaldateien wurde nativ kompaktiert und ist deshalb **ungültig**, unabhängig von einem möglichen Teilurteil. Sein unveränderliches Archiv liegt unter `artifacts/releases/0.2.8-context-window-invalid/`; Payload-SHA256 `75cc0cfbfded63776fbfa9ab27e0900fc61e50caaa785b3f5aaf7cac9cb0dbc2`.

Der nächste Lauf verwendet das ausdrücklich ausgewiesene Implementierungsprofil: alle aktuellen Code-, Test-, Dokumentations- und Helferdateien vollständig; nur sechs bytegleiche ältere Forschungsdateien sind über den unabhängig erneut validierten positiven0.2.7-Vollreview gebunden. Ihr Text wird im neuen Lauf nicht erneut gelesen. Der aktuelle Workspace enthält82 öffentliche Textdateien, davon76 vollständige Originale und sechs Forschungsreferenzen. Das PNG-Logo erhält keinen visuellen Review. Strengere Transportprüfungen sichern vollständige Benutzerbytes vor der ersten Modellantwort und die direkte Ausführung der gebundenen CLI-Datei.137 gezielte Tests und unabhängige Reproduktion dieser beiden Grenzen bestanden. Ein erfolgreich abgeschlossener aktueller Review steht aus.

## Historische Bearbeitung

Gültige blockierende Vollreviews0.2.0–0.2.6 führten zu Korrekturen an Zeit-/Messgrenzen, Nowcast, Lernregimen, Persistenz, Vergleichsstrata und nativen Recorder-Einheiten. Die vollständige Bearbeitung vor diesem Statusupdate bleibt lokal unter `artifacts/releases/0.2.7-reviewed/source/docs/review-findings.md` erhalten. Frühere formal positive, durch Kontextkürzung ungültige Reviews werden nicht als Vollnachweis verwendet. [Aktueller Implementierungsvertrag](implementation-contract.md).

## Grenzen

[Live-Stand und Tests](entwicklungsstand.md): 0.2.7, vier geladene Anlageneinträge unter Core 2026.10.4, aktuelle Prognosekurven geprüft. Entwicklungsstand 0.2.8 mit jeweils 814 bestandenen Tests unter Core .2/.3/.4. Core-ML-Fit auf qualifizierter Messhistorie und fairer prospektiver Vorsprung gegenüber **beiden** Referenzen sind offen. Ein Review belegt keine Prognosegüte.

Archive und rohe Receipts bleiben lokal; die genannten `artifacts/`-Pfade sind keine öffentlichen Downloads. Der veröffentlichte Quellstand 0.2.8 hat noch keinen frischen gebundenen Implementierungsreview.
