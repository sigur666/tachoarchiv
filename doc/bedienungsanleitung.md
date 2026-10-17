# TachoArchiv – Bedienungsanleitung

Stand: Version 1.10.0, Oktober 2026

---

## 1. Wozu das Programm da ist

TachoArchiv liest Fahrerkarten des digitalen Fahrtenschreibers aus, bewahrt die
Dateien revisionssicher auf und wertet Lenk- und Ruhezeiten aus. Es läuft unter
Linux und braucht keinen Internetzugang – die Fahrerdaten verlassen den Rechner
nicht.

Was es **nicht** ist: eine zertifizierte Kontrollsoftware. Die Auswertung ist
eine Arbeitshilfe und ersetzt keine rechtliche Prüfung. Für eine verbindliche
Bewertung ist die zuständige Behörde oder eine zertifizierte Anwendung
zuständig.

Alle Zeiten sind **UTC**, so wie der Fahrtenschreiber sie aufzeichnet. Im Sommer
liegt die deutsche Uhrzeit zwei Stunden davor, im Winter eine.

---

## 2. Installation

### Debian, Ubuntu und Verwandte

```sh
sudo apt install ./tachoarchiv_1.10.0_all.deb
```

Fehlende Abhängigkeiten holt `apt` dabei mit. Danach steht TachoArchiv im
Anwendungsmenü.

### Andere Distributionen

Das Quellarchiv entpacken und das beiliegende Skript aufrufen:

```sh
tar xzf tachoarchiv-1.10.0.tar.gz
cd tachoarchiv
./install.sh --user        # nur für den eigenen Benutzer
./install.sh               # systemweit, fragt nach dem Kennwort
```

Das Skript erkennt apt, dnf, pacman, zypper und apk, installiert PC/SC, die
Schriften und Qt nach und legt, falls PySide6 nicht als Paket vorliegt, eine
eigene Python-Umgebung an. `./uninstall.sh` entfernt alles wieder; das Archiv
bleibt dabei erhalten (mit `--purge` wird auch es gelöscht).

### Kartenleser vorbereiten

Der Leser wird über den PC/SC-Dienst angesprochen. Läuft er nicht, meldet das
Programm das in der Statuszeile:

```sh
sudo apt install pcscd          # Debian/Ubuntu
sudo systemctl enable --now pcscd.socket
```

Unterstützt wird jeder PC/SC-fähige Leser; geprüft wurde unter anderem mit einem
Alcor Micro AU9540.

---

## 3. Das Fenster im Überblick

**Links oben: der Kalender.** Tage mit Daten stehen fett. Der blaue Balken am
Fuß eines Tages zeigt die Lenkzeit, rot hinterlegt sind Tage mit einem Verstoß,
gelb die mit einer Warnung – jeweils zusätzlich mit einem Punkt, damit die Farbe
nicht allein die Aussage trägt. Ein Klick auf einen Tag öffnet ihn im Reiter
**Tag**.

**Links unten: die Kartenübersicht.** Name, Kartennummer, Gültigkeit, letzter
Download, Datenzeitraum, Abdeckung des Kontrollzeitraums und die Zählung der
Befunde.

**Oben rechts: Zeitraum.** Alle Daten, Kontrollzeitraum (einstellbar, Standard
56 Tage), 28 Tage oder 12 Monate. Die Wahl wirkt auf alle Reiter und auf die
Berichte.

**Rechts: die Reiter.** Tag, Tage, Verstöße, Warnungen, Restzeit, Schichten,
Wochen, Fahrzeug, Ereignisse, Archiv.

---

## 4. Eine Fahrerkarte auslesen

1. Karte in den Leser stecken.
2. In der Werkzeugleiste den Leser auswählen – fehlt er, auf **Leser suchen**
   klicken.
3. **Fahrerkarte auslesen** (oder Strg+R).

Das Auslesen dauert je nach Karte eine halbe bis zwei Minuten; der Fortschritt
steht in der Statuszeile. Die Datei landet unverändert und schreibgeschützt im
Archiv, mit SHA-256-Prüfsumme und Zeitstempel. Wurde dieselbe Karte schon
einmal gelesen, werden die Zeiträume automatisch zusammengeführt – Sie verlieren
also nichts, wenn Sie öfter auslesen als nötig.

Meldet das Programm Hinweise (etwa zu einer Datei, die die Karte nicht
herausgibt), ist das meist harmlos; echte Fehler erscheinen als Dialog.

### Vorhandene Dateien importieren

