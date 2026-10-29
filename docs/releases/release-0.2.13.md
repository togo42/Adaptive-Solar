# Adaptive Solar 0.2.13

## Änderungen

- Lernlabels brauchen mindestens 92 % Messabdeckung der ursprünglichen
  Zieldauer und höchstens 180 Sekunden fehlende Zeit an jedem Rand.
  Beide Bedingungen gelten gemeinsam; ursprüngliche Ziele bleiben mindestens
  halbstündig. Interne Lücken und unbekannte Randenergie werden nicht aufgefüllt.
- Der Join wählt den längsten gültigen zusammenhängenden Messblock. Ein früher
  kurzer Abschnitt verdeckt keinen längeren späteren Abschnitt mehr.
- Kleine unplausibel schnelle Zählerschritte können höchstens 60 Sekunden bis
  zu einem echten Folgebericht zurückgehalten werden. Nur die ganze plausible
  Differenz wird angenommen. Resets, Abregelung, Messungültigkeit, große
  Sprünge und Timeouts bleiben gesperrt; Energie wird nicht gekappt.
- Neue Diagnose `learning.<Stufe>.training_quality.rejection_details`, Schema 1:
  abgeschlossene abgelehnte Ziele sowie bereits gezählte abgelehnte Learner-Zeilen
  mit Originalzeiten, Gründen und bei Zeilen Ausgabezeit/Regime. Vollständige
  Rohzähler, höchstens 50 eindeutige Einträge je Gruppe; gleiche Schlüssel
  vereinigen Gründe, ungültige Originalzeiten sind `null`.
- Alignment und Detailgruppen bleiben bei Cachehits gemeinsam auf dem echten
  Cutoff des letzten Fits. Der schon gezählte Schatten-Kompatibilitätsfilter
  wird erklärt; andere spätere Filter und Validierungsgates erzeugen keine
  erfundenen Eingangsablehnungen. Fittrigger und Prognosemodelle ändern sich
  durch die Diagnose nicht.
- Aktuelle Forschungs-/Anwenderdokumentation ist mit diesen Regeln abgeglichen.
  Die dauerhafte Freigabe für Grok-Reviews des öffentlichen Repositoryumfangs
  steht in AGENTS.md; private Daten und Zugangsdaten bleiben ausgeschlossen.

## Upgrade von 0.2.12

Die Runtimepins bleiben pvlib 0.16.1 und scikit-learn 1.9.1. Die vorhandene
passende Musl-Binärbasis bleibt erhalten; kein Core-/OS-Upgrade erforderlich.
Nach HACS-Download Core einmal neu starten. Bestehende Optionen, Geräte,
Entity-IDs, AC-/DC-Grenzen und Energy-Verknüpfungen werden nicht geändert.

Der Featurevertrag bleibt **`beam-shade-table-v1`**. Passende Forecastarchive,
gemessene Intervalle, Schattentabellen und bereits ausgegebene Tagesbeginn-
Snapshots bleiben innerhalb der bisherigen Retentions-/Provenienzgrenzen
erhalten. Kein pauschaler Historienreset. Früher verworfene Zählerenergie wird
nicht rekonstruiert; neue Anker bleiben über Neustarts hinweg absichtlich kalt.

Vor Download Komponentenstand und Lernstores sichern. Gezielter Rückweg:
v0.2.12 erneut installieren; die gesicherten Stores nur bei tatsächlich nötiger
Rückkehr zur alten Historie und gestoppter Integration verwenden. Eine vollständige
HA-Wiederherstellung wäre ein separater Eingriff.

Die Diagnoseanzeige selbst wird im separaten Repository HA-Config gepflegt.
Dieses Release liefert die Modellschnittstelle und ändert keine Dashboardressource.
[Messregeln](../technik/messintervalle-92-prozent.md), [Diagnosevertrag](../technik/ablehnungsdiagnose.md).

## Prüfstand und Grenzen

Geprüfte Implementierung im Commit **`9259903`**: **1057 Tests ohne Skips** unter
Core 2026.10.4 / Testplugin 0.13.375, Ruff und Dependencycheck erfolgreich.
20 bestehende Verbrauchertests und vier erzeugte Producer-/Consumer-Vertragsfälle
bestanden. Neuer vollständiger Grok-4.7/high-Textreview über 106 Originaldateien:
**mergeable, keine Findings**; native Kontext-/Hashprüfung unabhängig wiederholt.
[Reviewbelege](../entwicklung/pruefnachweise.md).

Die Releasevorbereitung ändert Implementierungsbytes ausschließlich im
Versionsfeld des Manifests; Projektversion sowie Release-/Statusdokumentation
werden passend aktualisiert. Die übrigen Integrationsdateien sind bytegleich zum
geprüften Stand. Quell- und Testangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md); konkrete Installationsprotokolle bleiben privat.
Mehr akzeptierte Labels, bestandene Tests und ein Review belegen keinen
Prognosevorsprung oder bereits qualifiziertes produktives ML.

## Veröffentlichung

Historische Quell-, Test- und Veröffentlichungsangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md). Anlagenspezifische Installations-
und Laufzeitprotokolle werden privat geführt.
