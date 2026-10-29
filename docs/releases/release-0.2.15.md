# Adaptive Solar 0.2.15

## Änderungen

- Kleine Zeitstempellücken bei belegter gleicher Messkontinuität: höchstens eine
  Sekunde einzeln und fünf Sekunden je Stunde ursprünglicher Zielfensterdauer.
  Fehlende Sekunden erzeugen keine Energie oder Messabdeckung. Reset, Neustart,
  ungültige Quellen und Abregelung bleiben Phasengrenzen.
- Zählerberichte im Minutenabstand: zusätzliche Lernfenster an echten erhaltenen
  Messendpunkten und längeres Warten auf einen tatsächlichen Folgebericht bei
  begrenzten Rundungsbursts. Fünf- und Zehn-Minuten-Takte sind getestet; weder
  künstliche Zählerberichte noch anteilig erfundene Energie werden erzeugt.
- Physikfallback bei fehlgeschlagenem Lernen, höchstens zwölf Stunden alter
  Wettercache bei Abruffehlern mit ursprünglichem Empfangszeitpunkt, geschützte
  defekte Historienstores sowie zusätzliche Laufzeit- und Ablehnungsdiagnosen.
- Zeitlich qualifizierte Schattentabelle und optionale Physik-/Nowcastparameter
  mit neutralen Standards. Ein kleiner früher Bias-Kandidat kann ab 14
  qualifizierten Tagen separat geprüft werden; er verändert keine operative
  Prognose. Das neue persistente Vergleichsarchiv trennt reale Modellarme.
- Spätere negative Qualitäts-/Rohrevisionen sperren widersprüchliche Istlabels.
  Erst nach Mitternacht oder Zielbeginn fertig berechnete Ergebnisse werden nicht
  rückdatiert als Tagesstartprognosen oder Trainingsinputs archiviert.
- CI prüft kombinierte Zeilen-/Zweigabdeckung der Komponente mit mindestens 90 %.

Details: [Messdaten](../technik/measurement-learning.md), [Robustheit](../technik/forecast-resilience.md),
[Bias-Kandidat](../technik/early-bias-shadow.md), [Physik und Schatten](../technik/physics-learning-options.md),
[Vergleichsarchiv](../technik/model-comparison-archive.md), [Istwertrevisionen](../entwicklung/benchmark-aufnahme.md)
und [Archivverfügbarkeit](../technik/forecast-repairs.md).

## Upgrade von 0.2.14 und Rückweg

Runtimepins bleiben pvlib 0.16.1 und scikit-learn 1.9.1; der Lernfeaturevertrag bleibt
`beam-shade-table-v1`. Kein Core-/OS-Upgrade. Nach dem HACS-Download einmal Core
neu starten. Vorhandene Optionen, Entity-/Unique-IDs, Geräte und Energy-Zuordnungen
werden weiterverwendet; zusätzliche Physik-/Nowcastoptionen bleiben zunächst neutral.

Passende gültige Mess-/Forecasthistorie und tatsächlich ausgegebene Tagesstartwerte
bleiben nach ihren bestehenden Bindungsprüfungen erhalten. Alte Daten erhalten
keinen erfundenen Kontinuitäts- oder Verfügbarkeitsnachweis. Frühere gültige
Schattenproben ohne belegte Beobachtungs-/Empfangszeit bleiben diagnostisch erhalten,
beeinflussen die neue Tabelle aber nicht. Schattenfreigaben brauchen neue
qualifizierte Proben. Bereits verworfene Messungen oder nie archivierte Forecasts
werden nicht rekonstruiert. Defekte/unbekannte Speicher bleiben schreibgeschützt;
`history_storage_status` erklärt den Zustand.

Vor dem Download aktuelle Komponente und Historienstores sowie eine native
HA-Sicherung anlegen. Der neue Store `adaptive_solar.<entry_id>.comparison_v1`
liegt getrennt von der Lernhistorie. Für einen Rückweg 0.2.14 über HACS erneut
installieren; falls die alte Historie benötigt wird, ausschließlich die gesicherten
Stores bei entladener Integration gezielt zurückführen. Eine ältere Version kann
neue Speicherinhalte nicht vollständig interpretieren. Eine Code-Rückkehr allein
ist deshalb kein Nachweis verlustfreier Datenrückmigration.

## Prüfstand und Grenzen

Geprüfte Implementierung `d1991da6a621c736abbc402bc2ebd7d5a715f707`:
**1364 Tests ohne Skips**, Zeilenabdeckung **94,61 %**, Zweigabdeckung **87,63 %**,
kombiniert **92,57 %** auf Python 3.14.4 / HA Core 2026.10.4. Ruff und Dependencycheck
sauber. Vollständiger unabhängiger Codex-GPT-6.1-Sol/high-Review:
**mergeable, keine Findings**, 135 Originaltextdateien, 1.842.921 Payloadbytes,
32 abgeschlossene Turns. Separater Nachaudit bestätigt Quell-/Prompt-/Antwortbytes,
Modell-/Effortbindung und null Compaction, Tools oder Hintergrundaufgaben.
Receipt-SHA256: `8163ebb6749d480a8481bd743a08e0ff36db5809dd393c85a051cad406c5f6dd`.

Die Releasevorbereitung ändert gegenüber diesem geprüften Funktionsstand nur
Versionsmetadaten und Dokumentation. Quell- und Testangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md); konkrete Installationsprotokolle
bleiben privat. Nachträgliche Statusangaben liegen außerhalb des eingefrorenen
Reviews. Tests, Review und Installation beweisen keine Prognoseüberlegenheit;
produktives qualifiziertes ML und ein Vorteil des frühen Bias-Kandidaten brauchen
weiterhin ihre prospektive Auswertung.

## Veröffentlichung

Historische Quell-, Test- und Veröffentlichungsangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md). Anlagenspezifische Installations-
und Laufzeitprotokolle werden privat geführt.
