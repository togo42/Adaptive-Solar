# Fehlerbehandlung und Ressourcen der Prognose

Diese lokale Implementierung ergänzt die bestehende Physik- und Lernpipeline.
Sie ist kein Nachweis besserer Prognosen und ändert keine produktive HA-Installation.

## Optionales Residualmodell

Jeder nötige Fit entsteht in einem neuen lokalen `ResidualLearner`. Erst nach
vollständig erfolgreichem Fit und erfolgreicher Prognoseberechnung übernimmt der
Koordinator den Learner und die zugehörigen Diagnosen gemeinsam. Scheitert der Fit,
bleibt die gültige Physikprognose verfügbar; ein vorheriger Learner wird dabei
nicht weiterverwendet. Der nächste Aktualisierungslauf versucht den Fit erneut.
Die Fehlerbehandlung umfasst ausschließlich das optionale Fitten: beliebige Fehler
der verpflichtenden Physikberechnung werden weitergegeben.

Die Fit-Wiederverwendung prüft neben Historienrevision, lokalem Datum und
Schattentabelle auch die tatsächlich verbundenen Trainingssamples und deren
Alignmentdiagnose. Dadurch erzwingen neu abgeschlossene Zielintervalle und neu
verfügbare Labels einen neuen Fit auch ohne zusätzliche Historienmutation.
Der Join wird weiterhin bei jedem Lauf berechnet. Ein pauschales Zeitthrottling
oder eine Wiederverwendung allein nach Revision würde Änderungen an der
As-of-Verfügbarkeit übersehen. Alle bisherigen Qualitäts- und Historiengates
bleiben erforderlich.

## Wettercache und Abruffehler

Der normale Wettercache gilt für weniger als 3600 Sekunden. Scheitert danach ein
Abruf eines Mitglieds, darf dessen unveränderter letzter Forecast weiterlaufen,
wenn sein ursprünglicher Empfangszeitpunkt nicht in der Zukunft liegt, höchstens
12 Stunden alt ist und mindestens ein unterstütztes Intervall noch in der Zukunft
endet. `OpenMeteoClient(max_stale_age=...)` erlaubt eine engere Grenze zwischen
null und 12 Stunden; sie kann die Frischegrenze des Prognosekerns nicht erweitern.
Die Begrenzung gilt auch am exakten Grenzzeitpunkt. Es werden weder neue
Wetterintervalle erzeugt noch Empfangszeiten aktualisiert. Der Prognosekern
prüft das Wetteralter zusätzlich bei seiner eigenen Ausgabezeit.

Ein einzelnes fehlerhaftes Mitglied blockiert verfügbare Mitglieder nicht.
Wenn weder ein erfolgreicher Abruf noch ein zulässiger Cache verfügbar ist,
scheitert der Wetterlauf ausdrücklich. Der letzte Abruffehler bleibt auch bei
verwendetem Cache in `weather_errors` sichtbar. Ein erfolgreicher Folgeabruf
löscht ihn. Verwendeter alter Cache erhält `cache_state=stale_if_error` und macht
bei vollständiger verbleibender Tagesabdeckung den Qualitätssensor `degraded`.
Auch ein Fitfehler wird so sichtbar; fehlende Abdeckung bleibt `partial`.

## Begrenzte Diagnosen

`weather_diagnostics` ergänzt die bestehende Normalisierung kleiner negativer
Nachtstrahlung um Ablehnungsgründe für Strahlung, ungültige Umgebungsendpunkte,
fehlende benachbarte Endpunkte und Zeitstempel. Maximal acht Beispiele je Liste
bleiben erhalten. Fehlende Intervalle bleiben Lücken.

Je Wettermodell werden ursprünglicher Empfangszeitpunkt, Alter, Cachezustand,
Abruffehlertyp, Abdeckungsbeginn und -ende sowie die unterstützten Sekunden je
angefordertem lokalem Tag ausgegeben. Der laufende Tag beginnt für diese Prüfung
an der Aktualisierungszeit. Die Tagesgrenzen berücksichtigen auch 23- und
25-Stunden-Tage. Diese Wetterabdeckung ist keine Zusage gültiger Physik oder
einer vollständigen Anlagenprognose.

`resources` in HA-Diagnosen und Qualitätsattributen enthält monotone Laufzeiten
für Join, Fit und Prognose (Sekunden des letzten erfolgreichen Ausgabelaufs),
Fitversuche, Wiederverwendungen und Fitfehler seit Neustart, letzte Fit-Erfolgs-
und Fehlerzeitpunkte, den letzten Fehlertyp und akzeptierte eindeutige gemessene
Stunden je Wechselrichter/Ausgangsstufe. Fitzeiten sind bei Wiederverwendung null.
Eindeutige Messstunden sind keine vervielfachten Forecast-Origins und auch kein
Nachweis ausreichender Modellhistorie. Die Ressourcenattribute sind vom Recorder
für die normale Attributaufzeichnung ausgeschlossen.
