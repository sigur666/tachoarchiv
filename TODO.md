# Vorgemerkt

Nichts davon ist dringend; die Liste hält fest, was beim nächsten Update drankommt.

## Für das nächste Update

- **Nordische Sprachen ergänzen:** Norwegisch (nb), Schwedisch (sv), Dänisch
  (da), Finnisch (fi). Ablauf wie bei den übrigen: Datei in
  `tachoarchiv/locale/` anlegen, Eintrag in `i18n.LANGUAGES`, Platzhalter gegen
  `de.json` prüfen. Damit wären es 34 Sprachen.

## Längerfristig

- **Geschwindigkeitsauswertung gegen eine echte Fahrzeugdatei prüfen.** Bislang
  nur gegen selbst erzeugte Dateien getestet; bei Generation 2 können die
  Satzlängen abweichen.
- **Demodaten sind eine Karte der 1. Generation.** Die gibt es im Umlauf nicht
  mehr; für die Vorführung wäre eine Gen-2-Karte näher an der Wirklichkeit.
- **Flatpak-Bau** ist nie ausgeführt worden.
- **Paketnamen für Fedora, Arch, openSUSE und Alpine** in `install.sh` sind
  nicht auf den echten Systemen getestet.
- **16-px-Fassung des Programmsymbols**: das Motiv bleibt, aber ohne die feinen
  Zeilen, sonst ist es in der Fensterliste nicht mehr zu erkennen.

## Rückmeldungen

- Signaturprüfung Generation 2 an einer echten Fahrerkarte bestätigt: TLV-Aufbau,
  Dateisignaturen und die Verbindung Karte → Mitgliedstaat gehen auf
  (10.10.2026). Gemessen: BrainpoolP256r1, Zertifikate 205 Byte, Signatur über
  den Rumpf mit Kennung 7F4E, Berechtigung unter 5F4C vor dem Schlüssel,
  EF 0xC109 vorhanden, aber leer. 19 Dateisignaturen, alle bestätigt.
- Mit dem amtlichen ERCA-Wurzelzertifikat schließt die Kette vollständig:
  Zustand „bestätigt" an einer echten Karte (10.10.2026). Damit ist die
  Signaturprüfung für Generation 2 an echter Hardware abgenommen.
- Polnisch von einem Muttersprachler gegengelesen: richtig, etwas formell – für
  den Zusammenhang passend (07.10.2026).