**DDD-Datei importieren** (Strg+O) nimmt Dateien aus anderen Programmen an:
`.DDD`, `.C1B`, `.TGD` von Karten und `.DDD`, `.V1B`, `.V2B` von
Fahrzeug-Downloads. Mehrfachauswahl ist möglich. Bereits vorhandene Dateien
werden erkannt und nicht doppelt abgelegt.

---

## 5. Die Reiter im Einzelnen

### Tag

Der im Kalender gewählte Tag. Oben das Datum und, falls vorhanden, eine
Plakette mit der Zahl der Befunde. Darunter der Tagesverlauf als
Stufendiagramm wie auf dem Ausdruck des Fahrtenschreibers: Lenken, Arbeit,
Bereitschaft, Ruhe, Zeiten ohne Karte; eine Fähr- oder Zugüberfahrt erscheint
als violetter Balken darüber.

Die vier Kacheln zeigen Lenkzeit, Arbeitszeit, längste Ruhezeit und
Kilometerstand jeweils gegen ihre Grenze; überschrittene Werte stehen rot.
Darunter die Befunde dieses Tages und die Schichten, die ihn berühren.

### Tage

Alle Tage des gewählten Zeitraums mit dem Stufendiagramm und den Summen. Tage
mit Befunden sind farbig hinterlegt und mit ⚠ gekennzeichnet. Ein Klick auf eine
Zeile springt im Kalender auf diesen Tag.

### Verstöße

Nur die Verstöße, mit Zeitpunkt, Rechtsgrundlage und Beschreibung.

### Warnungen

Warnungen und Hinweise – also Dinge, die keine Zuwiderhandlung sind, aber
Beachtung verdienen: überfälliger Download, ablaufende Karte, unvollständiger
Nachweiszeitraum, Überschreitungen nach dem Arbeitszeitgesetz, Fähr- und
Zugüberfahrten, Datenlücken.

### Restzeit

Die Prognose: Wie viel darf jetzt noch gefahren werden? Sechs Kacheln zeigen die
verbleibende Tageslenkzeit, den Rest der Woche und der Doppelwoche, die noch
freien Verlängerungen auf zehn Stunden, die noch freien reduzierten Tagesruhen
und die Zeit bis zur fälligen Wochenruhe. Darunter steht, wie sich das
zusammensetzt, mit Rechtsgrundlage zu jedem Wert.

Gerechnet wird aus den vorliegenden Daten. Fahrten ohne Karte oder nach dem
letzten Download sind nicht enthalten – die Prognose ist eine Hilfe, keine
Zusage.

### Schichten

Jede Schicht mit Beginn, Ende, Dauer, Lenkzeit, Arbeit, Bereitschaft,
anschließender Ruhezeit und deren Art. Schichten mit Verstoß sind rot
hinterlegt, Schichten, auf die eine Wochenruhe folgt, grau – so sind die Wochen
auf einen Blick abgegrenzt. Oben vier Kennzahlen über den gewählten Zeitraum.

### Wochen

Summen je Kalenderwoche. Eine Wochenlenkzeit über 56 Stunden steht rot.

### Fahrzeug

Alles, was zum Fahrzeug gehört, in drei Unterreitern:

* **Fahrzeug und Downloads** – Fahrgestellnummer, Kennzeichen, Gerät,
  Unternehmen, letzter Download und die archivierten Dateien. Liegt der letzte
  Download länger als 90 Tage zurück, wird das hervorgehoben.
* **Geschwindigkeit** – der Tagesverlauf aus dem Massenspeicher, ein Wert je
  Sekunde. Oben lassen sich Tag und Grenzwert wählen. Die gestrichelte Linie ist
  der eingestellte Grenzwert, rote Bänder markieren Überschreitungen. Unten
  links jede Überschreitung mit Beginn, Dauer, Höchstwert und Mittel, unten
  rechts die Stunden des Tages. **Werte als CSV** gibt die Sekundenwerte aus.
* **Fahrzeuge der Karte** – die Fahrzeuge, die auf der Fahrerkarte vermerkt
  sind. Etwas anderes als die Fahrzeuge im Archiv.

### Ereignisse

Drei Felder übereinander, in der Höhe ziehbar: Fehler und Störungen,
Kontrollen, sonstige Ereignisse. Die Zahl in der Überschrift sagt, ob ein Feld
etwas enthält.

### Archiv

Die Fahrer- und Fahrzeugliste und die archivierten Dateien mit
Aufbewahrungsfrist, Prüfsumme und Signaturzustand. Dass die Namen hier liegen
und nicht dauerhaft am Fensterrand, ist Absicht: es sind personenbezogene Daten.

---

## 6. Berichte

**Bericht als PDF** (Strg+P) öffnet einen Dialog mit drei Entscheidungen:

* **Inhalt** – vollständige Auswertung oder nur die Verstöße. Bei „nur Verstöße"
  lässt sich zusätzlich ankreuzen, dass Warnungen und Hinweise mit aufgenommen
  werden.
* **Zeitraum** – vorbelegt mit dem Zeitraum des Hauptfensters.
* **Sprache des Berichts** – unabhängig von der Oberfläche. So lässt sich ein
  Bericht für jemanden ausdrucken, der die Programmsprache nicht liest; die
  Rechtsgrundlagen erscheinen dann in der amtlichen Zitierweise dieser Sprache.

Der Dateiname trägt den Sprachcode, damit sich mehrere Ausfertigungen
auseinanderhalten lassen.

**Auswertung als CSV** gibt die Befunde als Tabelle aus, zur Weiterverarbeitung
in einer Tabellenkalkulation.

---

## 7. Das Archiv

### Aufbewahrung

Die Originaldateien werden nie verändert und schreibgeschützt abgelegt. Zu jeder
Datei gehören eine SHA-256-Prüfsumme und der Zeitpunkt der Aufnahme. Die
Aufbewahrungsfrist – Standard zwei Jahre – ist in den Einstellungen änderbar und
wird je Datei angezeigt.

### Integrität prüfen

**Archiv ▸ Integrität prüfen** rechnet die Prüfsummen aller Dateien nach. Damit
fällt auf, wenn eine Datei nachträglich verändert oder beschädigt wurde.

### Signaturen prüfen

**Archiv ▸ Signaturen prüfen** rechnet die kryptografische Kette nach:
Dateisignatur ← Zertifikat der Karte ← Zertifikat des Mitgliedstaats ←
Wurzelzertifikat der ERCA. Die Spalte „Signatur" zeigt das Ergebnis:

| Anzeige | Bedeutung |
|---|---|
| bestätigt | Die Kette ist bis zur hinterlegten Wurzel geschlossen |
| Daten bestätigt, Wurzel offen | Die Daten sind unverändert und die Karte stammt vom angegebenen Mitgliedstaat, aber es ist kein Wurzelzertifikat hinterlegt |
| passt nicht | Die Datei wurde verändert oder das Zertifikat gehört nicht dazu |
| Wurzelschlüssel fehlt | Kein Wurzelzertifikat hinterlegt (Generation 1) |
| nicht prüfbar | Format nicht gelesen |
| keine Signatur | Die Datei trägt keine |

