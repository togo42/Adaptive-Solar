# Physik- und Schattenoptionen als überprüfbare Kandidaten

Stand: 27.10.2026. Die folgenden Optionen sind generische numerische
Modellannahmen. Verhaltenstests belegen Rechenverträge, keine Verbesserung der
Prognosegüte. Ein Vergleich braucht vorab festgelegte Kriterien und tatsächlich
vorab archivierte Prognosen gegen dieselben Messungen.

## Kompatible Physikparameter

Die nativen Einrichtungs- und Optionsdialoge bieten je String:

| Parameter | Standard | Bereich | Bedeutung |
|---|---:|---:|---|
| `iam_ashrae_b0` | 0 | 0–0,2 | ASHRAE-Einfallswinkelverlust ausschließlich des direkten Strahlungsanteils; 0 deaktiviert den Kandidaten |
| `faiman_u0` | 25 | 5–100 | konstanter Wärmeübergang in W/m²/K |
| `faiman_u1` | 6,84 | 0–30 | windabhängiger Wärmeübergang in W/m²/K je m/s |
| `wind_speed_factor` | 1 | 0–2 | numerischer Faktor auf Quellwind vor Faiman |

Die thermische Berechnung verwendet die auftreffende Strahlung vor IAM, die
PVWatts-Berechnung die nach IAM verbleibende wirksame Strahlung. Diffus- und
Bodenanteil erhalten hier keine zusätzliche IAM-Korrektur. ASHRAE ist eine
vereinfachte optische Kandidatenannahme, kein individuell vermessenes Modulmodell.

Faiman-Koeffizienten müssen zur Montage und zur Bezugshöhe der Windmessung
passen. Der Windfaktor ist eine ausdrücklich konfigurierte Näherung, keine aus
bekannten Standortdaten automatisch abgeleitete Höhenkorrektur. Der Standard
bleibt die bisherige pvlib-Annahme; sie zertifiziert keine bestimmte Dachmontage.
Die numerischen Grenzen vermeiden entartete Modellparameter und sind keine
empirisch validierten Grenzen für jede Hardware.

Neutrale neue Werte fehlen im kanonischen Konfigurations-JSON. Dadurch behalten
bestehende Konfigurationen ihre bisherigen vollständigen und physikalischen
Fingerprints. Aktive Physikänderungen ändern die strenge physikalische Bindung.
Es werden keine Herstellerdaten, Geräte-APIs oder Batteriedaten benötigt.

## Optionale Zeitintegration

`physics_substeps` ist 1 (bisheriger Mittelpunkt), 2, 4, 6 oder 12. Werte größer
1 aktivieren einen Kandidaten. Die ursprünglichen Wetterintervalle und ihre
GHI/DNI/DHI-Mittelwerte bleiben bestehen. Das gilt auch für die Auswahl der
Wettermodellkohorte für Schattenreferenzen, vor und nach einer GHI-Anpassung:
deren Teilintervallintegration normiert auf derselben ursprünglichen
Quellstütze wie die veröffentlichte Prognose. Eine komponentenweise Ineichen-
Clear-Sky-Zeitform, normiert über das **ursprüngliche** Quellintervall mittels
8-Punkt-Gauss-Legendre-Quadratur, liefert interne Momentan-Proxys. Die Ausgabe
mittelt gleich lange UTC-Teilintervalle an deren Mittelpunkten. Das ist
numerische Quadratur einer angenommenen Zeitform, keine gemessene unterstündige
Bewölkung. Numerische Restabweichungen der beiden Quadraturen sind möglich.
Temperatur, Wind und Bewölkung bleiben repräsentative Quellbedingungen.

Ein bei Ausgabe bereits laufendes Quellintervall wird nur für die zukünftige
Ausgabe beschnitten. Seine Formnormierung bleibt an das volle Quellintervall
gebunden; die Reststunde erhält dadurch nicht erneut die volle Stundenenergie.
Unverfügbare oder über die Wettergrenzen hinausgehende Momentan-Proxys erzeugen
fehlende Physikzellen. Nacht bleibt null. UTC-Dauern gelten auch bei beiden
Zeitumstellungen. Pro Momentan-Proxy werden alle Strings einer Ausgangsstufe
summiert und deren gemeinsame AC/DC-Grenze **vor** dem Leistungsmittel angewandt.
`inverter_power(..., at=...)` bleibt ein reiner Momentanpfad; Nowcast-Referenzen
werden nicht nochmals zeitlich integriert.

## Wettermodellarchive

