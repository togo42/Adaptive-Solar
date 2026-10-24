# Recherche: Physikalische und NWP-basierte Solarprognosemodelle

> Recherche-Zusammenfassung, Stand Oktober 2026. Fokus: Klarheits- (Clear-Sky-)Modelle, NWP-Strahlungsprognosen, physikalische Transmissions-/Trübungs- und Sonnenstandsmodelle, Satelliten-Nowcasting (< 6 h) und Hybridmodelle. Genauigkeitsangaben, soweit in den Quellen verfügbar, in W/m² oder %.

---

## 1. Clear-Sky-Modelle (Klarheitsstrahlungsmodelle)

Clear-Sky-Modelle berechnen die an der Oberfläche ankommende Strahlung für **wolkenfreien Himmel** als deterministische Funktion von Sonnenposition, Höhenwinkel, Jahres-/Tageszeit und einer atmosphärischen Trübungskenngröße (Linke-Turbidität $T_L$, Aerosol-AOD, Wasserdampf, Ozon). Sie sind die Referenzgröße für den **Clear-Sky-Index** $k_c = GHI / GHI_{clear}$, mit dem NWP- und Satellitenprognosen normalisiert werden – dadurch werden systematische Modellbiases von Wolkeneffekten entkoppelt. Der Modellfehler ist damit eine Untergrenze jeder downstream Prognose: Bias im Clear-Sky-Modell überträgt sich 1:1 auf die Prognose.

### 1.1 Ineichen–Perez (1982/2008)

Das Modell kombiniert einen präempirischen Klarheitssatz (heliostatische Sonnenkonstante $G_0$, effektive Masse, bodenbasierter Höhenkorrekturfaktor) mit einer **Linke-Turbiditäts-Kennzahl**, die die Streuung und Absorption der Atmosphäre global zusammenfasst. Es wurde von der IDEES/ASSET-Datenbank abgeleitet und von Perez et al. (2002) reformuliert, wobei $T_L$ gegen Sonnenhöhe und -azimut interpoliert wird. Es ist das am weitesten verbreitete physisch-empirische Modell und in **pvlib** (`ineichen`) als Referenz implementiert; es benötigt als einzige Eingabe neben der Position die turbidity time series bzw. eine Klimatologie-Tabelle. Typische Genauigkeit ist standortabhängig stark schwankend: In der IJCAI-17-Studie (Palani et al.) erzielte Ineichen über Bangalore/Seria/Tucson RMSE von **153 / 118 / 40 W/m²** (nRMSE 32,6 / 24,8 / 7,1 %) – am besten dort, wo reiche Sensorik für die $T_L$-Ableitung vorlag, im tropischen Klima dagegen am schlechtesten der getesteten Modelle.

*Einsatzbereiche:* Standortanalyse, Yield-Assessment, Normalisierung von Prognosen, pvlib-Standard.
*Horizonte:* nicht zeitabhängig – reine Referenzfunktion (Tagesverlauf/Szenarien).
*Stärken:* sehr kompakt, robust, wenige Eingaben, gut dokumentiert, überall verfügbar.
*Schwächen:* eine einzige lernbare Größe ($T_L$) macht das Modell „rigide" (Bewertung von Palani et al.); klimatologische $T_L$-Tabellen sind regional uneinheitlich; in feuchttropischen Lagen klar schlechter als in ariden Lagen.

### 1.2 Haurwitz (1945)

Ein rein empirisches, sehr einfaches Modell, das die Sonnenhöhenabhängigkeit der Klarheitsstrahlung als Potenz- bzw. Sinusfunktion beschreibt – ohne explizite Aerosol- oder Gaskomponente. Die Form $GHI = 1098 \sin h_s \cdot \exp(-0.057/\sin h_s)$ (in kJ/m²·h, umgerechnet) ist analytisch lösst und benötigt **keine** atmosphärischen Zusatzdaten. Haurwitz ist damit der schnellste und datenärmste Vertreter, wird aber vor allem als Baseline-Modell genutzt.

*Einsatzbereiche:* Pedagogik, Baseline-Referenz, Daten-sparse Regionen, Quick-Screening.
*Horizonte:* wie alle Clear-Sky-Modelle tagesverlaufs-abhängig, nicht prognostisch.
*Stärken:* extrem einfach, keine atmosphärischen Eingaben, robust bei tiefen Sonnenhöhen.
*Schwächen:* keine Aerosol-/Trübungssensitivität; IJCAI-17: RMSE **108 / 75 / 48 W/m²** (nRMSE 23,1 / 15,2 / 8,2 %) – im Mittel besser als Ineichen, aber klar schlechter als ASHRAE in ariden Lagen.

### 1.3 ASHRAE (1979/2009)

Das ASHRAE-Modell (Handbook of Fundamentals) basiert auf einem monatsmittelbaren klaren Himmelssatz, korrigiert um eine **Aerosol-Trübungsfaktor-Familie** ($B$, $C$, $D$-Koeffizienten je Monat) und die atmosphärische Masse. Es wurde ursprünglich für die Gebäudetechnik (HVAC-Auslegung, Lastspitzen) entwickelt und modelliert direkte, diffuse und globale Komponente getrennt. In der 2009er Version wurden die Koeffizienten rekalibriert; die 1979er-Version ist die in der Literatur meistverglichene.

*Einsatzbereiche:* Gebäudesimulation (EnergyPlus etc.), HVAC, Lastprognose für Kühllastspitzen, grobe Ertragsabschätzung.
*Horizonte:* klimatologisch-jahreszeitlich, nicht prognostisch.
*Stärken:* getrennte Komponenten (DNI/DHI/GHI), Monatsauflösung, etablierte Implementierungen.
*Schwächen:* starke regionale Abhängigkeit der Monatskoeffizienten; IJCAI-17: RMSE **116 / 101 / 51 W/m²** (nRMSE 24,7 / 20,9 / 8,5 %).

### 1.4 SPARC (2007) – Hinweis zur Begriffsambiguität

**Wichtige Klarstellung:** In der Literatur zur Strahlungsprognose ist „SPARC" kein Klarheitsstrahlungsmodell. Die Referenz, die in Satelliten- und Solarprognose-Publikationen typischerweise mit dem Kürzel SPARC gemeint ist, ist das **Cloud-, Snow- und Cloud-Shadow-Detection-Scheme** von Brest, Rossow und Schiffer (J. Atmos. Oceanic Technol. 24(3), 2007, „New Cloud, Snow, und Cloud Shadow Detection Scheme for Operational Processing of Satellite Visible and Infrared Data"), das im Rahmen des *SPARC*-Projekts (Stereo Photogrammetric Analysis of Remotely-sensed Cloud imagery) entwickelt wurde. Es dient der **Wolken-, Schnee- und Schattenklassifikation** in Satellitenbildern, nicht der Berechnung von Klarheitsstrahlung. Sein „aggregated rating"-Ansatz gewichtet mehrere Spektralkanäle zu einem Wolkenwahrscheinlichkeitswert und löst danach explizit Schneeflächen (über IR-/NIR-Kontrast) und Wolkenschatten (über geometrischer Projektion auf Gelände) – eine entscheidende Vorstufe für jeden satellitenbasierten Strahlungsalgorithmus, da Schnee sonst systematisch als Wolke fehlklassifiziert wird. Falls Sie ein **Strahlungsmodell** „SPARC" meinten (z. B. das NASA-GISS/SPARC-Klimatologie-Programm oder einen radiativen Transmissionscode), ist die Anfrage zu präzisieren.

### 1.5 REST2 (Gueymard, 2008)

