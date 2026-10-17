# TachoArchiv

Linux-Programm mit grafischer Oberfläche zum **Auslesen, Archivieren und Auswerten von Fahrerkarten** (digitaler Fahrtenschreiber, Generation 1 und 2).
Oberfläche in **30 Sprachen**, installierbar auf **jeder Linux-Distribution**.

Eine vollständige **Bedienungsanleitung** liegt unter [`doc/bedienungsanleitung.md`](doc/bedienungsanleitung.md) und im Paket unter `/usr/share/doc/tachoarchiv/`; im Programm steht sie unter **Hilfe ▸ Bedienungsanleitung**. Als PDF setzen lässt sie sich mit `python tools/manual_pdf.py`.

## Funktionen

- Signierter Download der Fahrerkarte über jeden PC/SC-Kartenleser (Gen1 und Gen2/Smart Tachograph)
- Import vorhandener Kartendateien (`.DDD`, `.C1B`, `.TGD`)
- Archivierung von **Fahrzeug-Downloads** (Massenspeicher, `.DDD`/`.V1B`/`.V2B`) vom Downloadkey: Kennzeichen, Fahrgestellnummer, Zeitraum und Inhalt werden erfasst, die Datei bleibt unverändert
- Revisionssicheres Archiv: Originaldateien bleiben unverändert und schreibgeschützt, SHA-256-Prüfsumme, Duplikaterkennung, Funktion „Archiv prüfen“
- Mehrere Downloads desselben Fahrers werden automatisch zusammengeführt
- Tagesansicht als Stufendiagramm (Lenken, Arbeit, Bereitschaft, Ruhe)
- Kalender links: Tage mit Daten fett, Lenkzeit als Fußbalken, Tage mit Verstoß oder Warnung farbig markiert; ein Klick öffnet den Tagesreiter
- Reiter **Restzeit**: Prognose der noch zulässigen Lenkzeit (Tag, Woche, Doppelwoche, freie Verlängerungen und reduzierte Tagesruhen, Frist bis zur Wochenruhe) mit Herleitung und Rechtsgrundlage
- Reiter **Schichten** mit Kennzahlen je Schicht; Verstöße sind hinterlegt
- **Geschwindigkeitsauswertung** aus dem Fahrzeug-Massenspeicher: Tagesverlauf als Diagramm, Überschreitungen und Stundenwerte als Tabelle, Ausgabe als CSV
- **Zugangsschutz** für das Archiv: auf Wunsch verschlüsselt (AES-256-GCM), mit Passwort, Wiederherstellungsschlüssel und Selbstsperre
- **Prüfung der Kartensignaturen** gegen den hinterlegten Wurzelschlüssel der ERCA (Generation 1 und 2)
- PDF-Bericht wahlweise vollständig oder nur mit den Verstößen, und in einer anderen Sprache als der Oberfläche
- Auswertung nach VO (EG) 561/2006 i. d. F. VO (EU) 2020/1054, VO (EU) 165/2014 und VO (EU) 581/2010, optional ArbZG § 21a; Stand September 2026
- Zeiträume: alles, 56 Tage (Kontrollzeitraum), 28 Tage, 12 Monate
- Bericht als PDF und Export als CSV
- Kein Netzwerkzugriff: die Fahrerdaten verlassen den Rechner nicht

### Geprüfte Regeln

Abdeckung des Nachweiszeitraums (laufender Tag und 56 vorausgehende Tage, einstellbar), Lenkzeitunterbrechung (4,5 h / 45 min, Aufteilung 15 + 30 min), tägliche Lenkzeit (9 h, zweimal pro Woche 10 h), tägliche Ruhezeit (11 h, reduziert 9 h, höchstens dreimal), wöchentliche Ruhezeit (spätestens nach sechs 24-h-Zeiträumen) samt Ausgleich reduzierter Wochenruhe bis Ende der dritten Folgewoche, wöchentliche Lenkzeit (56 h), Doppelwochen-Lenkzeit (90 h), Arbeitszeitgesetz (Ruhepausen, 10 h täglich, 60 h wöchentlich, 48-h-Durchschnitt), Download-Intervall der Karte (28 Tage), Ablauf der Karte, Aufzeichnungslücken.

### Fähre und Eisenbahn (Art. 9 VO (EG) 561/2006)