`ForecastResult.member_points` enthält nur wirklich verfügbare, konfigurierte
Wettermodelle. `member_issued_at` enthält deren ursprüngliche Wetterausgabezeit.
Je Modell enthalten die Punkte eigene Wetterfeatures, Baseline und identische
Physikleistung. Unterstützung liegt ab der tatsächlichen Prognoseausgabe;
`source_partial_at_issue` kennzeichnet die beschnittene laufende Zelle.

Diese Arme verwenden ursprüngliches NWP ohne lokale Temperatur/Wind/GHI,
gelernte Schattentabelle, ML oder Leistungs-Nowcast. Konfigurierte Stringphysik,
Horizonte, Dämpfung und gemeinsame Ausgangsgrenzen gelten weiterhin. Ein
Mehrmodellmittel ist keine zusätzliche unabhängige Wetterquelle. Die API liefert
Vergleichsarme; erst die gesonderte Speicherung macht sie zu einem Archiv.
Ihre Berechnung erfolgt vor den Abbruchstellen des operativen Korrekturpfads.
Scheitern beispielsweise alle GHI-korrigierten Teilintervall-Proxys, bleibt die
operative Zelle eine Lücke; gültige reine NWP-Mitglieder bleiben trotzdem in
`member_points` verfügbar. Scheitert auch ihre ursprüngliche Physik, bleiben
ebenso deren Zellen fehlend. Historische fehlende Mitglieder werden nicht ergänzt.

## Zeitlich qualifizierte Schattentabelle

Ein aggregierter Ausgangszähler identifiziert keine einzelnen Strings. Die
Tabelle lernt deshalb weiterhin eine effektive direkte Transmittanz je
Ausgangsstufe und Sonnenstandsbin. Ihr gemeinsamer Faktor ist eine Näherung bei
unterschiedlich verschatteten Strings, kein identifizierter Einzelstringverlust.
Diffusstrahlung wird nicht pauschal mit dem Faktor abgeschwächt.

Die Freigabe benötigt mindestens fünf verschiedene UTC-Viertelstunden aus
mindestens zwei verschiedenen UTC-Tagen innerhalb der letzten 45 Tage. Tage
werden über ihren jeweiligen Median gleich gewichtet. Der Median der absoluten
Abweichungen dieser Tagesmediane (MAD) darf höchstens 0,15 betragen. Damit kann
eine Serie vieler Messungen eines einzelnen Tages die Freigabe nicht allein
erzwingen; einzelne Ausreißer bleiben robust begrenzt. Es gibt keinen
pauschalen Mindestfaktor: starke reale Verschattung bleibt darstellbar.

Nach der Erstfreigabe darf der gespeicherte Faktor höchstens 0,10 pro seit der
letzten Änderung vergangenem UTC-Kalendertag zum neuen Median wandern. Im selben
Tag bleibt er stabil. Ein bloßer Lese-/Prognoseaufruf ändert den Zustand nicht.
Nicht ausreichende, zu alte oder stark streuende Belege liefern die neutrale
Baseline; diese Freigabeentscheidung ist von der begrenzten numerischen Drift
zu unterscheiden. Mehrere bewölkte Tage allein löschen keine Freigabe.

Alle produktiven Aufrufe übergeben `as_of` explizit. Zukünftige Messungen werden
beim Schreiben zurückgewiesen und bei zeitlich früherer Auswertung ignoriert.
Diagnostik zeigt Probenzahl, Tageszahl, MAD, Probenalter, ausgeschlossene
Zeitproben, Kandidatenfaktor, Freigabestatus und Ablehnungsgrund. Das Alter ist
Probenalter, kein Nachweis der unveränderten Umgebung.

Persistenzschema 3 bewahrt neben dem UTC-Viertelstundenbin den echten
Beobachtungszeitpunkt und den Zeitpunkt, zu dem der qualifizierte Bericht zur
Verfügung stand. Je Viertelstunde bleibt die **erste** qualifizierte Probe
unverändert; ein späterer Bericht ersetzt sie nicht rückwirkend. Das weicht
bewusst von der früheren Letztwert-Ersetzung ab. Maximal 24 Viertelstunden je
Bin sowie 64 chronologische Freigabeänderungen bleiben gespeichert. Eine
Auswertung verwendet nur damals verfügbare Proben und Freigaben; Lesen ändert
keinen Zustand. Unveränderte Faktoren verfallen nicht allein deshalb, weil ihre
letzte numerische Änderung lange zurückliegt. Die 45-Tage-Altersprüfung betrifft
die tatsächlich qualifizierten Beobachtungen.