REST2 („Reference Evaluation of Solar Transmittance, 2 Bände") ist ein **zweistufiges, zweibandiges** Transmissionsmodell: In einem ersten Schritt wird die Gasabsorption analytisch über effektive optische Pfade modelliert, in einem zweiten Schritt wird eine **Aerosol-/Trübungstransmission** in einem sichtbaren Band (290–700 nm) und einem Nahinfrarot-Band (700–4000 nm) getrennt ausgewertet und zur Gesamttransmission zusammengefügt. Es berücksichtigt explizit Aerosol-AOD, Wasserdampf, Ozon und Bodenhöhe und erreicht laut Gueymard Genauigkeiten im Bereich physikalischer Radiativitäts-Codes. In der IJCAI-17-Referenz wurde für Tucson ein RMSE von **36,8 W/m²** (nRMSE 15,08 %) berichtet – besser als das dort verglichene StreamerRT (126,24 W/m², nRMSE 25,32 %).

*Einsatzbereiche:* wissenschaftliche Referenz, Ertragsstudien, Validierung von Clear-Sky-Modellen und Satellitenprodukten, Design von CSP-Anlagen.
*Horizonte:* tagesverlaufs-abhängig (deterministisch), nicht prognostisch.
*Stärken:* physikalisch motiviert, hohe Genauigkeit bei verfügbarer Aerosol-/Gas-Klimatologie, gut validiert.
*Schwächen:* Eingabedaten-intensiv (AOD, Wasserdampf, Ozon nötig), aufwändigere Parametrisierung, in der Praxis weniger verbreitet als Ineichen.

### 1.6 Data-gestützte Klarheitsmodelle („Blue Skies", IJCAI-17)

Als jüngste Klasse: ML-Modelle, die den Klarheitsverlauf direkt aus historischen GHI-Messungen lernen, ohne atmosphärische Zusatzdaten. Palani et al. (2017) filtern per DBSCAN klar-sky-Werte aus der Messreihe und trainieren anschließend saison-, stunden- und azimutabhängige Regressoren. Ergebnis: RMSE **40 / 54 / 24 W/m²** (nRMSE 8,5 / 10,9 / 4,1 %) für BS-Basic, mit saisonal-azimutaler Verfeinerung **27 / 42 / 18 W/m²** – **3- bis 4-fach** niedriger als die klassischen Modelle.

*Stärken:* keine Atmosphärendaten nötig, ortsspezifisch kalibriert, robust über Klimazonen.
*Schwächen:* benötigt mindestens ein Jahr 1-minütige Messdaten, kein Physik-Konsens (kaum auf neue Standorte übertragbar), Überanpassungsrisiko.

---

## 2. NWP-basierte Strahlungsprognosen

NWP-Modelle simulieren die Atmosphäre auf einem Gitter und berechnen die Strahlungstransfergleichung im Rahmen der **Strahlungs-Schema** (RRTMG, ecRad, RRTM, SW/RAD-schemes) bei jedem Zeitschritt. Die Strahlungsausgabe (Parameter 169 `ssrd` = surface short-wave radiation downwards, ECMWF/Open Data) ist damit das Gittermittel über den Prognoseraum – keine punktuelle Messgröße.

### 2.1 ECMWF IFS + ecRad

Das IFS löst die Strahlungstransfergleichung mit **ecRad**, das seit Cycle 43r3 (2017) operational ist und das Vorgängermodell McRad ablöste. ecRad gruppiert die 112 Bänder des RRTM-Longwave-Codes bzw. 16 Bänder des Shortwave-Codes in effektive Bandsätze, verwendet einen Monte-Carlo-Independent-Column-Approximation-Ansatz für Wolken überlappende Säulen und erreicht ca. **35 % höhere Geschwindigkeit** bei vergleichbarer Genauigkeit. Auf dem TCo1279-Gitter (~9 km) verbraucht die Strahlung etwa **3,5 % der Modellrechenzeit**. Das deterministische IFS läuft bei ~9 km (TCo1279) Globauflösung; das ENS-Ensemble wurde von 18 km auf 9 km aufgerüstet. ECMWF Open Data liefert `ssrd` (Parameter 169) bei 0,25° und seit dem 20. Oktober 2026 zusätzlich bei 0,1°.

*Genauigkeit (CAMS-Radiation-Verifikation Q2 2025, 41 Stationen, IFS-HRES 9 km):*
- GHI intraday: rel. RMSE **29,6 %**, rel. MBE **1,5 %**; day-ahead: rel. RMSE **31,5 %**
- GHI rel. MAE intraday ≈ 16,7–21,5 %
- BNI (direkte Normale): rel. RMSE intraday **75,1 %**, day-ahead **79,6 %** – Faktor ~2,5 schlechter als GHI
- Desert-Klasse GHI am besten: rel. RMSE 23,1–25,6 %
- Spatially-smoothed Variante (IFS-HRES_LR): GHI 28,6 % intraday / 30,6 % day-ahead – räumliches Glätten verbessert den RMSE um < 1 Prozentpunkt

*Einsatzbereiche:* Day-ahead bis Season-ahead-Prognosen, globale Deckung, Ensembles (ENS) für Unsicherheitsquantifizierung, Input für CAMS-Radiation.
*Horizonte:* 0 h – 10 Tage (deterministisch), bis 6 Monate (ENS/MO-Extended-Range).
*Stärken:* global, hohe Konsistenz, geöffnete Daten (Open Data, Open-Meteo), etablierte Verifikationskette.
*Schwächen:* Gitterauflösung 9 km glättet lokale Wolkeneffekte (Double-Penalty-Effekt); BNI-Fehler sehr hoch; kein flächenexakter Standortwert; 6-tägliche Aktualisierung im Open-Data-Zugang.

### 2.2 ICON / ICON-D2 (DWD)

ICON (ICOsahedral Nonhydrostatic) ist das deutsche Global- und Regionalmodell mit icosahedraler Gitterstruktur; die Strahlung wird mit **RRTMG** (Rapid Radiative Transfer Model for GCMs, 30 Bänder) gelöst. Die Nieder-Plus-Version läuft bei **2,2 km Auflösung mit 65 vertical levels** und **48 h Vorhersagezeit**, alle 3 h aktualisiert. ICON-EU (europäische Domäne) läuft ebenfalls bei ca. 2,2 km; ICON-D2 (Deutschland) bei 2,2 km.

*Genauigkeit (meteoblue BSRN/WRDC-Verifikation 2018–2020, 70+ Stationen, stündliche GHI):*
- ICON: MAE **45,86–54,12 W/m²** (je nach Region)
- im Vergleich: ERA5 39,95–48,41 W/m²; GFS 47,77–56,19 W/m²; MultiModel 42,54–51,06 W/m²; NEMS 54,61–65,74 W/m²

*Einsatzbereiche:* Deutschland-/Europa-Prognosen, Kurzfrist-Forecasting, Intraday, Solar- und Windpark-Prognosen in DACH.
*Horizonte:* 0–48 h (ICON-D2/ICON-EU, 2,2 km), 0–7,5 d (ICON global).
*Stärken:* sehr hohe Gitterauflösung für Europa, DWD-Open-Data-Zugang, im DACH-Raum beste lokale Wolkendarstellung.
*Schwächen:* kurze Vorhersagezeit im Hochauflösungslauf, Regionalscope, Strahlungsschema-Abhängigkeit.

### 2.3 GFS (NOAA)

Das Global Forecast System verwendet **RRTMG** über die Common Community Physics Package (CCPP) mit dem Modul `module_radsw_main`. Die Aerosol-Parametrisierung im Strahlungsmodul ist **klimatologisch mit 5°-Auflösung**, d. h. ohne aktuelle Aerosol-Vorhersage – ein direkter Treiber für systematische GHI-Bias in belasteter Luft (Staub, Rauch).

*Genauigkeit (meteoblue, stündliche GHI):* GFS MAE **47,77–56,19 W/m²** – im Mittel etwas schlechter als ICON und ERA5. In der SolarAnywhere-Validierung schlug GFS/NDFD die Persistenz bis ca. 5–6 h Vorlauf, danach aber unterhalb des Satelliten-Nowcasts.

*Einsatzbereiche:* globale Vorhersage, Input für Prognosesysteme in USA und global, D+4 bis D+14 bei Solargis.
*Horizonte:* 0 h – 16 Tage.
*Stärken:* vollständig offen zugänglich (AWS Open Data, NOMADS), globale Abdeckung.
*Schwächen:* 5°-Aerosolklimatologie, relativ grobes Gitter (0,25°), in Europa meist schlechter als ICON/IFS.

### 2.4 HARMONIE (KNMI/DMI/Sundsvall-Modell)

HARMONIE-AROME ist ein nicht-hydrostatisches Kürzstreckenmodell in 2- bis 2,5-km-Auflösung; KNMI liefert es in drei Domänen (Niederlande, Europa, Karibik) mit stündlicher Aktualisierung und 2,5 Tagen Vorhersagezeit. KNMI speist nur **globale Sonnenstrahlung**, keine direkte/diffuse Zerlegung – Open-Meteo wendet dazu ein Separationsmodell an (Razo/Müller Witwer, EU-PVSEC 2019). KNMI-Mitigation des **doppelten Bestrafungsproblems**: Statt nur RMSE-Glättung wird die Wirkung räumlicher Verschiebung von Wolkenbändern durch Vorhersage von **cloud physical properties** mit atmospheric motion vectors adressiert.

*Genauigkeit (Wang et al., Solar Energy 177, 47–58, 2019):* RMSE von etwa **31–44 % für GHI** bei ca. 4 km × 6 km Auflösung.
Das KNMI-Projekt „Forecast of solar radiation in the Netherlands" kombiniert SEVIRI-Satellitenbilder mit HARMONIE: 0–6 h via Advektion von SEVIRI-Wolken-Eigenschaften (mit SICCS-Algorithmus für Broadband-/Spektralflüsse), 0–48 h via HARMONIE mit SEVIRI-Cloud-Masken-Assimilation; die „tipping point" zwischen Satelliten- und Modellprognose liegt innerhalb der 0–6-h-Fenster. Verifikation am BSRN-Standort Cabauw.

*Einsatzbereiche:* Kurzfristprognose (Intraday, 0–48 h), Regionalmodelle für kleine Domänen, Solarpark-Prognosen in Nordeuropa.
*Horizonte:* 0–48 h (HARMONIE-AROME).
*Stärken:* sehr hohe Auflösung, stündliche Updates, explizite Wolkenbehandlung (keine Konvektionsparametrisierung).
*Schwächen:* kurze Vorhersagezeit, kein DNI/DHI ohne Separation, Domänen-spezifisch.

### 2.5 CAMS Radiation Service (betriebsnahe NWP-Strahlungsprognose)

Der Copernicus Atmosphere Monitoring Service betreibt quartalsweise Verifikation der IFS-Strahlungsprognosen gegen 41 BSRN-Stationen (Q2 2025-Bericht). Zentraler Befund: **GHI ist um Faktor 2–2,5 genauer als BNI** (direkte Normale), da BNI sensitiv auf horizontale Wolkenkantenverschiebungen und Aerosol-Angaben ist. Zusätzlich existiert eine **IFS-COMPO**-Komponente (40 km, mit modellierter Aerosol-Vorhersage), die bei BNI in allen Fehlerklassen besser abschneidet als IFS-HRES, bei GHI aber nur in rel. MAE/MBE besser ist – bei RMSE liegt IFS-HRES weiter vorne.

*Genauigkeit (rel. RMSE, Q2 2025):*
| Produkt | GHI intraday | GHI day-ahead | BNI intraday | BNI day-ahead |
|---|---|---|---|---|
| IFS-HRES (9 km) | 29,6 % | 31,5 % | 75,1 % | 79,6 % |
| IFS-HRES_LR (geschmiert) | 28,6 % | 30,6 % | 73,5 % | 77,9 % |
| IFS-COMPO (40 km) | 30,9 % | 32,9 % | 80,1 % | 84,9 % |

---

## 3. Physikalische Transmissions-, Trübungs- und Sonnenstandsmodelle

Diese Modellklasse ist **kein Forecaster**, sondern die deterministische Grundlage, ohne die kein Prognosesystem auskommt: sie liefert die Sonnenposition, die atmosphärische Transmission und die Umlegung der Strahlung auf beliebige Modulorientierungen.

### 3.1 Sonnenposition

Alle modernen Implementierungen verwenden entweder den **NREL-SPS-Algorithmus** (Reda & Andreas, 2004) oder die **IAU-Konvention** für Sternzeit. pvlib bietet `pvlib.spa` (Solar Position Algorithm, NREL-Spreadsheet-kompatibel) mit Genauigkeit < 0,003° (entspricht ~0,1 W/m² bei hohem Sonnenstand), sowie `pyephem` und `ephem`-Backends. Die Abweichung zwischen den Backends liegt typischerweise < 1″.

*Genauigkeit:* < 0,003° (NREL SPA).
*Stärken:* absolut reproduzierbar, keine Messdaten nötig, analytisch lösbar.
*Schwächen:* topografische Schatten-/Diffus-Horizont-Effekte erfordern separate Behandlung (z. B. `pvlib` Horizon-Modelle).

### 3.2 Linke-Turbidität & Ineichen–Perez

Die Linke-Turbidität $T_L$ quantifiziert die Streuung und Absorption einer „reinen" Wasserdampf-/Rayleigh-Atmosphäre durch zusätzliche Aerosole und Verunreinigungen (skalarer Turbiditätsfaktor $T = T_L \cdot T_{gas}$). pvlib liefert zwei Zugänge: (a) klimatologische Monatsmittel-Tabelle (die ursprüngliche Ineichen-Tabelle mit regionalen Gruppen wie „Continental", „Tropical", „Desert"), (b) **Linke-Turbidity lookup** aus NSRDB-PWMIS-Daten (`get_linke_turbidity`), die monatliche und stündliche $T_L$-Karten bereitstellen.