Für den vollen Nachweis wird das Wurzelzertifikat der ERCA gebraucht. Es wird
nicht mitgeliefert; wie Sie es bekommen, steht in der Datei
`BITTE-HIER-ABLEGEN.txt`, die im Ordner `erca` Ihres Archivs liegt. Kurz: beim
Joint Research Centre der EU-Kommission (<https://dtc.jrc.ec.europa.eu/>,
Bereich „ERCA ST"), bei der Behörde Ihres Mitgliedstaats, oder von jemandem, der
es schon hat – dann aber den Fingerabdruck vergleichen.

**Hilfe ▸ Zertifikate untersuchen** zeigt diesen Fingerabdruck und den Aufbau der
Zertifikate. Die Ausgabe enthält keine Fahrerdaten und lässt sich bedenkenlos
weitergeben, wenn etwas nicht funktioniert.

### Zugangsschutz

Voreingestellt ist **kein Passwort**; die Dateien liegen dann unverschlüsselt im
Archivordner. Unter **Archiv ▸ Zugang** lässt sich das ändern: Ein zufälliger
Schlüssel verschlüsselt alle Archivdateien und den Index mit AES-256-GCM,
Dateinamen werden durch Kennungen ohne Aussagekraft ersetzt. Das Archiv sperrt
sich nach einstellbarer Zeit ohne Bedienung selbst und kann beim Programmstart
gesperrt bleiben.

Das ist für ein gemeinsam genutztes Benutzerkonto gedacht, auf dem Dateirechte
niemanden trennen. Zwei Dinge leistet es nicht: Solange das Archiv entsperrt
ist, kommt jeder an die Daten, der an den laufenden Rechner kommt. Und gegen
Zugriff mit Administratorrechten hilft nur die Verschlüsselung des
Datenträgers.

> **Ohne Passwort und ohne Wiederherstellungsschlüssel sind die Daten endgültig
> verloren.** Es gibt keine Hintertür. Die Aufbewahrungspflicht gilt trotzdem –
> drucken Sie den Wiederherstellungsschlüssel aus und bewahren Sie ihn getrennt
> vom Rechner auf.

---

## 8. Einstellungen

**Archiv ▸ Einstellungen** regelt:

* **Zeiten ohne Karte als Ruhezeit werten** – wirkt auf die Auswertung von
  Lücken.
* **Arbeitszeitgesetz prüfen** – die deutschen Regeln zu Pausen und
  Arbeitszeit zusätzlich zur EU-Verordnung.
* **Fähr- und Zugregel anwenden** – die Ausnahme nach Artikel 9.
* **Nachweiszeitraum prüfen** und dessen Länge – Standard 56 Tage, also der
  laufende Tag und die 56 vorausgehenden.
* **Aufbewahrungsfrist** in Jahren.
* **Archivordner**.

Die Sprache wird rechts in der Werkzeugleiste gewählt und sofort übernommen; die
Liste zeigt den ISO-Code und den Namen in der Sprache selbst. Verfügbar sind 30
Sprachen, auch von rechts nach links geschriebene.

---

## 9. Was geprüft wird

Auswertung nach VO (EG) 561/2006 in der Fassung der VO (EU) 2020/1054,
VO (EU) 165/2014 und VO (EU) 581/2010, wahlweise ergänzt um das
Arbeitszeitgesetz. Geprüft werden unter anderem:

* Fahrtunterbrechung: 4,5 Stunden Lenkzeit, 45 Minuten Pause, Aufteilung
  15 + 30 Minuten
* tägliche Lenkzeit 9 Stunden, zweimal je Woche 10 Stunden
* tägliche Ruhezeit 11 Stunden, reduziert 9 Stunden, höchstens dreimal
* wöchentliche Ruhezeit spätestens nach sechs 24-Stunden-Zeiträumen, samt
  Ausgleich einer reduzierten Wochenruhe bis zum Ende der dritten Folgewoche
* wöchentliche Lenkzeit 56 Stunden, Doppelwoche 90 Stunden
* Fähre und Eisenbahn nach Artikel 9: höchstens zwei Unterbrechungen von
  zusammen höchstens einer Stunde, nur für die regelmäßige tägliche und die
  wöchentliche Ruhezeit, bei der Wochenruhe erst ab acht Stunden Überfahrt
* Download-Intervall der Karte (28 Tage) und des Fahrzeugs (90 Tage)
* Ablauf der Karte, Abdeckung des Nachweiszeitraums, Aufzeichnungslücken

Nicht berücksichtigt werden Ausnahmen nach Artikel 12, Sonderregeln im
Mehrfahrerbetrieb und nationale Ausnahmen. Ob dem Fahrer eine Schlafkabine zur
Verfügung stand, ist auf der Karte nicht gespeichert und kann nicht geprüft
werden.

---

## 10. Wenn etwas nicht funktioniert

**„Der PC/SC-Dienst ist nicht erreichbar."** `pcscd` installieren und starten,
siehe Abschnitt 2.

**Kein Kartenleser in der Liste.** Leser abziehen und neu anstecken, dann **Leser
suchen**. Hilft das nicht, prüfen, ob der Leser überhaupt erkannt wird:
`pcsc_scan` aus dem Paket `pcsc-tools`.

**Das Auslesen bricht ab oder meldet einen Statuscode.** **Hilfe ▸
Kartendiagnose** sendet nur lesende Befehle und zeigt, welche Befehlsform die
Karte annimmt. Die Ausgabe enthält keine Fahrerdaten und lässt sich kopieren und
weitergeben.

**Die Signaturprüfung schlägt fehl, obwohl die Karte in Ordnung ist.**
**Hilfe ▸ Zertifikate untersuchen** aufrufen und die Ausgabe weitergeben – das
ist ein Hinweis auf einen Fehler im Programm, nicht auf eine Fälschung.

**Das Archiv ist gesperrt und das Passwort ist weg.** Der
Wiederherstellungsschlüssel öffnet es ebenfalls. Ist auch der verloren, sind die
Daten nicht mehr zugänglich.

---

## 11. Wo die Daten liegen

Standardmäßig unter

```
~/.local/share/TachoArchiv/TachoArchiv/archiv/
```

(als Flatpak unterhalb von `~/.var/app/io.github.tachoarchiv.TachoArchiv/data/`).
Dort liegen der Index `archiv.sqlite`, die Originaldateien im Ordner `ddd` und
die Wurzelzertifikate im Ordner `erca`. Der Pfad ist in den Einstellungen
änderbar; **Archiv ▸ Archivordner öffnen** führt direkt hin.

Die Archivdaten sind personenbezogene Daten im Sinne der DSGVO. Wer sie
aufbewahrt, ist dafür verantwortlich – Aufbewahrungsfrist, Zugang und Löschung
inbegriffen.