Schema 1 und 2 bleiben lesbar, ihre Proben besitzen jedoch keine nachweisbaren
Beobachtungs-/Verfügbarkeitszeitpunkte. Sie werden ausdrücklich als
`unqualified_legacy` erhalten und in der Diagnostik gezählt, dürfen aber keine
Freigabe oder Lernbaseline begründen. Es werden keine Empfangszeiten erfunden.
Die aktive Tabelle startet für solche Altdaten neutral; **Lesbarkeit bedeutet
keine Kompatibilität ihrer Lernhistorie**. Die bestehenden GHI-, Messqualitäts-,
Clipping- und Abregelungsgates bleiben notwendig. Die Zahlen sind konservative
Schutzregeln und benötigen ebenfalls prospektive Standortprüfung; insbesondere
die neue Freigabe unterscheidet sich bewusst von der früheren Freigabe allein
nach fünf Viertelstunden.

## Optionale Leistungs-Nowcast-Glättung

`power_nowcast_window_minutes` ist standardmäßig 0 (bisheriges Verhalten);
1–15 Minuten aktivieren einen Kandidaten. Ein begrenzter Verlauf hält höchstens
128 tatsächlich bei Aktualisierungen gelesene Originalberichte pro Stufe samt
Umweltberichten. Weder häufigeres Abfragen noch neue Messzeitpunkte werden
angefordert. Wiederholungen desselben Berichts erzeugen keine neue Beobachtung.
Der Verlauf ist flüchtig und wird bei fehlender/ungültiger Leistung oder einer
geänderten überwachten Freigabephase verworfen. Das umfasst auch eine zwischen
zwei Aktualisierungen registrierte Abregelungs-/Validitätsunterbrechung.

Jeder nutzbare Leistungsbericht bekommt eine eigene Momentanreferenz mit
demselben Wettermodellkohort, GHI-Regime und Lernmodus. Umweltwerte müssen vor
oder am ursprünglichen Leistungszeitpunkt liegen. Neuere GHI wird niemals
rückwärts angewandt. Quellen, die erst nach dem Leistungsbericht ausgegeben
wurden, fehlende Wetterunterstützung und inkompatible Schattenbaselines werden
übersprungen. Das kann die Glättung insbesondere bei häufig neu ausgegebenem
Wetter vollständig verhindern; dann gilt der bisherige Einzelbericht-Nowcast.

Gemittelt werden begrenzte Residuen relativ zur jeweiligen physikalischen
Momentanbaseline, nicht rohe Leistungen über die Sonnenbewegung. Die Gewichte
berücksichtigen den tatsächlich von benachbarten Berichtzeitpunkten aufgespannten
Zeitraum und eine exponentielle Aktualitätsabnahme mit halber Fensterlänge als
Zeitkonstante (mindestens eine Minute). Vor dem ältesten oder nach dem neuesten
Bericht wird keine Zeitunterstützung erfunden. Mindestens zwei vergleichbare
Berichte sind nötig. Das geglättete relative Residuum wird auf die jüngste
Momentanbaseline zurückbezogen und durch die bestehenden 35-%-Stufengrenze,
Nowcast-Abnahme und Ausgangsgrenze begrenzt. Geänderte Leistungen behalten keine
als kalibriert bezeichneten Fehlerbänder. Der Status nennt den Kandidatenpfad.

## Lokaler Rechenaufwand

Ein synthetischer Einzelvergleich am 27.10.2026 mit `examples/site.json`, zwei
Stufen, zwei Wetterarmen und 300 Ausgabeintervallen benötigte auf dem
Entwicklungsrechner rund 1,0 Sekunden mit dem bisherigen Mittelpunkt und
9,0 Sekunden mit vier Teilintervallen. Beide Wetterarme verwendeten dabei
dieselbe synthetische Klarhimmelkurve; 600 zusätzliche Einzelmodellintervalle
waren jeweils enthalten. Das ist eine Orientierung zum zusätzlichen
Rechenaufwand, kein HAOS-Benchmark und kein Genauigkeitsnachweis. Die feinere
Integration bleibt deshalb optional; Laufzeitdiagnosen zeigen den tatsächlichen
Aufwand der jeweiligen Installation.

## Primärquellen

Am 27.10.2026 gegen die pvlib-Dokumentation und den verwendeten Quellcode geprüft:

- [pvlib ASHRAE IAM](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iam.ashrae.html): Winkelmodell und Parameter `b`.
- [pvlib Faiman](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.temperature.faiman.html): Wärmeübergangsparameter und Windbezug.
- [pvlib Temperatur-Quellcode](https://github.com/pvlib/pvlib-python/blob/main/pvlib/temperature.py): dokumentierte Herkunft der Standardkoeffizienten aus offen montierten Siliziummodulen.
- [pvlib Clear-Sky-Modelle](https://pvlib-python.readthedocs.io/en/stable/reference/clearsky.html): verwendete interne Zeitform ist modelliert.