*Typische $T_L$-Werte:* 1 (extrem klar), 2 (moderat), 3–5 (kontinental/hochtrüb), > 6 (stark belastet).
*Stärken:* ein einziger, physikalisch motivierter Parameter fasst die komplette Trübung zusammen.
*Schwächen:* $T_L$ bündelt Aerosol und Wasserdampf in einem Skalar – keine spektrale Auflösung, keine Trennung nach Aerosol-Typ (Staub vs. Sahel-Staub vs. Urban-Haze).

### 3.3 Perez-Transpositionsmodell

Das Perez-Modell (1990, 2002) ist der **Standard-Transpositionsalgorithmus**, um von GHI/DHI (Horizontal) auf beliebige Modulneigung zu gelangen. Es verwendet einen 8-Parameter-Interpolationssatz über Sonnenhöhe, Zenitwinkel der Sonne, Inklinationswinkel, azimuthale Komponente und Himmelstransparenz, um den isotropen und den anisotropen (circumsolar + horizontale Streulicht-)Anteil des Diffusstrahls zu gewichten. Es ist in pvlib, SAM und den meisten kommerziellen Ertragsmodellen implementiert und gilt als Genauigkeits-Referenz (Typical-Transposition-Modell).

*Typische Genauigkeit:* GHI→POA-Uncertainties < 1 % bei guter Eingabequalität.
*Stärken:* anisotropes Diffusmodell, sehr gut validiert, breite Implementierung.
*Schwächen:* benötigt DHI + DNI als Eingabe; unter schneebedecktem Boden oder extremer Horizontabtrennung fehleranfällig.

### 3.4 ASTM G173 / SMARTS2

Das ASTM G173-03-Referenz-Spektrum (300–4000 nm, 2,8 nm/5 nm Auflösung) ist aus **SMARTS2** (Simple Model of the Atmospheric Radiative Transfer of Sunshine) abgeleitet: Ein semi-empirischer Spektral-Transmissionscode, der Absorption und Streuung von Gasen (O₃, NO₂, H₂O, CO₂, O₂, CH₄), Molekül- und Aerosol-Streuung (Tabelle von vier Aerosol-Modellen: Rural, Urban, Maritime, Continental) explizit berechnet. Es ist der De-facto-Referenz-Spektralstandard für PV-Modul-Eichung (STC-Normalisierung nach ASTM E927/E1036) und für CSP-Design.

