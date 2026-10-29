# Archivhost ohne lokale Home-Assistant-Installation

Stand: 29.10.2026. Expliziter Betreiberauftrag: HA Core vom Archivhost entfernen
und bei künftigen Installationen/Updates ausschließen. Das betrifft ausschließlich
den Collector-/Replayhost, nicht die produktive Home-Assistant-Instanz.

## Installation und Updates

`scripts/install_archive_host.py --venv PFAD` erzeugt eine isolierte Pythonumgebung
oder aktualisiert eine vorhandene HA-freie Umgebung. Es installiert ausschließlich
das reguläre Projekt und die direkten Pins aus dem aktuellen Komponentenmanifest.
`deploy/archive-host-constraints.txt` enthält unerfüllbare Versionsbedingungen für
`homeassistant` und `pytest-homeassistant-custom-component`. Eine versehentlich
hinzukommende direkte oder transitive Anforderung führt damit zum Resolverfehler.
Die Sperre ist für jeden Installerlauf verpflichtend, auch mit zusätzlichen Pins.

Vor und nach der Installation prüft ein isolierter Pythonprozess, dass der
erwartete venv verwendet wird, keine HA-Distributionen installiert sind und auch
kein übrig gebliebenes HA-Modul importierbar ist. Systempakete sind ausgeschlossen.
Nach der Installation muss `pip check` erfolgreich sein. Der Installer entfernt
bestehende Pakete nicht automatisch: Eine alte HA-Umgebung wird bewusst abgelehnt,
statt sie während eines unbemerkten Updates umzubauen. Entwicklung und native
HA-Tests behalten ihre getrennten Abhängigkeiten.

Pip erhaelt keine geerbten `PIP_*`-Einstellungen; `PIP_CONFIG_FILE=/dev/null`
deaktiviert globale, Benutzer- und venv-Konfigurationen. `--no-user` und
`PIP_REQUIRE_VIRTUALENV=1` binden die Installation an die Zielumgebung.
Der Postflight importiert zusaetzlich die tatsaechlichen Laufzeitmodule
(aiohttp, NumPy, SciPy, pvlib, sklearn und das Kernmodell) und prueft ihre
Dateipfade innerhalb des Ziel-venv. Eine leere oder per `.pth` umgeleitete
Umgebung kann damit keinen erfolgreichen Lauf vortaeuschen. Ein echter
Offline-pip-Test prueft sowohl `PIP_TARGET` als auch eine abweichende
Konfigurationsdatei, ohne ausserhalb des temporaeren Ziel-venv zu installieren.

Für neue Releases den Installer vor dem Aktivieren des Releasepfads ausführen
und anschließend die Collector-/Replay-CLIs sowie kontrollierte Aufnahmen prüfen.
Private Runtimepins können mit `--constraints` ergänzt werden. Abhängigkeiten
werden nicht zwischen HA und Host kopiert. Der zusätzliche CI-Job baut eine neue
HA-freie Umgebung und prüft die CLI-Importe; ein konfigurierter CI-Job ist allein
noch kein Nachweis eines bereits erfolgreich gelaufenen externen CI-Laufs.

## Daten und Replay-Provenienz

Archiv, Hashablage, Pins, Zeitauflösung und numerische Lern-/Physikverfahren
benötigen keinen lokalen HA-Core. Die Wetteraufnahme und Auswertung verwenden
weiterhin pvlib, NumPy/SciPy, Pandas und scikit-learn. Zugriff auf die produktive
HA-Instanz erfolgt weiterhin über deren authentifizierte Leseschnittstellen.

`software_provenance()` dokumentiert die tatsächlich installierten Versionen.
Ohne lokales HA wird `libraries.homeassistant` korrekt `null`; es wird kein
fingiertes Paket oder falscher Versionsnachweis hinterlegt. Die bisherige
Replayabnahme vergleicht Quellhash und sämtliche erfassten Bibliotheksversionen
streng. Eine historische Aufnahme mit `homeassistant=2026.10.4` kann deshalb nach
der Entfernung numerisch passen, aber kein vollständiges Umgebungsmatch mehr
erreichen. Das Ergebnis bleibt dann `matched=true`, `software_match=false`,
`accepted=false`. Ein abweichender Quellhash bleibt ebenfalls ein Ablehnungsgrund.
Es werden weder Toleranzen noch Herkunftsgates abgeschwächt. Frühere akzeptierte
Replays gelten ausschließlich für ihre damalige dokumentierte Umgebung.