Kennzeichnet der Fahrer auf der Karte eine Fähr- oder Zugüberfahrt, gilt eine dadurch unterbrochene Ruhezeit nicht als abgebrochen. Geprüft wird:

- höchstens **zwei** Unterbrechungen von zusammen höchstens **einer Stunde**; darüber hinaus zählt die Ruhezeit als unterbrochen
- die Ausnahme gilt nur für die **regelmäßige tägliche** (11 h) und die **wöchentliche** Ruhezeit, nicht für eine reduzierte Tagesruhe
- eine **regelmäßige wöchentliche** Ruhezeit darf nur bei einer Überfahrt ab **8 Stunden** unterbrochen werden
- Karten der 1. Generation kennzeichnen nur den Beginn der Überfahrt; das Ende wird dann auf den Beginn der nächsten Lenkzeit geschätzt und im Bericht als Schätzung ausgewiesen

Überfahrten erscheinen als violetter Balken über dem Tagesdiagramm und als Zeile unter „Ereignisse“. Die Prüfung lässt sich in den Einstellungen abschalten. Ob dem Fahrer eine Schlafkabine oder Liege zur Verfügung stand, ist auf der Karte nicht gespeichert und kann nicht geprüft werden.

## Voraussetzung auf dem Rechner

Der Kartenleser wird über den PC/SC-Dienst des Systems angesprochen:

```sh
# Debian/Ubuntu
sudo apt install pcscd
# Fedora
sudo dnf install pcsc-lite
# Arch
sudo pacman -S pcsclite ccid

sudo systemctl enable --now pcscd.socket
```

## Installation

### Beliebige Distribution – `install.sh`

```sh
./install.sh            # systemweit nach /usr/local (fragt per sudo nach Rechten)
./install.sh --user     # nur für den aktuellen Benutzer, nach ~/.local
```

Das Skript erkennt die Distribution und holt über deren Paketverwaltung, was fehlt: die PC/SC-Bibliothek, `pcscd`, die Noto-Schriften und Qt. Unterstützt werden Debian und Ubuntu (apt), Fedora und RHEL (dnf), Arch (pacman), openSUSE (zypper) und Alpine (apk); bei unbekannter Paketverwaltung überspringt es diesen Schritt und nennt, was zu tun bleibt.

Findet sich **kein PySide6** in den Paketquellen – etwa unter Debian 12 oder Ubuntu 24.04 –, legt das Skript eine eigene Python-Umgebung unter `<prefix>/lib/tachoarchiv/venv` an und holt Qt aus PyPI (etwa 100 MB). Damit läuft das Programm auch dort, wo die Distribution Qt 6 für Python nicht anbietet. Erzwingen lässt sich dieser Weg mit `--venv`, unterdrücken lassen sich alle Installationen mit `--no-deps`.

Weitere Optionen: `--prefix=/opt/tachoarchiv` für ein eigenes Ziel, `--help` für die Übersicht.

Entfernt wird mit `./uninstall.sh` (bzw. `--user` oder `--prefix=…`). Archiv und Einstellungen bleiben dabei erhalten; `--purge` löscht sie nach Rückfrage mit.

### Debian-Paket bauen und installieren

Für Debian und Ubuntu gibt es zusätzlich das native Paket. Voraussetzung ist **Debian 13 (Trixie) oder neuer** bzw. Ubuntu 25.04 oder neuer – ältere Versionen haben keine PySide6-Pakete (dort ist das Flatpak der Weg).

```sh
sudo apt install debhelper dh-python python3-all python3-setuptools pybuild-plugin-pyproject
dpkg-buildpackage -us -uc -b
sudo apt install ../tachoarchiv_1.5.0_all.deb
```

Das Paket installiert das Programm nach `/usr/bin/tachoarchiv`, den Python-Teil nach `/usr/lib/python3/dist-packages/tachoarchiv`, dazu Menüeintrag, Symbol, AppStream-Datei und Handbuchseite (`man tachoarchiv`). `pcscd` wird als *Recommends* mitinstalliert, der Kartenleser funktioniert also ohne weiteres Zutun.

### Flatpak bauen und installieren

Benötigt `flatpak` und `flatpak-builder`.

```sh
./build.sh
flatpak install --user TachoArchiv.flatpak
flatpak run io.github.tachoarchiv.TachoArchiv
```

`build.sh` lädt die KDE-Runtime 6.8 und die PySide-BaseApp von Flathub, baut die App und erzeugt das Bundle `TachoArchiv.flatpak`, das auf andere Rechner kopiert werden kann.