*Genauigkeit:* SMARTS2 gilt als ~2 % präzise gegenüber Labor-/Feldmessungen im Gesamtbereich.
*Stärken:* spektral aufgelöst, physikalisch transparent, internationaler Standard.
*Schwächen:* benötigt Aerosol- und Gas-Profile, nicht für Echtzeitbetrieb ausgelegt.

---

## 4. Satelliten-Nowcasting (< 6 h)

Satelliten-Nowcasting extrahiert aus geostationären Bildern (Meteosat MSG/SEVIRI, GOES, Himawari) Wolkeneigenschaften und **Cloud Motion Vectors (CMV)**, um die Wolkenentwicklung extrapolativ vorherzusagen und daraus die Bodenstrahlung abzuleiten. Es ist die einzige Modelklasse, die im ersten Stunde-bereich zuverlässig mit lokaler Wolkendynamik mithalten kann – NWP-Modelle sind dort durch Initialisierungs- und Auflösungsbeschränkungen limitiert.

### 4.1 SolarAnywhere (Clean Power Research)

SolarAnywhere kombiniert mehrere Phasen: **CMV-Nowcast** für 1 Min bis 5 h, **NWP-Blend** für 5 h bis 7 Tage. Der CMV-Algorithmus schätzt Wolkengeschwindigkeit und -richtung aus aufeinanderfolgenden MSG-Satellitenbildern; die Prognose wird über 5–6 h aufrechterhalten, danach erfolgt die Übergabe an das NWP-Ensemble. Der Clear-Sky-Index wird mit einem physischen Strahlungs-RT-Modell berechnet, das Luftfeuchte und Wolkendecks-Daten berücksichtigt.

*Validierung (7 US-Standorte, Vergleichsatellite = Surface Stations):*
- Satellite-Modell-Fehler (Referenz): **52–129 W/m²** RMSE
- **1-h-ahead CMV: 46–110 W/m²** RMSE – oft *besser* als die Satellitenreferenz
- **6-h-ahead CMV: 85–200 W/m²** RMSE
- Break-even CMV vs. NWP (NDFD) liegt bei **5–6 h** Vorlauf
- NWP schlägt Persistenz bis 7 Tage

*Einsatzbereiche:* Intraday-/Hour-ahead-Prognosen für PV-Portfolios, Dispatch, Bilanzkreise.
*Horizonte:* 1 Min – 7 d (gestaffelt).
*Stärken:* für 1 h Vorlauf oft besser als die Satellitenreferenz (rein extrapolativ, kein NWP-Bias), hohe zeitliche Auflösung.
*Schwächen:* hoher RMSE-Wachstum über die Zeit (46 → 200 W/m² von 1 h → 6 h), abhängig von Satelliten-Latenz, keine Wolkenhöheninformation ohne Stereokanäle.

### 4.2 Solargis (Solar Forecast Irradiance Algorithm, SFIA)

Solargis nutzt einen **optical-flow-basierten CMV-Nowcast**: Das Modell vergleicht zwei Satellitenbilder im Abstand von 5–30 Minuten und identifiziert in einem multi-skalierten Ansatz sowohl kleine als auch große Wolkenbewegungen. Die resultierenden Vektoren werden zu einer einzigen Vektorkarte aggregiert, um die Wolkenextrapolation über die nächsten **6 Stunden** zu steuern; ein zeitabhängiger Glättungsfaktor minimiert den MAE und simuliert Wolken-Diffusion. Aktualisierung erfolgt **alle 5, 10 oder 15 Minuten** je nach geografischer Region. Für längere Zeiträume übernimmt Solargis NWP: **IFS bis DAY+3**, **GFS ab DAY+4 bis DAY+14**. Zusätzlich sind HRRR und ICON (global/europäisch) als NWP-Modelle verfügbar.

*Einsatzbereiche:* PV-Ertragsprognose in Monitor- und Forecast-Plattformen, Hour-ahead.
*Horizonte:* 0–6 h (CMV), bis D+14 (NWP).
*Stärken:* multi-skalierte optical-flow-Methode, definierte Glättung für Wolken-Diffusion, kontinuierliche Updates.
*Schwächen:* proprietärer Algorithmus, geografische Abhängigkeit der Update-Frequenz, kein offener Zugang.

### 4.3 KNMI SICCS + AMV-Advektion

Das KNMI-Projekt kombiniert die **SICCS**-Methode (Surface Insolation under Clear and Cloudy skies derived from SEVIRI imagery) mit atmospheric motion vectors: SEVIRI-Wolkeneigenschaften werden mit den atmosphärischen Bewegungsvektoren advektiert, um 0–6-h-Vorhersagen zu erzeugen; daraus werden Broadband- und Spektralflüsse von direkter, diffuser und globaler Strahlung berechnet. Ab 0–48 h übernimmt HARMONIE, wobei SEVIRI-Cloud-Masken assimiliert werden.

*Genauigkeit (Wang et al., Solar Energy 177, 47–58, 2019):* RMSE **31–44 % GHI** bei 4 × 6 km.
*Stärken:* explizite Wolkenphysik-Advektion statt reiner Bewegungsvektor-Extrapolation, geostationäre MSG-Abdeckung.
*Schwächen:* 5-minütige MSG-Taktung (nicht 1-min wie Low-Earth-Orbit), Regionalscope.

### 4.4 All-Sky Imager (ASI) / Ground-based Nowcasting

Bodenbasierte Himmelkameras (Fischaugen- oder All-Sky-Imager) liefern Wolkenschatten-Nowcasting mit sehr hoher räumlicher und zeitlicher Auflösung. Im ASI-Benchmark (Renewable Energy, 2022) erreichten alle-sky-imager-basierte Nowcasts RMSE von **6,9–18,1 %** – die beste Genauigkeitsklasse im Sub-Stunden-Bereich. Utrecht-Universitätsarbeit (KNMI Nubiscope, Cabauw) berichtet RMSE-Peaks über 35 W/m².

*Einsatzbereiche:* PV-Steuerung am Standort, Ramp-Rate-Management, Nachbarschafts-Cloud-Tracking.
*Horizonte:* typisch 0–30 Min (max. 2 h), Updates alle 10–15 s.
*Stärken:* extrem hohe Aktualisierung, keine Satellitenlatenz, standortgenau.
*Schwächen:* nur ~15–30 km Sichtreichweite, kein Fernbereich, Wartung/Opazität/Belegung der Kuppel.

---

## 5. Hybridmodelle (NWP + physikalische Korrektur)

Die zentrale Erkenntnis der modernen Solarprognose: **Keine einzelne Modelklasse dominiert über alle Vorhorrizonte.** Hybridmodelle kombinieren entweder physisch-statistische Post-Processing-Verfahren auf NWP-Daten oder verschmelzen CMV-Nowcasts mit NWP-Ensembles zu einer nahtlosen Vorhersage.

### 5.1 Statistisches Post-Processing auf NWP (Bakker et al., Solar Energy 191, 2019)

Das Team um Bakker (ECN/TNO) testete **sieben Post-Processing-Methoden** auf HARMONIE-AROME-Daten mit CAMS-Aerosol-Input gegen KNMI-Bodenstationen (30 Stationen, stündliche GHR-Beobachtungen). Die Methoden: lineare Regression, Bias-Korrektur, Quantile-Regression, Generalized Random Forests (GRF), k-nearest neighbours, neural networks. Ergebnis: **Quantile Regression und Generalized Random Forests** schnitten am besten ab und lieferten signifikante RMSE-Verbesserungen über die Baseline.

