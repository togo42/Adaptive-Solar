# Adaptive Solar: Dokumentation

Die [Projektübersicht](../README.md) beschreibt Zweck und Einstieg. Die aktuellen
Anleitungen und Datenverträge beziehen sich auf **0.2.18**. Veröffentlichte
Versionen und historische Prüfungen stehen getrennt unter
[Releases](releases/README.md) und [Prüfnachweise](entwicklung/pruefnachweise.md).

## Installation und Anwendung

| Dokument | Inhalt |
| --- | --- |
| [Installation](anwendung/installation.md) | Voraussetzungen, HACS, manuelle Installation, Upgrade und Rückweg |
| [HAOS-Binärabhängigkeiten](anwendung/haos-installation.md) | Qualifizierter amd64-/Musl-Bau und persistente Bereitstellung |
| [Bedienung](anwendung/bedienung.md) | Einrichtung, Optionen, Sensoren, Energy und Fehlerbehebung |
| [Datenschutz](anwendung/datenschutz.md) | Datenflüsse, Speicherung, Diagnose und Löschgrenzen |

## Technik und Datenverträge

| Dokument | Inhalt |
| --- | --- |
| [Implementierungsvertrag](technik/implementation-contract.md) | Architektur, Zeit-/Messgrenzen, Physik, Lernen und Persistenz |
| [Tagesbeginnkurve](technik/day-start-curve.md) | Eingefrorene Stundenkurve, Attribute und Alt-Snapshots ab 0.2.18 |
| [Messgültigkeit](technik/measurement-validity.md) | Externe Quellenprüfung und Wiederanlauf |
| [Messkontinuität und Lernfenster](technik/measurement-learning.md) | Aktuelle Endpunktfenster, Herkunft und Rundungsbursts |
| [Messintervalle ab 0.2.13](technik/messintervalle-92-prozent.md) | Historischer Ausgangsvertrag; spätere Ergänzungen sind gekennzeichnet |
| [Ablehnungsdiagnose](technik/ablehnungsdiagnose.md) | Ziel-/Zeilendetails und echter Fit-Cutoff |
| [Direktstrahl-Verschattung](technik/adaptive-solar-verschattung.md) | Ursprüngliche Spezifikation mit späteren Vertragsverweisen |
| [Physik-/Schatten-/Nowcastoptionen](technik/physics-learning-options.md) | Aktuelle Kandidatenparameter und zeitliche Freigaben |
| [Früher Bias im Shadow](technik/early-bias-shadow.md) | Beobachteter Kandidat mit eigenen Gates |
| [Trainingsabdeckung offline prüfen](technik/learning-support-guard.md) | Separater Support-Guard-Kandidat im Entwicklungsstand; keine HA-Aktivierung |
| [Prognosereparaturen](technik/forecast-repairs.md) | Nachtstrahlung, Tagesstartprovenienz und Originalimport |
| [Fehlerbehandlung und Ressourcen](technik/forecast-resilience.md) | Fit-/Wetterfallback und geschützte Historie |
| [Modellvergleichsarchiv](technik/model-comparison-archive.md) | Prospektiv ausgegebene Modellarme und Auswertung |

## Optionaler Archivbetrieb

Diese Anleitungen sind allgemein verwendbar. Sie setzen einen bewusst eingerichteten
privaten Archivhost voraus; die Prognoseintegration benötigt diesen Host nicht.

| Dokument | Inhalt |
| --- | --- |
| [Archivbetrieb](archiv/archivbetrieb.md) | Aufnahme, eingefrorene Daten, Replay und Energiequantile |
| [Istwerte offline qualifizieren](archiv/istwert-qualitaetsadapter.md) | Entwicklungskandidat: Originalintervalle, explizite Quellenbindung und vollständige Stundenmasken |
| [Hostinstallation](archiv/archiv-host-installation.md) | Eigene Laufzeit, Dienste, Timer, Zugangsdaten, Platz und Sicherung |
| [HA-freie Hostlaufzeit](archiv/archiv-runtime-ohne-ha.md) | Installer, Paketgrenzen und strenge Replayprovenienz |
| [Hashablage](archiv/archiv-hashablage.md) | Verzeichnislayout, Migration und Rückweg |
| [Speicher-/Cursorvertrag](archiv/archive-storage-contract.md) | Originale, Transaktionen, Lücken, Pins und Retention |
| [Speicherung und Transport](archiv/archiv-speicherung-und-transport.md) | Originaldateien/SQLite und spätere Datenbankoptionen |

## Entwicklung und Validierung

- [Entwicklung](entwicklung/entwicklung.md): Umgebung, Tests, Beiträge und Veröffentlichung.
- [Validierung](entwicklung/validierung.md): prospektiver Messplan und hashgebundener Reviewablauf.
- [Vergleichsaufnahme](entwicklung/benchmark-aufnahme.md): Recorder-Istwerte und Referenzprognosen.
- [Prüfnachweise](entwicklung/pruefnachweise.md): historische Quell-/Releasebezüge und Aussagegrenzen.
- [Dokumentationspflege](entwicklung/dokumentationspflege.md): Ablageregeln und Konsistenzprüfung.
- [Historische Umsetzungsliste](historie/geplante-updates.md): abgeschlossene Import-/Anzeigeänderungen.
- [Logo und Gestaltung](branding.md).

## Recherche und Planung

- [Gesamtrecherche](recherche/solar-prognose-ml-recherche.md).
- [Werkzeuge und Dienste](recherche/solar-prognosemodelle-zusammenfassung.md).
- [Machine Learning](recherche/solar_ml_research.md).
- [Ensembles und hybride Ansätze](recherche/ensemble_hybrid_solar_forecasting.md).
- [Datenquellen und Feature Engineering](recherche/solarprognose_datenquellen_feature_engineering.md).
- [Strahlung und NWP](recherche/solarstrahlungsprognose_recherche.md).
- [Wettermodelle und Prognosehorizonte](recherche/wettermodelle-und-prognosehorizonte.md).
- [Historische Codeanalyse](recherche/adaptive-solar-analyse.md) und
  [Bewertung/Arbeitspakete](recherche/adaptive-solar-bewertung.md).
- [Physikvergleich und Archivplanung](recherche/physikvergleich-und-archivierung.md).

Recherchetexte tragen ihren jeweiligen Recherche-/Codestand. Literaturergebnisse
und Planungsvorschläge sind keine belegten Fähigkeiten der aktuellen Integration.

## Öffentliche und private Unterlagen

Öffentlich bleiben eigenständig verständliche Anleitungen, Datenverträge,
Releaseänderungen, Forschung und zusammengefasste Prüfstände. Konkrete Anlagen-,
Host-, Backup-, Installations- und Laufzeitprotokolle werden unter ignoriertem
`data/docs/betrieb/` geführt; Rohdaten, Tokens und private Reviewartefakte bleiben
ebenfalls außerhalb des öffentlichen Dateibaums.

Die am 29.10.2026 ausgelagerten Originaltexte sind lokal mit Quellcommit und
SHA256-Manifest erhalten. Das lokale Verzeichnis ist kein Bestandteil eines
frischen Klons. Bereits veröffentlichte Fassungen bleiben in der Git-Historie
und älteren Tags sichtbar. Die Neuordnung löscht oder überschreibt diese Historie nicht.
