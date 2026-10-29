# Dokumentation pflegen und auf Konsistenz prüfen

Stand: 29.10.2026. Einstieg ist der [Dokumentationsindex](../README.md),
die aktuelle Implementierung steht im Repository. Bei Abweichungen zuerst den
Code prüfen und anschließend die betroffenen Anleitungen gemeinsam aktualisieren.

## Ablage und Geltungsbereich

| Ort | Inhalt und Pflege |
| --- | --- |
| `README.md` | Kurzer Produkteinstieg, aktuelle dokumentierte Version und Hauptlinks |
| `docs/anwendung/` | Aktuelle Installation, Bedienung und Datenschutz |
| `docs/technik/` | Architektur und Datenverträge; historische Ausgangsverträge ausdrücklich kennzeichnen |
| `docs/archiv/` | Wiederverwendbare Anleitungen für den optionalen Archivbetrieb |
| `docs/entwicklung/` | Entwicklung, Review, Validierung und öffentliche Prüfzusammenfassungen |
| `docs/releases/` | Änderungen und Upgradegrenzen je Version |
| `docs/recherche/` | Grundlagen und Planung mit eigenem Recherche-/Codestand |
| `docs/historie/` | Historische Umsetzungslisten, ohne Anspruch auf aktuelle offene Aufgaben |
| `data/docs/betrieb/` | Ignorierte private Betriebs-, Installations- und Sicherungsprotokolle |

Öffentliche Anleitungen müssen ohne private Belege ausführbar und verständlich
sein. Beispiele verwenden fiktive Parameter. Laufzeitdaten und private Mappings
gehören unter `data/`, generierte Prüfberichte unter `artifacts/`, rohe
Reviewdateien unter `reviews/private/`. Keiner dieser Orte wird öffentlich verlinkt.
Eine lokal ignorierte Ablage benötigt die eigene private Sicherung; sie wird
nicht mit einem frischen Klon wiederhergestellt.
Vor dem Entfernen eines Worktrees private Dokumentation in die ignorierte Ablage
des Hauptcheckouts übernehmen. Archivort und Quellcommit im Projektgedächtnis
festhalten, ohne private Betriebsinhalte in das Gedächtnis zu kopieren.

Historische Review- und Releasebezüge behalten ihre ursprünglichen Hashes und
Grenzen. Beim Verschieben ändern sich Dateipfade und häufig relative Links;
alte Receipts qualifizieren die neuen Dateien deshalb nicht automatisch.
[Forschungsbezüge im Review](validierung.md#4-lokale-prüfung-und-review) bleiben
streng gebunden.

## Konsistenzprüfung bei Änderungen

1. Versionen aus `pyproject.toml` und Komponentenmanifest sowie HACS-Untergrenze
   mit README, Installation und aktuellen Versionshinweisen abgleichen. Historische
   Matrixprüfungen von der tatsächlich geprüften Releaseumgebung unterscheiden.
2. Neue Optionen, Sensorattribute, Dienste und Speicherfelder in Bedienung,
   Datenvertrag und Datenschutz nachführen. Messgates, Einheiten, Zeitbezug,
   fehlende Daten und Migrationsgrenzen ausdrücklich erhalten.
3. Relative Links und Überschriftenanker nach Verschiebungen prüfen, auch in
   Recherchetexten und AGENTS.md. Öffentliche Links dürfen keine ignorierten Dateien
   voraussetzen. Inhaltsverzeichnisse und den zentralen Index aktualisieren.
4. Betroffene Markdownseiten rendern und Tabellen, Codeblöcke und Navigation prüfen.
   In Recherchetexten einen historischen Stand nicht pauschal auf heute umdatieren;
   geänderte externe Sachbehauptungen anhand von Primärquellen neu prüfen.
5. Bei Pfadänderungen auch Helfer und Tests durchsuchen. Der Reviewhelfer bindet
   die sechs ursprünglichen Recherchedateien nun unter `docs/recherche/`.
   Dokumentation, nötige Helferanpassung und Validierung gemeinsam committen.

Hilfreiche lokale Suchen aus der Repositorywurzel:

```bash
rg --files -g '*.md'
rg -n '^#{1,3} ' README.md docs -g '*.md'
rg -n 'docs/|RESEARCH_FILES|\.md' scripts tests AGENTS.md
git diff --check
git check-ignore data/docs/betrieb/README.md
```

## Konsistenzabgleich vom 29.10.2026

Die Neuordnung trennt Forschung, aktuelle Verträge, historische Planung und
private Betriebsnachweise. README, Bedienung, Installation, Datenschutz und
Implementierungsvertrag sind auf 0.2.18 abgeglichen. Der Datenschutz- und
Persistenzvertrag nennen jetzt die optionalen Tagesbeginnkurven. Hinweise auf
einen unveröffentlichten Archivzweig wurden korrigiert; ältere Planungsbewertungen
behalten ihren historischen Codebezug. Private Betreiberbestätigungen und konkrete
Sicherungs-/Installationszustände sind aus den allgemeinen Anleitungen entfernt.

Die Originaltexte vor der Neuordnung sind lokal unter `data/docs/betrieb/` mit
Quellcommit und SHA256-Manifest erhalten. Bereits veröffentlichte Inhalte bleiben
in der Git-Historie und alten Tags sichtbar. Die lokale Auslagerung ist keine
rückwirkende Entfernung aus veröffentlichten Quellen.

Der Abgleich umfasst lokale Dokumentziele, Überschriftenanker, Markdownrendering,
die genannten Versions-/Speicherverträge und die Regressionen des Reviewhelfers.
Er ist keine vollständige neue Literaturrecherche, keine Live-HA-Prüfung und kein
neuer externer Integrationsreview.