*Stärken:* adressiert systematische Modellbiases ohne Modellveränderung, liefert direkt **Vorhersageintervalle** für probabilistische Dispatch-Optimierung.
*Schwächen:* benötigt reichlich historische Beobachtungen, Kalibrierung je Standort nötig, bei Regime-Shifts (Jahreszeitwechsel) anfällig.

### 5.2 ML-Kombination physikalisch-statistisch (Bellinguer et al.)

Bellinguer et al. berichten eine **~40 % RMSE-Verbesserung** durch Kombination von NWP-Modellen mit datengetriebenen Korrekturen – ein typischer Wert für die Branche, wenn multiple NWP-Modelle (IFS, ICON, GFS) mit lokalen Messdaten fusioniert werden.

### 5.3 GFS-Hybrid mit Gradient Boosting (arXiv:2007.01639)

Validierungsstudie für GFS-Strahlungsprognosen (Tag-vorher): **Persistenz schlug rohes GFS** im Vergleichszeitraum; der Gradient-Boosting-Hybrid (XGBoost-artig auf NWP-Features + lokalen Messungen trainiert) schnitt am besten ab und übertraf beide Einzelmodelle. Dieser Befund – dass ein rohes NWP-Modell unter Umständen schlechter ist als naive Persistenz – ist ein wichtiger Praxisbefund.

### 5.4 CMV-NWP-Blend (SolarAnywhere)

SolarAnywhere implementiert die **physisch gestaffelte Kombination** explizit: CMV-Nowcast für 1 Min–5 h, danach NWP-Blend bis 7 d. Die Break-even-Analyse (Validierung 7 US-Standorte) zeigt den exakten Übergang bei **5–6 h Vorlauf**: darunter ist CMV besser, darüber NWP.

### 5.5 Ensemble- und Multi-Model-Fusion

**meteoblue MultiModel** kombiniert mehrere globale NWP-Modelle (ICON, GFS, MFGLOBAL, NEMS) zu einem gewichteten Mittel; die Verifikation (BSRN/WRDC, 2018–2020, 70+ Stationen) ergab stündliche GHI-MAE von **42,54–51,06 W/m²** – im Mittel besser als jedes Einzelmodell außer ERA5 (39,95–48,41 W/m²).

*Einsatzbereiche:* Dispatch-Optimierung, Bilanzkreis-Prognosen, PV-Portfolios, E/Auktionen.
*Horizonte:* 0 h – 10+ Tage (je nach Ensemble-Fusion).
*Stärken:* robuster über Regime-Wechsel, probabilistische Ausgabe, oft die beste Gesamtgenauigkeit.
*Schwächen:* Rechenaufwand, Black-Box-Charakter der ML-Komponenten, erfordert kontinuierliche Rekalibrierung.

---

## 6. Komparative Einordnung: Genauigkeit nach Vorhorsizont

Zusammenfassung der wichtigsten Quantitätsanker aus den Quellen:

| Vorhors | Modellklasse | Typische Genauigkeit (GHI) |
|---|---|---|
| 0–15 Min | All-Sky Imager | RMSE 6,9–18,1 % |
| 1 h | Satellite CMV (SolarAnywhere) | RMSE 46–110 W/m² |
| 1 h | Commercial Intraday-Forecaster (8 Anbieter, EPJ Photovolt. 14/2023) | nRMSE 27–49 % je Standort, Streuung 26–58 % |
| 0–5 h | meteoblue Nowcast | rMAE 5–20 % |
| 3 h | Satellite vs. NWP Tipping Point (EPJ 2023, KNMI, Fennoscandia) | Satelliten besser < 3 h, NWP besser > 3–4 h |
| 5–6 h | CMV-NWP-Übergang (SolarAnywhere) | Break-even |
| 2–3 h | Solis-Heliosat vs. NWP (Fennoscandia) | Solis-Heliosat besser |
| 6 h | Satellite CMV (SolarAnywhere) | RMSE 85–200 W/m² |
| Day-ahead | ECMWF IFS-HRES (CAMS Q2 2025) | rel. RMSE 31,5 %, rel. MAE ~17–21 % |
| Day-ahead | GFS (meteoblue) | MAE 47,8–56,2 W/m² |
| Day-ahead | ICON (meteoblue) | MAE 45,9–54,1 W/m² |
| Day-ahead | HARMONIE (Wang et al. 2019) | RMSE 31–44 % |
| D+1..D+7 | SolarAnywhere NWP-Blend | RMSE 102–204 W/m² (Standort-abhängig) |

**Wichtige methodische Befunde:**
1. **BNI-Fehler sind ~2,5× höher als GHI-Fehler** (CAMS: 75–80 % vs. 29–32 % rel. RMSE) – jede Prognose mit direktem Strahlanteil ist entsprechend unsicherer.
2. **Double-Penalty-Effekt:** Räumliches Glätten von NWP-Modellen verbessert RMSE um < 1 Prozentpunkt (CAMS IFS-HRES vs. HRES_LR), beseitigt aber nicht die eigentliche Wolkenverschiebungs-Ursache.
3. **Persistenz ist ein ernstzunehmender Benchmark:** In der GFS-Validierung schlug Persistenz das rohe GFS-Modell in einem Vergleichszeitraum.
4. **Clear-Sky-Index-Normalisierung** mit Ineichen–Perez ist der Branchenstandard, um Prognosefehler von Klarheitsmodell-Bias zu entkoppeln.

---

## 7. Freie vs. kommerzielle Datenquellen je Modell

Wichtige praktische Frage für den Einsatz: Lässt sich das jeweilige Modell **ausschließlich mit frei verfügbaren (kostenlosen) Daten und Diensten** betreiben — oder sind kommerzielle Lizenzen nötig? Kurzantwort: **Alle in diesem Bericht beschriebenen physikalischen und NWP-basierten Modelle sind vollständig mit kostenlosen Daten betreibbar** (DWD ICON, ECMWF Open Data, NOAA GFS, CAMS, ERA5 sind allesamt CC BY 4.0 bzw. Public Domain). Kommerziell werden erst die **fertigen Solar-Nowcasting-Dienste** (SolarAnywhere, Solargis, Solcast, Meteomatics) und **bankable Datensätze mit SLA**. Die Lizenzdetails sind allerdings differenziert zu betrachten — insbesondere Open-Meteo (scheinbar frei, aber nicht-kommerziell) und einige ML-Gewichte (z. B. Moirai: CC BY-NC).

### 7.1 Übersicht: Einsetzbarkeit ohne kommerzielle Dienste