## Fahrzeug-Massenspeicher

Fahrzeugdateien werden über denselben Menüpunkt importiert wie Kartendateien und landen im Reiter **Fahrzeuge** links. Erfasst werden Fahrgestellnummer, Kennzeichen, Gerätegeneration, herunterladendes Unternehmen, der im Gerät gespeicherte Zeitraum und welche Datenbereiche die Datei enthält. Liegt der letzte Download länger als 90 Tage zurück, wird das farbig hervorgehoben – das ist die Frist für den Massenspeicher, während die Fahrerkarte alle 28 Tage fällig ist.

Ausgewertet wird aus dem Inhalt bislang die **Geschwindigkeit**: der Massenspeicher führt je Sekunde einen Wert (TREP 0x04 bei Generation 1, 0x24/0x34 bei Generation 2). Im Reiter **Fahrzeug ▸ Geschwindigkeit** stehen der Tagesverlauf, die Abschnitte über dem eingestellten Grenzwert und die Stundenwerte; die Sekundenwerte lassen sich als CSV ausgeben. Unterbrechungen bis 30 s und Abschnitte unter 5 s werden zusammengefasst, sonst zerfällt eine Überschreitung in hundert Zeilen. Sätze mit unglaubwürdigem Zeitstempel oder Wert werden übergangen – lieber keine Kurve als eine erfundene.

Die übrigen Bereiche werden nicht ausgewertet; das Programm archiviert sie revisionssicher und weist nach, was wann gelesen wurde. Sind die Kopfdaten einer Datei unlesbar, wird sie trotzdem aufbewahrt – Archivieren geht vor Auswerten.

**Hinweis:** Die Geschwindigkeitsauswertung ist bislang nur gegen selbst erzeugte Dateien geprüft, nicht gegen einen echten Download aus einem DTCO. Die Satzlängen bei Generation 2 können abweichen; Rückmeldungen mit einer echten Datei sind willkommen.

## Sprachen

Deutsch, Englisch, Albanisch, Bulgarisch, Estnisch, Französisch, Griechisch, Italienisch, Kroatisch, Lettisch, Litauisch, Niederländisch, Polnisch, Portugiesisch, Rumänisch, Serbisch (kyrillisch und lateinisch), Slowakisch, Slowenisch, Spanisch, Tschechisch, Ungarisch – dazu Ukrainisch, Russisch, Weißrussisch, Türkisch, Arabisch, Hindi, Urdu und Punjabi.

Die lateinische Fassung des Serbischen wird nicht getippt, sondern mit `tools/sr_latn.py` aus der kyrillischen umgeschrieben; ein Test hält beide deckungsgleich. Nach einer Änderung an `sr.json` also das Skript noch einmal laufen lassen.

Die Texte liegen als JSON je Sprache unter `tachoarchiv/locale/`. Eine Formulierung ändern heißt: Datei öffnen, Zeile ändern, fertig – kein Neuübersetzen und kein Eingriff in den Code. Eine neue Sprache braucht eine Datei mit denselben Schlüsseln und einen Eintrag in `LANGUAGES` in `i18n.py`; ein Test prüft, dass alle Dateien dieselben Schlüssel und Platzhalter haben.

Arabisch und Urdu werden von rechts nach links dargestellt, die Oberfläche spiegelt sich dabei komplett. Die nötigen Schriften bringt `fonts-noto-core` mit – arabisch, Nastaliq für Urdu, Devanagari und Gurmukhi. Das Paket wird als Abhängigkeit automatisch mitinstalliert (rund 42 MB).

Die Übersetzungen sind maschinell erstellt und nicht von Muttersprachlern gegengelesen. Die Fachbegriffe folgen der Terminologie der EU-Verordnungen, einzelne Formulierungen können trotzdem holprig sein.

## Wenn das Auslesen fehlschlägt

Unter **Hilfe → Kartendiagnose** sendet das Programm ausschließlich lesende Testbefehle an die Karte und zeigt ATR, Protokoll und die Antwort auf jeden Befehl. Damit lässt sich feststellen, welche Befehlsform die Karte akzeptiert. Die Ausgabe enthält keine Fahrerdaten und lässt sich in die Zwischenablage kopieren. Am Ende steht die erkannte **Kartenart** – Fahrer-, Werkstatt-, Kontroll- oder Unternehmenskarte. Nur Fahrerkarten werden ausgewertet.

