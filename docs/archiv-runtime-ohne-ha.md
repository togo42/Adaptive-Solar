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

Der Installationsnachweis wird nach Hostreadback ergänzt.