| Modell / Klasse (Abschnitt) | Ohne Kommerz-Service einsetzbar? | Freie Eingangsdaten / Quellen | Anmerkung / kommerzielle Alternative |
|---|---|---|---|
| Clear-Sky-Modelle (Ineichen–Perez, Haurwitz, ASHRAE, REST2) | ✅ Vollständig | pvlib (BSD-3), NSRDB-Lookups, CAMS-Turbidität, ERA5-Land | Kein kommerzieller Dienst nötig; alles analytisch/Offline |
| ECMWF IFS + ecRad (2.1) | ✅ Vollständig | **ECMWF Open Data** (CC BY 4.0, seit 2025 kompletter Realtime-Katalog, `ssrd` Param. 169, 0,25° + 0,1°) | Operatives ECMWF-Ensemble (ENS) weiterhin kommerziell/Lizenz; Open Data deckt deterministische Läufe ab |
| ICON / ICON-D2 (2.2) | ✅ Vollständig | **DWD Open Data** (`opendata.dwd.de`, CC BY 4.0, auch kommerziell nutzbar, keine Registrierung) | Beste kostenlose Europa-Option (2,2 km, konvektionsauflösend) |
| GFS (2.3) | ✅ Vollständig | NOAA AWS Open Data (`noaa-gfs-bdp-pds`), NOMADS; Public Domain | Ebenso HRRR frei (3 km, USA) |
| HARMONIE (2.4) | ✅ Vollständig | KNMI Open Data (`english.knmidata.nl/open-data/harmonie`, 2 km, 2,5 Tage) | Regional auf Nordeuropa begrenzt |
| CAMS Radiation Service / -Verifikation (2.5) | ✅ Vollständig (Registrierung) | **CAMS Solar Radiation Time-Series & Forecast**: CC BY 4.0, gratis nach einfacher Registrierung; direkt via `pvlib.iotools.get_cams` | Verkauf der Rohdaten untersagt, Weitergabe ok |
| Sonnenposition / Linke-Turbidität / Perez / SMARTS (3) | ✅ Vollständig | pvlib (BSD-3), NREL SPA (frei), NSRDB-PWMIS-Turbiditäts-Karten, ASTM G173-Tabellen frei zitierbar | — |
| SolarAnywhere (4.1) | ❌ Nein | keine offene Alternative mit identischem Produkt | Kommerziell (Trial only); Selbstbau-CMV aus EUMETSAT-Daten als kostenlose Route |
| Solargis SFIA (4.2) | ❌ Nein | — | Kommerziell; kostenlose Gratis-Karten nur ohne Zeitreihe/Prognose |
| KNMI SICCS + AMV (4.3) | ✅ Prinzipiell ja | EUMETSAT **Core Data** (MSG/SEVIRI, CC BY 4.0, frei inkl. kommerzieller Nutzung) + KNMI-Open-Data-Algorithmen; SICCS-Code teils frei | Eigenbau-Aufwand hoch; Verifikationsdaten frei (BSRN/Cabauw) |
| All-Sky-Imager / bodenbasiert (4.4) | ✅ Hardware-Ausnahme | DIY-Fischeye + Raspberry Pi (~50–400 €, Open-Source-Software AllskyTeam/allsky, INDI Allsky); Trainingsdaten: SKIPP'D, SkyGPT-Datensatz (frei) | Kommerzielle ASI (z. B. EKO ASI-16) vierstellig € — für hobby/Prototyp nicht nötig |
| Hybridmodelle Post-Processing (5.1–5.3) | ✅ Vollständig | NWP-Open-Data-Inputs (ICON/GFS/ECMWF) + eigene Pyranometer-Messung oder CAMS-Referenz; XGBoost/LightGBM/scikit-learn (frei) | — |
| Ensemble- / Multi-Model-Fusion (5.5) | ✅ Vollständig | ICON + GFS + ECMWF Open Data selbst mischen (statt meteoblue MultiModel) | meteoblue MultiModel selbst ist kommerziell |
| ML-/Deep-Learning-Ergänzungen (Berichtsteil 2: LSTM, CNN, Transformer etc.) | ✅ überwiegend ja | Trainingsdaten frei: ERA5, CAMS, NSRDB, PVDAQ, SKIPP'D, Folsom; Frameworks frei (PyTorch, statsforecast/neuralforecast MIT) | Bei Foundation-Modellen Lizenz prüfen: Chronos/TimesFM/MOMENT Apache-2.0 ✅, Moirai CC BY-NC ⚠️ |
| Wetter-Foundation-Modelle (GraphCast, Aurora, AIFS, Pangu) | ✅ überwiegend ja | Aurora (MIT), WeatherNext/GraphCast/GenCast (Apache-2.0 + CC BY 4.0), ECMWF AIFS-Gewichte (CC BY 4.0, frei) | Pangu-Gewichte: Huawei-Lizenz prüfen (teils nicht-kommerziell) |

### 7.2 Kostenlose NWP-Datenquellen (Übersicht)

| Dienst | Kostenlos? | Bedingungen | URL |
|---|---|---|---|
| NOAA GFS / HRRR (GRIB) | ✅ | Public Domain, via AWS Open Data / NOMADS | https://registry.opendata.aws/noaa-gfs-bdp-pds/ |
| DWD ICON / ICON-EU / ICON-D2 | ✅ | **CC BY 4.0 — auch kommerziell**, keine Registrierung | https://opendata.dwd.de/ |
| ECMWF Open Data (IFS) | ✅ | CC BY 4.0, seit 2025 kompletter Realtime-Katalog | https://www.ecmwf.int/en/forecasts/datasets/open-data |
| ECMWF AIFS (KI-Wettermodell) | ✅ | Gewichte CC BY 4.0 / MIT, via `ecmwf-lab/ai-models` | https://www.ecmwf.int/en/forecasts/dataset/aifs-machine-learning-data |
| KNMI HARMONIE | ✅ | Open Data des KNMI | https://english.knmidata.nl/open-data/harmonie |
| GeoSphere Austria (vorm. ZAMG, MOSMIX) | ✅ | Open-Data-Programm, Attribution | https://www.geosphere.at/ |
| Open-Meteo API | ⚠️ eingeschränkt | **Nur nicht-kommerziell**, 10.000 Calls/Tag; kommerziell nur gegen Gebühr | https://open-meteo.com/ |
| Meteoblue Free API | ⚠️ Trial | 1 Jahr / 10 Mio. Credits, kommerziell lizenzpflichtig | https://docs.meteoblue.com/ |
| Meteomatics | ❌ | Kommerziell (Testphase) | https://www.meteomatics.com/en/pricing/ |

### 7.3 Kostenlose Strahlungs-, Satelliten- und Referenzdaten

| Dienst | Kostenlos? | Bedingungen | URL |
|---|---|---|---|
| **CAMS Solar Radiation** (Time-Series + Forecast, GHI/DNI/DHI) | ✅ | CC BY 4.0 inkl. kommerzieller Nutzung; Registrierung am Copernicus Data Store nötig | https://ads.atmosphere.copernicus.eu/datasets/cams-solar-radiation-timeseries |
| **PVGIS** (EU-JRC) | ✅ | Kostenlos, API frei; als öffentlicher EU-Dienst nutzbar | https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en |
| **EUMETSAT Core Data** (MSG/SEVIRI Rohbilder) | ✅ | CC BY 4.0, frei & kommerziell nutzbar; Registrierung im Data Store | https://user.eumetsat.int/ |
| GOES / Himawari via AWS | ✅ | Frei & offen (NOAA-Verteilung) | https://registry.opendata.aws/noaa-himawari/ |
| NASA POWER / MERRA-2 | ✅ | API frei, Attribution; MERRA-2 via AWS-Spiegel | https://power.larc.nasa.gov/ |
| **ERA5 / ERA5-Land** (Reanalysis) | ✅ | Copernicus-Lizenz (CC BY 4.0), CDS-Registrierung | https://cds.climate.copernicus.eu/ |
| SURFRAD (NOAA-Bodenmessnetz, USA) | ✅ | Public Domain | https://gml.noaa.gov/grad/surfrad/overview.html |
| NSRDB / SRRL (NREL) | ✅ | API-Key frei; via AWS Open Data | https://registry.opendata.aws/nrel-pds-nsrdb/ |
| BSRN (globales Referenzmessnetz) | ✅ | Zugang über Datenzentren, teils Registrierung | https://bsrn.awi.de/ |
| SOLEMI (DLR) | ⚠️ | Historischer Service derzeit offline; **Nachfolger: CAMS Radiation Service** | (via SoDa) |
| SolarAnywhere / Solargis / Solcast | ❌ | Kommerziell; Solcast „Free Rooftop" nur 10 API-Calls/Tag, nur Wohngebiete | https://solcast.com/free-rooftop-solar-forecasting |

### 7.4 Freie Trainingsdaten und Werkzeuge für ML-Ergänzungen