Eine einzelne nicht lesbare Datei bricht den Download nicht mehr ab: Sie erscheint als Warnung, die übrigen Dateien werden archiviert.

Lässt eine Karte ihr Stammverzeichnis nicht auswählen, erscheint nach dem Auslesen ein Hinweis in der Statuszeile: die Kennungsdateien EF_ICC und EF_IC fehlen dann im Archiv, auf die Auswertung hat das keinen Einfluss.

Häufige Statuswörter: `6A86` falsche Parameter P1/P2 (die Karte verlangt eine andere Form der Dateiauswahl – das Programm probiert von sich aus mehrere durch), `6700` falsche Länge (Blockgröße bzw. Signaturlänge – wird automatisch angepasst), `6982` Sicherheitsbedingung nicht erfüllt (die Datei zeigt sich nur einem authentisierten Fahrzeuggerät, bei Werkstattkarten fehlt die PIN) – erscheint als Hinweis, nicht als Fehler, `6A82` Datei nicht gefunden, `6982` Sicherheitsbedingung nicht erfüllt, `6D00`/`6E00` Befehl oder Befehlsklasse nicht unterstützt (dann steckt meist keine Fahrerkarte, sondern eine andere Chipkarte im Leser).

## Ohne Kartenleser ausprobieren

Menü **Datei → Demodaten laden** legt einen Beispielfahrer mit 38 Tagen an, der gezielt einige Verstöße und Hinweise enthält.

## Entwicklung

Direkt ohne Flatpak starten (PySide6 und pcscd erforderlich):

```sh
pip install PySide6
python3 -m tachoarchiv
```

Tests der Kernlogik (ohne Qt):

```sh
python3 tests/test_core.py
```

Umgebungsvariable `TACHOARCHIV_PCSCLIB` setzt einen abweichenden Pfad zur `libpcsclite.so.1`.

## Datenablage

Standardmäßig im Datenverzeichnis der App (im Flatpak unter `~/.var/app/io.github.tachoarchiv.TachoArchiv/`), änderbar in den Einstellungen:
`archiv.sqlite` (Index) und `ddd/<Kartennummer>/C_<Datum>_<Name>_<Kartennummer>.DDD`.
Die Aufbewahrungsfrist (Standard 2 Jahre) ist einstellbar.

### Zugangsschutz

Voreingestellt ist **kein Passwort**; die Dateien liegen dann unverschlüsselt im Archivordner. Unter **Archiv ▸ Zugang** lässt sich der Schutz einschalten: ein zufälliger Archivschlüssel verschlüsselt alle Archivdateien und den Index mit AES-256-GCM, der Schlüssel selbst liegt mit dem Passwort und mit einem Wiederherstellungsschlüssel umschlossen in `zugang.json` (scrypt). Dateinamen und Unterordner werden dabei durch Kennungen ohne Aussagekraft ersetzt – sonst verrät schon das Verzeichnis, wessen Daten dort liegen. Das Archiv sperrt sich nach einstellbarer Zeit ohne Bedienung selbst und kann beim Programmstart gesperrt bleiben.

Das ist für ein **gemeinsam genutztes Benutzerkonto** gedacht, auf dem Dateirechte niemanden trennen. Zwei Dinge leistet es nicht: Solange das Archiv entsperrt ist, kommt jeder an die Daten, der an den laufenden Rechner kommt. Und wer Administratorrechte hat, kommt an den Schlüssel im Speicher – dagegen hilft nur die Verschlüsselung des Datenträgers.

**Ohne Passwort und ohne Wiederherstellungsschlüssel sind die Daten endgültig verloren.** Es gibt keine Hintertür. Die Aufbewahrungspflicht gilt trotzdem: Wiederherstellungsschlüssel ausdrucken und getrennt vom Rechner aufbewahren.

## Wichtige Hinweise

