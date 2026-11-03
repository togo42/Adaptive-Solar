# Rust für die Archivverarbeitung bewerten

Stand: 03.11.2026. Rust wurde als mögliche spätere Umsetzung eines begrenzten
Hostbausteins betrachtet. Es gibt in diesem Arbeitsstand weder eine
Rustimplementierung noch einen gemessenen Rust-Geschwindigkeitsvorteil.

## 1. Nachgewiesener Restaufwand

Die [Originalvalidierung](performance-originalvalidierung.md) vermeidet bereits
zwei wiederholte Python-Schlüsselbaumdurchläufe je Envelope. Ein erneutes
lokales Phasenprofil zeigt weiterhin den wesentlichen Aufwand vor
`build_quality`: Originallesen/-prüfung, kanonische Serialisierung und
Konfigurationsaufbereitung. Die reine Stundensuche ist im geprüften Fall klein.
Inklusive Profilzeiten überlappen und sind keine uninstrumentierten
Laufzeitanteile.

Ein Sprachwechsel beseitigt keine unnötigen Originalzugriffe. Deshalb wird
zuerst das Potenzial einer [vollständigkeitserhaltenden Auswahl](performance-archivauswahl.md) untersucht.
Sollten danach hohe Rechenkosten verbleiben, ist ein gebündelter Rustbaustein
ein konkreter Vergleichskandidat.

## 2. Sinnvoller Umfang

Ein optionaler Hosthelfer könnte große Byteblöcke gebündelt lesen, prüfen und
benötigte Metadaten ableiten. Eine PyO3-Erweiterung könnte den Prozessübergang
vermeiden, müsste dafür Pythonobjekt-Konvertierungen und ABI-/Paketaufwand
mitmessen. Viele kleine Übergaben pro Ereignis sind kein geeigneter
Geschwindigkeitsnachweis. Die [PyO3-Performancehinweise](https://pyo3.rs/main/performance.html)
beschreiben unter anderem Konvertierungs- und Allokationskosten.

Ein konkreter erster Schnitt wäre
`scan_validate_project_batches(paths, query)`: vollständige Batchprüfung,
anschließend originalgetreue ausgewählte Ereignisbytes und Abhängigkeitsbelege
gebündelt zurückgeben. Große irrelevante Wetterpayloads müssten dann keine
Pythonobjekte werden. Der bisherige Qualitätsverbraucher behielte Gates und
reale Verfügbarkeitszeiten. Externe JSON-Aussagen dürfen dabei keine ungeprüften
internen Konfigurationsbelege erzeugen. Eine Portierung der Stundensuche hat
nach dem lokalen Restprofil geringere Priorität.

JSON-Encoding, Gzip und SHA nutzen in der geprüften Pythonumgebung bereits
native Implementierungen. Ein einfacher Austausch dieser Bibliotheken ist
deshalb kein belegter Beschleunigungsschritt. Relevanter wären weniger
Pythonobjekte und zusammengefasste Verarbeitungsschritte, sofern deren
End-to-End-Vorteil tatsächlich gemessen wird. Primärquellen:
[CPython-JSON-Encoder](https://github.com/python/cpython/blob/v3.14.4/Lib/json/encoder.py),
[Python-Gzip](https://docs.python.org/3.14/library/gzip.html) und
[Python-Hashlib](https://docs.python.org/3.14/library/hashlib.html).

## 3. Byte- und Fehlersemantik erhalten

Die Archivprüfsumme verwendet die konkrete Pythonserialisierung
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False)` und striktes UTF-8. Das ist keine beliebig austauschbare
JSON-Kanonisierung. Der öffentliche Pythonpfad verlangt außerdem durchgehend
Stringschlüssel. Die [JSON-Dokumentation](https://docs.python.org/3.14/library/json.html)
beschreibt die einzelnen Optionen; maßgeblich bleibt der gepinnte lokale Code.

Ein Rustkandidat muss insbesondere dieselben Ergebnisse liefern für:

- Ganzzahlen und Fließkommazahlen, Exponentenformat, `-0.0` und Grenzwerte;
- große Ganzzahlen und die tatsächlich aktiven Python-Lesegrenzen;
- nichtendliche Zahlen und überlaufende JSON-Exponenten;
- Unicode, Escapes, Surrogatpaare und isolierte Surrogate;
- doppelte Schlüssel, Sortierung, Stringschlüsselpflicht und Rekursionsgrenzen;
- beschädigte Originale, Hashkonflikte und vollständige Auswahlgegenbelege.

Die Standard-Zahlenrepräsentation von Serde ist kein Nachweis dieser
Pythonidentität. Dokumentierte Bereiche und Sonderfälle stehen bei
[`serde_json::Number`](https://docs.rs/serde_json/1.0.154/serde_json/struct.Number.html).
[`RawValue`](https://docs.rs/serde_json/latest/serde_json/value/struct.RawValue.html)
kann Originalformatierung erhalten; Originaltext ersetzt jedoch nicht den
kanonischen Envelopehash. Ein schneller Parser allein ist deshalb noch kein
verhaltensgleicher Archivreader.

## 4. Nächster Rust-Nachweis

Ein begrenzter Versuch beginnt mit synthetischen Originalen und absichtlich
beschädigten Eingaben. Zuerst werden Bytes, Hashes und Ablehnungen gegen die
gepinnten Pythonfunktionen geprüft. Erst danach folgen komplette Batchläufe
einschließlich Ein-/Ausgabe und Pythonübergabe. Toolchain, Crates, Features und
Buildprofil müssen reproduzierbar gebunden sein; ein Rustmikrobenchmark ohne
Übergaben belegt keinen Hostvorteil.

Die konkrete lokale Toolchain-Verfügbarkeit und Installationsdetails gehören
in die private Betriebsdokumentation. Eine spätere Umsetzung bleibt optional
für den Archivhost und erzeugt keine neue Rust-Pflichtabhängigkeit der
HA-Integration. Eine Portierung oder produktive Aktivierung ist durch diese
Bewertung nicht umgesetzt.