- **PV-Leistungsdaten:** NREL PVDAQ (frei), Open Power System Data (Lizenz je Paket prüfen), Stanford **SKIPP'D** (Sky-Images + PV-Leistung, 61 GB, frei), Folsom/SOLETE (UCSD, frei), Global PV Panel Dataset (Scientific Data 2025, CC BY, Zenodo).
- **Python-Stack (alles frei):** `pvlib` (BSD-3, Clear-Sky + CAMS-IO + PV-Simulation), `herbie` (MIT, NWP-GRIB-Download GFS/HRRR/ICON/ECMWF), `Meteostat` (MIT, Daten CC BY 4.0), `statsforecast`/`neuralforecast` (MIT/Apache), PyTorch.
- **Offene Solar-/Wetter-ML-Modelle:** OpenClimateFix *open-source-quartz-solar-forecast* (explizit frei, 0–48 h), SkyGPT-Code (GitHub), DiffCast (Open Source), Aurora (MIT), GraphCast/WeatherNext/GenCast (Apache-2.0 + CC BY 4.0), ECMWF AIFS-Gewichte (CC BY 4.0), Chronos/TimesFM (Apache-2.0), MOMENT (Apache-2.0); ⚠️ **Moirai (Salesforce): CC BY-NC — nicht kommerziell**, Pangu-Gewichte (Lizenz prüfen).
- **DIY-Sky-Camera:** Fischeye + Raspberry Pi (~50–400 €), Open-Source-Software (AllskyTeam/allsky, INDI Allsky); kommerzielle All-Sky-Imager erst für professionellen/bankable-Betrieb.

### 7.5 Fazit zur Einsetzbarkeit