- Die Auswertung ist eine **Arbeitshilfe** und ersetzt keine rechtliche Prüfung. Alle Zeiten sind in UTC, wie vom Fahrtenschreiber aufgezeichnet. Die Fähr- und Zugausnahme wird nur ausgewertet, wenn die Überfahrt auf der Karte gekennzeichnet ist. Weitere Ausnahmen (Art. 12, Sonderregeln im Mehrfahrerbetrieb, nationale Ausnahmen) werden nicht automatisch berücksichtigt.
- Die Signaturprüfung (siehe unten) belegt, dass die Daten seit dem Auslesen unverändert sind und von einer Karte mit gültigem Zertifikat stammen. Sie ersetzt **keine zertifizierte Kontrollsoftware**; für eine rechtsverbindliche Echtheitsprüfung ist eine solche nötig.
- Die Archivdaten sind personenbezogene Daten im Sinne der DSGVO.

## Signaturprüfung

Jede signierte Datei eines Downloads trägt eine Signatur der Karte. Der öffentliche Schlüssel der Karte steckt im Kartenzertifikat, dieses ist vom Mitgliedstaat signiert, dessen Zertifikat von der europäischen Wurzelinstanz **ERCA**. **Archiv ▸ Signaturen prüfen** rechnet diese Kette nach und zeigt das Ergebnis in der Spalte „Signatur" des Archivreiters.

### Wurzelschlüssel hinterlegen

Der Wurzelschlüssel wird **nicht mitgeliefert** – er ist amtlich und soll aus amtlicher Quelle kommen.

**Woher Sie ihn bekommen:** Zuständig ist die Gemeinsame Forschungsstelle der EU-Kommission (JRC), die die ERCA betreibt: <https://dtc.jrc.ec.europa.eu/> – Bereich „ERCA ST" für die heutigen Karten (Generation 2), „ERCA DT" für alte Bestände (Generation 1). Auf den öffentlichen Listen stehen vor allem die Zertifikate der Mitgliedstaaten (MSCA); das Wurzelzertifikat selbst ist dort nicht immer unmittelbar verlinkt. Finden Sie es nicht, fragen Sie es unter <jrc-erca@ec.europa.eu> an. Zweiter Weg: die Behörde Ihres Mitgliedstaats, die Fahrerkarten ausgibt (in Deutschland das Kraftfahrt-Bundesamt). Dritter Weg: die Datei von jemandem übernehmen, der sie schon hat – zulässig, weil es ein öffentliches Dokument ist, aber dann unbedingt den Fingerabdruck prüfen (siehe unten).

Dieselbe Anleitung liegt als `BITTE-HIER-ABLEGEN.txt` im `erca`-Ordner, den das Programm beim Start anlegt – dort, wo die Frage auftaucht. Die Dateien gehören in den Ordner `erca` im Archivverzeichnis. Bei unveränderten Einstellungen ist das

```
~/.local/share/TachoArchiv/TachoArchiv/archiv/erca
```

(im Flatpak `~/.var/app/io.github.tachoarchiv.TachoArchiv/data/TachoArchiv/TachoArchiv/archiv/erca`). Das Programm legt den Ordner beim Start an und hinterlegt darin eine Datei `BITTE-HIER-ABLEGEN.txt` mit denselben Angaben; ist das Archivverzeichnis in den Einstellungen geändert, liegt `erca` entsprechend darunter. **Archiv ▸ Signaturen prüfen** nennt den tatsächlichen Pfad und öffnet den Ordner auf Wunsch gleich. Der Dateiname ist beliebig, das Programm erkennt am Inhalt, worum es sich handelt:

- **Generation 2** (heutige Karten): das ERCA-Wurzelzertifikat als Datei im Zertifikatsformat der Anlage 11 (beginnt mit `7F 21`). Mehrere Generationen der Wurzel können nebeneinander liegen.
- **Generation 1** (nur noch für alte Archivbestände): 144 Byte (8 Byte Kennung, 128 Byte Modulus, 8 Byte Exponent) oder 136 Byte ohne Kennung.

Bei **Generation 2** geht es auch ohne hinterlegte Wurzel schon ein gutes Stück: Dort steht der öffentliche Schlüssel im Klartext im Zertifikat, deshalb lassen sich die Dateisignaturen und die Verbindung Karte → Mitgliedstaat prüfen. Offen bleibt nur, ob der Mitgliedstaat selbst beglaubigt ist; das Programm nennt diesen Zustand „Daten bestätigt, Wurzel offen". Eine veränderte Datei fällt auch in diesem Zustand auf.

Bei **Generation 1** geht ohne Wurzel gar nichts: dort steckt der öffentliche Schlüssel innerhalb der Signatur und wird erst durch das Nachrechnen mit dem Ausstellerschlüssel sichtbar.

