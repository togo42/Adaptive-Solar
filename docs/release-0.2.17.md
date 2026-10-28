# Adaptive Solar 0.2.17

Der Originalreplay von 0.2.16 lehnte auf dem Archivhost berechnete Zwischenwerte
wegen kleinster Rundungsunterschiede gegenüber HA ab. Im realen Abnahmedatensatz
lag die größte Leistungsabweichung bei 2,3e-12 W, deutlich unter der vorhandenen
Leistungstoleranz von 1e-6 W. Zeitunterstützung, Eingaben und Lernentscheidungen
stimmten überein.

0.2.17 korrigiert ausschließlich den Vergleich ausdrücklich abgeleiteter
Gleitkommawerte. Originaleingaben, Konfiguration, Quellprovenienz, Zeiten,
Schrittfolge und fachliche Lernentscheidungen bleiben streng gebunden.
Die produktiven Physik- und Lernregeln ändern sich nicht.
Die feste Rundungspolicy verwendet absolute und relative Toleranz jeweils
`1e-12`; die separate Leistungsprüfung bleibt bei standardmäßig `1e-6 W`.
Benannte Referenz-/Faktorwerte dürfen nur bei identischer Struktur und weiterhin
identischen Gateentscheidungen so verglichen werden. Materielle Abweichungen
und bereits durch eine Rundungsdifferenz veränderte Entscheidungen bleiben Fehler.

Das Release 0.2.16 und seine Originalaufnahmen bleiben unverändert. Deren
fehlgeschlagene Abnahme wird nicht rückwirkend umgedeutet. Für den erneuten
Nachweis werden mit 0.2.17 aufgenommene Originale und der dazu passende
Archivhoststand verwendet.

Vorhandene Exportoptionen, Journale, externe Originale, Konfiguration und gültige
Historie bleiben erhalten. Nach HACS-Download Core neu starten; auf dem
Archivhost die passende unveränderliche Quellversion installieren und die
vorhandenen Quellen/Cursor weiterverwenden. Kein Core-/OS-Upgrade erforderlich.

Prüfumfang, präzise Vergleichsregeln und Laufzeitabnahme werden im
[Entwicklungsstand](entwicklungsstand.md), [Datenvertrag](archive-storage-contract.md)
und [Archivbetrieb](archivbetrieb.md) dokumentiert. Numerische Reproduktion ist
kein Nachweis besserer Prognosen oder kalibrierter Ensemblewahrscheinlichkeiten.


## Veröffentlichungs- und Betriebsnachweis

Veröffentlicht aus `ed901b337da64d41022562ed8a5ba55769cd273a`; auf HA und
Archivhost installiert. Main-/Tag-CI bestätigen je 1.634 Tests ohne Skips und
90,84 % kombinierte Abdeckung. Vier neue Originalreplays und acht chronologische
Schattenreplays bestanden; maximale Leistungsabweichung 1,3643e-12 W.
Eine getrennte eingefrorene Kopie mit 76 Originaldateien und 3.019 Ereignissen
wurde einschließlich Indexwiederaufbau unverändert geprüft. Die vorhandene
Anlagenkonfiguration, Historie, Journalgenerationen und alten Originale blieben
erhalten. Die vier Archivtimer sind aktiv.

Die kurze Anfangsaufnahme belegt keine mehrmonatige Lerngüte. Bei rund 6,8 GiB
freiem Hostspeicher ist die Kapazität für 24 Monate noch nachzumessen.
[Vollständige Nachweise und Grenzen](entwicklungsstand.md#veröffentlichter-und-installierter-stand-0217).
Dieser Betriebsnachtrag liegt außerhalb des unveränderten Release-Tags.