1. **Reine Forschung / Hobby (z. B. Home-Assistant-PV-Prognose):** alles gratis — DWD ICON, CAMS Radiation, PVGIS, SKIPP'D; Achtung: Open-Meteo nur nicht-kommerziell, 10k Calls/Tag.
2. **Kommerzielles Produkt ohne Lizenzbudget:** vollständig legal und gratis mit **DWD ICON (GRIB) + ECMWF Open Data/AIFS + CAMS Radiation + ERA5-Land + pvlib/herbie** — alles CC BY 4.0 bzw. Public Domain. Kostenfaktor ist nur der Entwicklungsaufwand für GRIB-Verarbeitung und Post-Processing.
3. **Bankable / netzdienliche Prognosen mit SLA:** hier entsteht der Druck Richtung Solcast/Solargis/SolarAnywhere/Meteomatics, weil die Rohdaten zwar frei sind, aber Unsicherheitsquantifizierung und Verfügbarkeitsgarantien nicht. Workaround: Unsicherheit selbst aus Ensembles (ECMWF Open Data, AIFS-Ensembles, GenCast) ableiten.
4. **KI-Nowcasting:** Sky-Image-Route nur mit DIY-Kamera + freiem Trainingsdatensatz (SKIPP'D) sinnvoll; sonst Satellitensequenzen (EUMETSAT Core Data, CC BY 4.0) mit offenen Modellen (OCF-Quartz, DiffCast).
5. **Lizenzfallen:** Open-Meteo (NOK), Moirai (CC BY-NC), Pangu-Gewichte, Open Power System Data (Einzel-Lizenzen), Solcast-Free-Tier — vor produktiver Nutzung die aktuellen Nutzungsbedingungen prüfen.

---

## 8. Quellenliste

### Clear-Sky-Modelle
1. **Palani, K., Kota, R., Azad, A. P., Arya, V. (2017)**: "Blue Skies: A Methodology for Data-Driven Clear Sky Modelling", *Proceedings of the Twenty-Sixth International Joint Conference on Artificial Intelligence (IJCAI-17)*, pp. 3781–3782. — https://www.ijcai.org/proceedings/2017/ (PDF unter `/tmp/opencode/blueskies.pdf`)
2. **Ineichen, P., Perez, R. (2002)**: "A broadband hourly transmittance model: description and validation", *Solar Energy* — via pvlib-Dokumentation, https://pvlib-python.readthedocs.io/en/stable/user_guide/clearsky.html
3. **Perez, R. et al. (2002)**: "Operational modeling of clear sky solar radiation", *Solar Energy* — via pvlib-Dokumentation
4. **Gueymard, C. A. (2008)**: "REST2: Reference Evaluation of Solar Transmittance, 2 Bands", *Solar Energy* 82(11) — zitiert in Palani et al. 2017
5. **ASHRAE (1979, 2009)**: *Handbook of Fundamentals*, American Society of Heating, Refrigeration and Air-Conditioning Engineers — zitiert in Palani et al. 2017
6. **Haurwitz, B. (1945)**: "Insolation in relation to cloudiness and cloud velocity", *Journal of Meteorology* — zitiert in Palani et al. 2017
7. **Brest, C. L., Rossow, W. B., Schiffer, R. A. (2007)**: "New Cloud, Snow, and Cloud Shadow Detection Scheme for Operational Processing of Satellite Visible and Infrared Data", *J. Atmos. Oceanic Technol.* 24(3) — SPARC-Projekt (nicht Strahlungsmodell)
8. **pvlib-python Dokumentation (2026)**: "Clear Sky Modeling" — https://pvlib-python.readthedocs.io/en/stable/user_guide/clearsky.html

### NWP-basierte Strahlungsprognosen
9. **ECMWF (2026)**: "ecRad radiation scheme in ECMWF models" — https://www.ecmwf.int/en/documentation (IFS Documentation, Cycle 43r3, 2017, ~35 % Geschwindigkeitsverbesserung, 3,5 % der Modellrechenzeit)
10. **ECMWF Open Data (2026)**: Surface short-wave radiation downwards, Parameter 169 (`ssrd`), 0,25° + 0,1° ab 20. Oktober 2026
11. **Copernicus/CAMS (2025)**: "Quarterly Report on the Performance of the CAMS Radiation Forecast Products", Q2 2025, 41 Stationen — `/tmp/opencode/cams_eqc.pdf`; https://atmosphere.copernicus.eu/
12. **DWD (2026)**: ICON / ICON-D2 NWP-Forecast Data — https://www.dwd.de/EN/ourservices/nwp_forecast_data/nwp_forecast_data.html (ICON-D2 2,2 km / 65 Levels / 48 h, alle 3 h)
13. **NOAA (2026)**: GFS via CCPP, `module_radsw_main`, RRTMG, 5°-Aerosolklimatologie — https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast
14. **KNMI (2026)**: "Forecast of solar radiation in the Netherlands" (HARMONIE + SEVIRI + SICCS) — https://www.knmi.nl/kennis-en-datacentrum/project/forecast-of-solar-radiation-in-the-netherlands-1f0f3816-0854-47a6-9766-42cba229d8fb
15. **Wang, P., van Westrhenen, R., Meirink, J. F., van der Veen, S., Knap, W. (2019)**: "Surface solar radiation forecasts by advecting cloud physical properties derived from Meteosat Second Generation observations", *Solar Energy* 177, 47–58. — https://doi.org/10.1016/j.solener.2018.10.073 (RMSE 31–44 % GHI)
16. **KNMI Data Platform (2026)**: HARMONIE AROME CY43, 2 km, 1-h, 2,5 Tage — https://english.knmidata.nl/open-data/harmonie

### Transmissions-, Trübungs- und Sonnenstandsmodelle
17. **Reda, I., Andreas, A. (2004)**: "Solar Position Algorithm for Solar Radiation Applications", NREL Technical Report (NREL SPA, Genauigkeit < 0,003°) — https://midcdmz.nrel.gov/spa/
18. **Perez, R., Ineichen, P., Seals, R., Michalsky, J., Stewart, R. (1990)**: "Modeling daylight availability and irradiance components from direct and global irradiance", *Solar Energy* 44(5) — Perez-Transpositionsmodell
19. **Gueymard, C. A. (2003)**: "SMARTS2: A Simple Model of the Atmospheric Radiative Transfer of Sunshine: Algorithms and validation of a medically-insensible version", ASHRAE Transactions — ASTM G173-03 Referenzspektrum
20. **ASTM International (2012)**: ASTM G173-03 Standard Tables for Reference Solar Spectral Irradiances — https://www.astm.org/g0173-03r12.html
21. **pvlib-python (2026)**: `linke_turbidity`, `get_linke_turbidity` (NSRDB-PWMIS lookup) — https://pvlib-python.readthedocs.io/en/stable/
22. **NREL (2026)**: PVLIB-Python: Perez transposition model — https://github.com/pvlib/pvlib-python/blob/master/pvlib/irradiance.py

### Satelliten-Nowcasting (< 6 h)
23. **Clean Power Research (2026)**: SolarAnywhere Forecast — https://www.cleanpower.com/products/solaranywhere/forecast/ (CMV 1 Min–5 h, NWP-Blend 5 h–7 d, break-even 5–6 h)
24. **SolarAnywhere (2026)**: "Validation of Short and Medium Term Operational Solar Radiation Forecasts in the US" — `/tmp/opencode/sa_fc.pdf` (7 Standorte: 1-h CMV 46–110 W/m², 6-h 85–200 W/m², Satellitenreferenz 52–129 W/m²)
25. **Solargis (2026)**: "Forecast modelling" — https://kb.solargis.com/docs/forecast-modelling (optical-flow CMV, Bilder im Abstand 5–30 min, 6-h-Extrapolation, Updates alle 5/10/15 min, IFS bis D+3, GFS D+4–D+14)
26. **Solargis (2026)**: "Forecast subscription parameters" — https://kb.solargis.com/docs/forecast-subscriptions-details (4 NWP-Modelle: IFS, ICON, GFS, HRRR)
27. **Solargis (2026)**: "Satellite-based model" / "Data sources" — https://kb.solargis.com/docs/satellite-based-irradiance
28. **Kallio-Myers et al. (2022)**: "Comparison of irradiance forecasts from operational NWP model and satellite-based estimates over Fennoscandia", *Meteorological Applications* 29, e2051. — https://doi.org/10.1002/met.2051 (Solis-Heliosat besser erste 2–3 h, NWP danach; rRMSE 28,7–56,2 %)
29. **ASI-Benchmark (2022)**: All-Sky-Imager-Nowcasting, *Renewable Energy* — RMSE 6,9–18,1 %
30. **Utrecht University (2026)**: "Real-time solar irradiance forecasting for grid integration using all-sky imaging", KNMI Nubiscope, Cabauw — https://dspace.library.uu.nl/ (RMSE-Peaks > 35 W/m²)

### Hybridmodelle
31. **Bakker, K., Zhang, B., van der Meer, J., van der Burg, W., van der Meijde, M., Buis, E., Vergeer, A. (2019)**: "Comparison of statistical post-processing methods for solar irradiance forecasts based on the Harmonie-Arome NWP model", *Solar Energy* 191, 138–150. — arXiv:1904.07192, https://doi.org/10.1016/j.solener.2019.05.040 (7 Methoden, Quantile Regression + Generalized Random Forests am besten)
32. **Bellinguer et al.**: Kombination NWP + ML, ~40 % RMSE-Verbesserung — zitiert in der Solarprognose-Literatur
33. **arXiv (2020)**: "A day-ahead solar irradiance forecasting framework using gradient boosting" (Validierung GFS, Persistenz schlug rohes GFS, Hybrid am besten) — arXiv:2007.01639
34. **meteoblue (2021)**: "Solar power forecast accuracy verification based on independent BSRN/WRDC measurements" — https://www.meteoblue.com/ (ICON MAE 45,86–54,12; GFS 47,77–56,19; ERA5 39,95–48,41; MultiModel 42,54–51,06 W/m²)
35. **EPJ Photovoltaics (2023)** 14:15: "Benchmark of commercial intra-day solar irradiance forecasts" — 8 Anbieter, nRMSE 27–49 % @1 h, Satelliten nötig < 3 h, NWP ausreichend > 3–4 h

### Freie vs. kommerzielle Datenquellen (Abschnitt 7)
36. **AWS Open Data Registry** — NOAA GFS: https://registry.opendata.aws/noaa-gfs-bdp-pds/ · NOAA HRRR: https://registry.opendata.aws/noaa-hrrr-pds/
37. **DWD Open Data Server** (ICON/ICON-EU/ICON-D2, CC BY 4.0): https://opendata.dwd.de/
38. **ECMWF Open Data** (IFS + AIFS, CC BY 4.0): https://www.ecmwf.int/en/forecasts/datasets/open-data — "Entire Realtime Catalogue open to all" (2025): https://www.ecmwf.int/en/about/media-centre/news/2025/ecmwf-makes-its-entire-realtime-catalogue-open-all — AIFS: https://www.ecmwf.int/en/forecasts/dataset/aifs-machine-learning-data
39. **Open-Meteo** Terms / Pricing (NOK-Restriktion, 10k Calls/Tag): https://open-meteo.com/en/terms · https://open-meteo.com/en/pricing/
40. **Copernicus CAMS** Solar Radiation Time-Series (CC BY 4.0): https://ads.atmosphere.copernicus.eu/datasets/cams-solar-radiation-timeseries · Radiation Service via pvlib: https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iotools.get_cams.html
41. **PVGIS** (EU-JRC): https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en
42. **Solcast** Free Rooftop Tier (10 Calls/Tag): https://solcast.com/free-rooftop-solar-forecasting
43. **NASA POWER**: https://power.larc.nasa.gov/
44. **EUMETSAT** Data Policy (Core Data CC BY 4.0): https://user.eumetsat.int/resources/user-guides/data-registration-and-licensing — Himawari via AWS: https://registry.opendata.aws/noaa-himawari/
45. **NOAA SURFRAD**: https://gml.noaa.gov/grad/surfrad/overview.html — **NREL NSRDB** (AWS): https://registry.opendata.aws/nrel-pds-nsrdb/ — **BSRN**: https://bsrn.awi.de/
46. **Copernicus CDS** (ERA5 / ERA5-Land): https://cds.climate.copernicus.eu/ — **NASA MERRA-2** (AWS): https://registry.opendata.aws/nasa-merra-2/
47. **NREL PVDAQ**: https://data.openei.org/submissions/4568 — **Open Power System Data**: https://data.open-power-system-data.org/ — **Stanford SKIPP'D**: https://github.com/yuhao-nie/Stanford-solar-forecasting-dataset — **Global PV Panel Dataset** (Sci Data, CC BY): https://www.nature.com/articles/s41597-025-04985-y
48. **pvlib-python** (BSD-3): https://github.com/pvlib/pvlib-python — **herbie**: https://herbie.readthedocs.io/ — **Meteostat** (MIT, Daten CC BY 4.0): https://dev.meteostat.net/license — **nixtla**: https://github.com/nixtla/statsforecast
49. **Open Climate Fix** open-source-quartz-solar-forecast: https://github.com/openclimatefix/open-source-quartz-solar-forecast — **Aurora** (Microsoft, MIT): https://github.com/microsoft/aurora — **WeatherNext/GraphCast/GenCast** (Apache-2.0 + CC BY 4.0): https://github.com/google-deepmind/weathernext — **Chronos** (Apache-2.0): https://github.com/amazon-science/chronos-forecasting — **TimesFM**: https://github.com/google-research/timesfm — **MOMENT**: https://github.com/moment-timeseries-foundation-model/moment — **Moirai** (CC BY-NC 4.0!): https://github.com/SalesforceAIResearch/uni2ts
50. **EKO Instruments** All Sky Imagers (kommerziell): https://eko-instruments.com/us/product-category/all-sky-imagers/ — **DIY Allsky** (Open Source): https://github.com/AllskyTeam/allsky — **GeoSphere Austria**: https://www.geosphere.at/ — **SolarAnywhere EULA**: https://www.solaranywhere.com/license/

---

*Hinweis: Alle PDF-Extraktionen und Zwischenergebnisse liegen unter `/tmp/opencode/` (`blueskies.txt`, `cams_eqc.txt`, `sa_fc.txt`, `diva.txt`). Die HARMONIE-Auswertung (MDPI Atmos. 9(5):163) war aufgrund von Zugangsbeschränkungen nicht verfügbar; die KNMI-Projektseite liefert die qualitativen Eckdaten.*