Hat ein Download ein **Verknüpfungszertifikat** (EF 0xC109) dabei, reicht die vorherige Wurzel: damit wird der Wechsel von einer ERCA-Generation zur nächsten überbrückt.

### Wenn Sie das Programm weitergeben

Das Wurzelzertifikat gehört zu den Daten des Benutzers, nicht zum Programm – das Paket enthält es nicht. Ein neuer Benutzer muss es also einmal hinterlegen. Dafür gibt es drei Wege:

1. **Jeder für sich:** Datei in den eigenen `erca`-Ordner legen (Pfad siehe oben).
2. **Einmal für den ganzen Rechner:** Datei nach `/usr/local/share/tachoarchiv/erca/` legen (oder `/usr/share/tachoarchiv/erca/`, wenn sie aus einem Paket kommt). Das Programm sieht dort nach, sobald im eigenen Archiv nichts liegt, und alle Benutzer des Rechners sind versorgt. Für eigene Pakete lässt sich das Zertifikat dort mitliefern.
3. **Beilegen:** Wer das Programm weitergibt, kann das Zertifikat danebenlegen – es ist ein öffentliches amtliches Dokument.

**Prüfen Sie ein Wurzelzertifikat, das Sie nicht selbst geholt haben.** Es ist der Vertrauensanker der ganzen Kette; wird es ausgetauscht, bestätigt das Programm anschließend auch gefälschte Karten. **Hilfe ▸ Zertifikate untersuchen** zeigt den SHA-256 jeder hinterlegten Datei – vergleichen Sie ihn mit der amtlichen Veröffentlichung.

### Was die Zustände bedeuten

| Anzeige | Bedeutung |
|---|---|
| bestätigt | Signatur passt zu den Daten, Kette bis zur hinterlegten Wurzel geschlossen |
| Daten bestätigt, Wurzel offen | Nur Generation 2: die Daten sind unverändert und das Kartenzertifikat stammt vom angegebenen Mitgliedstaat, aber es ist kein ERCA-Wurzelzertifikat hinterlegt |
| passt nicht | Die Datei wurde nach dem Auslesen verändert, oder das Zertifikat gehört nicht dazu |
| Wurzelschlüssel fehlt | Kein ERCA-Schlüssel hinterlegt oder er passt nicht zum Aussteller |
| nicht prüfbar | Format nicht gelesen – etwa Generation 2 |
| keine Signatur | Die Datei trägt keine |

Ein Fehlschlag heißt „nicht bestätigt", nicht „gefälscht". Prüfen Sie zuerst, ob die Datei beim Kopieren beschädigt wurde.

Läuft die Prüfung bei einer echten Karte nicht durch, hilft **Hilfe ▸ Zertifikate untersuchen**: dort stehen Aufbau, Kurve, Längen und welche Lesart der Zertifikatssignatur passt – ohne Fahrerdaten, zum Weitergeben geeignet.

### Grenzen

- Geprüft werden beide Generationen: Generation 1 mit RSA und SHA-1, Generation 2 mit ECDSA über die in Anlage 11 vorgesehenen Kurven (NIST P-256/P-384/P-521, Brainpool P256r1/P384r1/P512r1) und dem zur Schlüssellänge gehörenden Hash. Bei Generation 2 wird der Schlüssel aus dem **Signaturzertifikat** der Karte (EF 0xC101) verwendet; fehlt es im Download, steht „nicht prüfbar".
- Generation 2 ist an einer echten Fahrerkarte mit dem amtlichen ERCA-Wurzelzertifikat vollständig bestätigt (Oktober 2026): Zertifikatsaufbau, Dateisignaturen und die ganze Kette Karte → Mitgliedstaat → Wurzel gehen auf. Signiert wird der Zertifikatsrumpf einschließlich seiner Kennung `7F4E`. Generation 1 ist nur gegen selbst erzeugte Ketten geprüft – Karten dieser Generation sind nicht mehr im Umlauf, die Prüfung gibt es für alte Archivbestände.
- Schlägt die Prüfung bei einer Karte fehl, von der Sie wissen, dass sie in Ordnung ist, ist das ein Hinweis auf einen Fehler im Programm – bitte melden, am besten mit der Ausgabe von **Hilfe ▸ Zertifikate untersuchen**.
- Geprüft wird die Signatur, nicht die Sperrung eines Zertifikats.