## Prüfung und Betriebsnachweis

Tests prüfen reale isolierte Umgebungen, zurückgebliebene Module/Metadaten,
verpflichtende Constraints auch beim Update und echte pip-Resolverablehnungen
für beide gesperrten Pakete. **63 gezielte Installer-/Runner-/Original- und
Schattenreplaytests** bestanden; ein danach ergänzter Regressionstest bestätigt
zusätzlich, dass die Entfernung der HA-Version keine historische Originalabnahme
vortäuscht. Ruff und `pip check` sind erfolgreich.

Für die beauftragte Umstellung werden vorab die Paketversionen beider bisherigen
Umgebungen verglichen. Bei identischen Laufzeitabhängigkeiten können die alten
Umgebungspfade auf dieselbe neue HA-freie Laufzeit verweisen. Die ursprünglichen
Releasequellen bleiben getrennt erhalten. Neue oder abweichende numerische Pins
benötigen eine eigene Laufzeit; gemeinsam genutzte Umgebungen nicht unbemerkt
bei einem späteren Release verändern.

## Installierter Stand und Betriebsnachweis

Am 29.10.2026 ist Commit `770361b46fe342cf60e1e6e193d59f990835b88f` auf dem
Archivhost aktiviert. 189 öffentliche Quelldateien wurden gegen das lokale
Manifest geprüft; Transferarchiv-SHA256
`6dce709c0428ebef97d5949cbe04e70ba2a91466db80959d9b822a9424c1a6ef`.
Erstinstallation und anschließendes echtes Update derselben neuen Umgebung
bestanden mit dem verpflichtenden Installer. Alle sechs Collector-/Replay-CLIs
importieren ohne HA, `pip check` ist erfolgreich, die bisherigen numerischen
Paketversionen sind erhalten.

Die Paketversionen der alten 0.2.16-/0.2.17-Umgebungen unterschieden sich nur bei
`adaptive-solar-ha` selbst; alle anderen waren gleich. Beide alten Umgebungspfade
verweisen nun auf dieselbe neue Laufzeit. Die alten Paketverzeichnisse einschließlich
HA Core wurden nach erfolgreichen Aufnahme-/Replayprüfungen gelöscht. Die
ursprünglichen Releasequellen sind weiterhin getrennt verfügbar; ihre Skripte
laden die Komponenten aus dem jeweiligen Quellbaum.

Gemessener Umgebungsplatz vor der Umstellung: **1.562.250.240 Byte**; danach
**272.081.920 Byte** (rund **260 MiB**), Ersparnis **1.290.168.320 Byte**
(rund **1,20 GiB**). Das ist die gemessene Dateibelegung, keine Aussage über
zusätzliche Poolbelegung durch historische Dateisystem-/PBS-Sicherungen.

Alle vier Archivtimer sind aktiv; kontrollierte HA-, Wetter-, Beobachtungs- und
Retentionläufe erfolgreich. Die acht neuesten Wetterprodukte sind verfügbar und
tragen wahrheitsgemäß `libraries.homeassistant=null` für die Hostumgebung.
Index und Pins waren beim Releasewechsel bytegleich; private Hostkonfiguration,
Archivlayout und produktive HA-Einstellungen wurden nicht verändert.

Vier eingefrorene Originalprognosen wurden mit den ursprünglichen Quellen in
der neuen Laufzeit erneut gerechnet: alle numerisch passend, maximale Abweichung
`9,095e-13 W`. Quellhash und alle bisher verglichenen numerischen Bibliotheken
stimmen mit den Aufnahmen überein; einzige Bibliotheksabweichung ist die entfernte
HA-Version. Alle vier Berichte melden deshalb korrekt `software_match=false`
und `accepted=false`. Der historische positive Nachweis vom 28.10.2026 wird
nicht auf diese veränderte Umgebung übertragen.

Private Paketlisten und Prüfbelege liegen lokal unter
`data/archive-no-ha-20261029/`. Der neue CI-Job ist implementiert; in diesem
Arbeitsauftrag wurde kein externer CI-Lauf ausgelöst.
