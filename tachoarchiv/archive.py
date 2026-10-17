"""Revisionssicheres Archiv: Originaldateien unverändert (schreibgeschützt) + SQLite-Index."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .ddd import DddFile
from .parser import CardData, merge_cards, parse_card
from .signature import RootStore, Status, summary, verify_card
from .vault import LockedError, Vault, VaultError
from .vu import VuError, VuInfo, is_vu_file, parse_vu

UTC = dt.timezone.utc
DB_PLAIN = "archiv.sqlite"
DB_ENC = "archiv.sqlite.enc"      # bei eingeschaltetem Schutz: verschlüsselter Abzug

SCHEMA = """
CREATE TABLE IF NOT EXISTS drivers (
    card_number TEXT PRIMARY KEY,
    surname TEXT, firstnames TEXT, birth_date TEXT, nation TEXT,
    expiry TEXT, generation INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_number TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    source TEXT NOT NULL,
    original_name TEXT,
    first_day TEXT, last_day TEXT, generation INTEGER
);
CREATE INDEX IF NOT EXISTS idx_dl_card ON downloads(card_number);
CREATE TABLE IF NOT EXISTS vehicles (
    vin TEXT PRIMARY KEY,
    nation TEXT, registration TEXT, generation INTEGER, version INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS vu_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    source TEXT NOT NULL,
    original_name TEXT,
    downloaded_at TEXT, period_begin TEXT, period_end TEXT,
    generation INTEGER, days INTEGER, blocks TEXT, company TEXT, card_number TEXT
);
CREATE INDEX IF NOT EXISTS idx_vu_vin ON vu_downloads(vin);
"""


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "unbekannt"


@dataclass
class VuDownload:
    id: int
    vin: str
    path: Path
    sha256: str
    imported_at: dt.datetime
    source: str
    original_name: str
    downloaded_at: str
    period_begin: str
    period_end: str
    generation: int
    days: int
    blocks: str
    company: str
    card_number: str


@dataclass
class Download:
    id: int
    card_number: str
    path: Path
    sha256: str
    imported_at: dt.datetime
    source: str
    original_name: str
    first_day: str
    last_day: str
    generation: int


class DuplicateError(Exception):
    pass


class Archive:
    def __init__(self, base: str | os.PathLike, vault: Vault | None = None):
        self.base = Path(base)
        (self.base / "ddd").mkdir(parents=True, exist_ok=True)
        self.vault = vault if vault is not None else Vault(self.base)
        self.db: sqlite3.Connection | None = None
        self._cache: dict[str, tuple[int, CardData]] = {}
        self.prepare_erca()
        if self.vault.ready:
            self.open_db()

    # ------------------------------------------------------------------ Index
    def open_db(self) -> None:
        """Öffnet den Index. Bei eingeschaltetem Schutz nur im Arbeitsspeicher."""
        if self.db is not None:
            return
        if not self.vault.enabled:
            self.db = sqlite3.connect(self.base / DB_PLAIN)
        else:
            if not self.vault.unlocked:
                raise LockedError()
            self.db = sqlite3.connect(":memory:")
            enc = self.base / DB_ENC
            if enc.exists():
                dump = self.vault.decrypt(enc.read_bytes()).decode("utf-8")
                self.db.executescript(dump)
        self.db.executescript(SCHEMA)

    def close_db(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
        self._cache.clear()

    def _flush(self) -> None:
        """Verschlüsselten Index wegschreiben – nach jeder Änderung, der Index ist klein."""
        if not self.vault.enabled or self.db is None:
            return
        dump = "\n".join(self.db.iterdump()).encode("utf-8")
        path = self.base / DB_ENC
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(self.vault.encrypt(dump))
        os.replace(tmp, path)
        os.chmod(path, 0o600)

    def _require(self) -> sqlite3.Connection:
        if self.db is None:
            raise LockedError()
        return self.db

    # ------------------------------------------------------------------ Dateien
    def _store(self, path: Path, raw: bytes) -> None:
        """Legt eine Datei unveränderbar ab – verschlüsselt, wenn der Schutz an ist."""
        data = self.vault.encrypt(raw)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o400 if self.vault.enabled else 0o444)

    def _load(self, path: Path) -> bytes:
        return self.vault.decrypt(path.read_bytes())

    def _free_path(self, folder: Path, name: str) -> Path:
        path = folder / name
        stem, _, suffix = name.rpartition(".")
        n = 1
        while path.exists():
            path = folder / f"{stem}_{n}.{suffix}"
            n += 1
        return path

    def _name(self, kind: str, stamp: dt.datetime, label: str, ident: str, sha: str) -> str:
        """Bei eingeschaltetem Schutz ohne Namen – sonst verrät schon das Verzeichnis alles."""
        if self.vault.enabled:
            return f"{kind}_{sha[:16]}.bin"
        return f"{kind}_{stamp:%Y%m%d_%H%M}_{_safe(label)[:20]}_{_safe(ident)}.DDD"

    # ------------------------------------------------------------------ Import
    def _folder(self, kind: str, ident: str) -> Path:
        """Unterordner je Karte/Fahrzeug; bei Schutz als Kennung ohne Aussagekraft."""
        leaf = hashlib.sha256(ident.encode()).hexdigest()[:16] if self.vault.enabled else _safe(ident)
        folder = self.base / "ddd" / kind / leaf if kind else self.base / "ddd" / leaf
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def add(self, raw: bytes, source: str, original_name: str = "") -> tuple[Download, CardData]:
        db = self._require()
        sha = hashlib.sha256(raw).hexdigest()
        row = db.execute("SELECT id FROM downloads WHERE sha256=?", (sha,)).fetchone()
        if row:
            raise DuplicateError(original_name or sha)
        card = parse_card(DddFile.parse(raw))
        info = card.info
        num = info.card_number or "unbekannt"
        now = dt.datetime.now(UTC)
        folder = self._folder("", num)
        path = self._free_path(folder, self._name("C", now, info.surname, num, sha))
        self._store(path, raw)

        first = card.days[0].date.date().isoformat() if card.days else ""
        last = card.days[-1].date.date().isoformat() if card.days else ""
        with db:
            db.execute(
                "INSERT INTO drivers VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(card_number) DO UPDATE SET "
                "surname=excluded.surname, firstnames=excluded.firstnames, birth_date=excluded.birth_date, "
                "nation=excluded.nation, expiry=excluded.expiry, generation=excluded.generation, "
                "updated_at=excluded.updated_at",
                (num, info.surname, info.firstnames,
                 info.birth_date.isoformat() if info.birth_date else "", info.issuing_nation,
                 info.expiry_date.isoformat() if info.expiry_date else "", info.generation,
                 now.isoformat()))
            cur = db.execute(
                "INSERT INTO downloads (card_number, path, sha256, imported_at, source, original_name, "
                "first_day, last_day, generation) VALUES (?,?,?,?,?,?,?,?,?)",
                (num, str(path.relative_to(self.base)), sha, now.isoformat(), source,
                 original_name, first, last, info.generation))
        self._cache.pop(num, None)
        self._flush()
        return self._download(db.execute("SELECT * FROM downloads WHERE id=?",
                                         (cur.lastrowid,)).fetchone()), card

    def add_any(self, raw: bytes, source: str, original_name: str = ""):
        """Nimmt Fahrerkarten- und Fahrzeugdateien entgegen und legt sie passend ab."""
        if is_vu_file(raw):
            return self.add_vu(raw, source, original_name)
        return self.add(raw, source, original_name)

    def add_vu(self, raw: bytes, source: str,
               original_name: str = "") -> tuple[VuDownload, VuInfo]:
        """Archiviert einen Fahrzeug-Download (Massenspeicher) unverändert."""
        db = self._require()
        sha = hashlib.sha256(raw).hexdigest()
        if db.execute("SELECT id FROM vu_downloads WHERE sha256=?", (sha,)).fetchone():
            raise DuplicateError(original_name or sha)
        if not is_vu_file(raw):
            raise VuError("no vu file")
        try:
            _, info = parse_vu(raw)
        except (ValueError, IndexError):
            # Kopfdaten unlesbar: die Datei wird trotzdem unverändert aufbewahrt,
            # nur ohne Kennzeichen und Zeitraum. Archivieren geht vor Auswerten.
            info = VuInfo()
        vin = info.vin or info.plate or "unbekannt"
        now = dt.datetime.now(UTC)
        folder = self._folder("fahrzeuge", vin)
        stamp = info.downloaded_at or now
        path = self._free_path(folder, self._name("M", stamp, info.registration, vin, sha))
        self._store(path, raw)

        def iso(d):
            return d.isoformat() if d else ""

        with db:
            db.execute(
                "INSERT INTO vehicles VALUES (?,?,?,?,?,?) ON CONFLICT(vin) DO UPDATE SET "
                "nation=excluded.nation, registration=excluded.registration, "
                "generation=excluded.generation, version=excluded.version, "
                "updated_at=excluded.updated_at",
                (vin, info.nation, info.registration, info.generation, info.version,
                 now.isoformat()))
            cur = db.execute(
                "INSERT INTO vu_downloads (vin, path, sha256, imported_at, source, original_name, "
                "downloaded_at, period_begin, period_end, generation, days, blocks, company, "
                "card_number) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (vin, str(path.relative_to(self.base)), sha, now.isoformat(), source,
                 original_name, iso(info.downloaded_at), iso(info.period_begin),
                 iso(info.period_end), info.generation, info.days,
                 ",".join(f"{t:02X}" for t in info.blocks), info.company, info.card_number))
        self._flush()
        return self._vu(db.execute("SELECT * FROM vu_downloads WHERE id=?",
                                   (cur.lastrowid,)).fetchone()), info

    # ------------------------------------------------------------------ Abfragen
    def _vu(self, r) -> VuDownload:
        return VuDownload(r[0], r[1], self.base / r[2], r[3], dt.datetime.fromisoformat(r[4]),
                          r[5], r[6] or "", r[7] or "", r[8] or "", r[9] or "", r[10] or 1,
                          r[11] or 0, r[12] or "", r[13] or "", r[14] or "")

    def vehicles(self) -> list[dict]:
        rows = self._require().execute(
            "SELECT v.vin, v.nation, v.registration, v.generation, COUNT(d.id), "
            "MAX(d.downloaded_at), MAX(d.imported_at) FROM vehicles v "
            "LEFT JOIN vu_downloads d ON d.vin=v.vin "
            "GROUP BY v.vin ORDER BY v.registration, v.vin").fetchall()
        return [{"vin": r[0], "nation": r[1], "registration": r[2], "generation": r[3],
                 "count": r[4], "last_download": r[5], "last_import": r[6]} for r in rows]

    def vu_downloads(self, vin: str | None = None) -> list[VuDownload]:
        if vin:
            rows = self._require().execute(
                "SELECT * FROM vu_downloads WHERE vin=? ORDER BY imported_at", (vin,)).fetchall()
        else:
            rows = self._require().execute("SELECT * FROM vu_downloads ORDER BY imported_at").fetchall()
        return [self._vu(r) for r in rows]

    def _download(self, r) -> Download:
        return Download(r[0], r[1], self.base / r[2], r[3], dt.datetime.fromisoformat(r[4]),
                        r[5], r[6] or "", r[7] or "", r[8] or "", r[9] or 1)

    def drivers(self) -> list[dict]:
        rows = self._require().execute(
            "SELECT d.card_number, d.surname, d.firstnames, d.expiry, MAX(l.imported_at) "
            "FROM drivers d LEFT JOIN downloads l ON l.card_number=d.card_number "
            "GROUP BY d.card_number ORDER BY d.surname, d.firstnames").fetchall()
        return [{"card_number": r[0], "surname": r[1], "firstnames": r[2], "expiry": r[3],
                 "last_import": r[4]} for r in rows]

    def downloads(self, card_number: str | None = None) -> list[Download]:
        if card_number:
            rows = self._require().execute("SELECT * FROM downloads WHERE card_number=? ORDER BY imported_at",
                                   (card_number,)).fetchall()
        else:
            rows = self._require().execute("SELECT * FROM downloads ORDER BY imported_at").fetchall()
        return [self._download(r) for r in rows]

    def load_driver(self, card_number: str) -> CardData:
        dls = self.downloads(card_number)
        cached = self._cache.get(card_number)
        if cached and cached[0] == len(dls):
            return cached[1]
        cards = []
        warnings = []
        for d in dls:
            try:
                cards.append(parse_card(DddFile.parse(self._load(d.path))))
            except (OSError, ValueError) as e:
                warnings.append(f"{d.path.name}: {e}")
        merged = merge_cards(cards)
        merged.warnings = warnings
        self._cache[card_number] = (len(dls), merged)
        return merged

    def verify(self) -> dict[str, bool]:
        """Prüfsummen aller archivierten Dateien; Schlüssel "c<id>" Karte, "v<id>" Fahrzeug."""
        result = {}
        for kind, items in (("c", self.downloads()), ("v", self.vu_downloads())):
            for d in items:
                try:
                    ok = hashlib.sha256(self._load(d.path)).hexdigest() == d.sha256
                except (OSError, VaultError):
                    ok = False
                result[f"{kind}{d.id}"] = ok
        return result

    # ------------------------------------------------------------------ Zugangsschutz
    def _all_files(self) -> list[tuple[str, int, Path, str, str, str, dt.datetime]]:
        """(Tabelle, id, Pfad, sha, Kennung, Name für den Dateinamen, Zeitstempel)."""
        out = []
        for d in self.downloads():
            out.append(("downloads", d.id, d.path, d.sha256, d.card_number, "", d.imported_at))
        for v in self.vu_downloads():
            stamp = dt.datetime.fromisoformat(v.downloaded_at) if v.downloaded_at else v.imported_at
            plate = next((r[0] for r in self._require().execute(
                "SELECT registration FROM vehicles WHERE vin=?", (v.vin,)).fetchall()), "")
            out.append(("vu_downloads", v.id, v.path, v.sha256, v.vin, plate or "", stamp))
        return out

    def _relocate(self, items, labels: dict[str, str], raws: dict | None = None) -> None:
        """Dateien neu ablegen – nach dem Umschalten passen Ordner und Namen nicht mehr.

        Beim Ausschalten des Schutzes ist der Schlüssel schon weg, dann kommen die
        Daten aus ``raws`` statt von der Platte.
        """
        db = self._require()
        for table, ident_id, old, sha, ident, plate, stamp in items:
            raw = raws[(table, ident_id)] if raws is not None else self._load(old)
            kind = "M" if table == "vu_downloads" else "C"
            folder = self._folder("fahrzeuge" if kind == "M" else "", ident)
            label = plate if kind == "M" else labels.get(ident, "")
            new = self._free_path(folder, self._name(kind, stamp, label, ident, sha))
            self._store(new, raw)
            with db:
                db.execute(f"UPDATE {table} SET path=? WHERE id=?",
                           (str(new.relative_to(self.base)), ident_id))
            if old != new:
                try:
                    os.chmod(old, 0o600)
                    old.unlink()
                except OSError:
                    pass
        for folder in sorted((self.base / "ddd").rglob("*"), reverse=True):
            if folder.is_dir():
                try:
                    folder.rmdir()                 # nur leere Ordner verschwinden
                except OSError:
                    pass

    def _surnames(self) -> dict[str, str]:
        return {r[0]: r[1] or "" for r in
                self._require().execute("SELECT card_number, surname FROM drivers").fetchall()}

    def _db_to_memory(self) -> None:
        dump = "\n".join(self._require().iterdump())
        self.db.close()
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(dump)

    def protect(self, password: str) -> str:
        """Schutz einschalten: alles verschlüsseln. Gibt den Wiederherstellungsschlüssel zurück."""
        if self.vault.enabled:
            raise VaultError("already protected")
        items = self._all_files()
        labels = self._surnames()
        recovery = self.vault.enable(password)
        self._db_to_memory()
        self._relocate(items, labels)
        self._flush()
        try:
            (self.base / DB_PLAIN).unlink()
        except OSError:
            pass
        self._cache.clear()
        return recovery

    def unprotect(self) -> None:
        """Schutz ausschalten: alles wieder im Klartext ablegen."""
        if not self.vault.enabled:
            return
        if not self.vault.unlocked:
            raise LockedError()
        items = self._all_files()
        labels = self._surnames()
        raws = {(t, i): self._load(p) for t, i, p, *_ in items}
        self.vault.disable()                       # ab hier schreibt _store im Klartext
        self._relocate(items, labels, raws)
        dump = "\n".join(self._require().iterdump())
        self.db.close()
        self.db = sqlite3.connect(self.base / DB_PLAIN)
        self.db.executescript(dump)
        try:
            (self.base / DB_ENC).unlink()
        except OSError:
            pass
        self._cache.clear()

    def lock(self) -> None:
        self.close_db()
        self.vault.lock()

    def unlock(self, secret: str) -> None:
        self.vault.unlock(secret)
        self.open_db()

    # ------------------------------------------------------------------ Signaturen
    ERCA_README = """Wurzelzertifikat der ERCA - wie Sie es bekommen und wo es hingehoert
=======================================================================

In diesen Ordner gehoert das amtliche Wurzelzertifikat der europaeischen
Zertifizierungsstelle fuer den Fahrtenschreiber (European Root Certification
Authority, ERCA). Ohne dieses Zertifikat kann TachoArchiv die Signatur einer
Fahrerkarte nicht bis zur Wurzel zurueckverfolgen.


1. Was Sie brauchen
-------------------

Fuer die heutigen Karten (Generation 2, Smart Tachograph) das Wurzelzertifikat
ERCA-ST. Es ist eine Binaerdatei im Zertifikatsformat der Anlage 11; die ersten
beiden Bytes sind 7F 21.

Fuer alte Archivbestaende (Generation 1) den oeffentlichen ERCA-DT-Schluessel:
144 Byte (8 Byte Kennung, 128 Byte Modulus, 8 Byte Exponent) oder 136 Byte ohne
Kennung. Karten dieser Generation sind nicht mehr im Umlauf.


2. Woher Sie es bekommen
------------------------

Zustaendig ist die Gemeinsame Forschungsstelle der Europaeischen Kommission
(Joint Research Centre, JRC), die die ERCA betreibt:

    https://dtc.jrc.ec.europa.eu/

    Generation 2 (heutige Karten):  Bereich "ERCA ST"
    Generation 1 (alte Bestaende):  Bereich "ERCA DT"

Auf den oeffentlichen Listen dieser Seiten stehen vor allem die Zertifikate der
einzelnen Mitgliedstaaten (MSCA). Das Wurzelzertifikat selbst ist dort nicht
immer unmittelbar verlinkt. Finden Sie es nicht, fragen Sie es bei der ERCA an:

    jrc-erca@ec.europa.eu

Zweiter Weg: Die Behoerde Ihres Mitgliedstaats, die Fahrerkarten ausgibt, haelt
das Zertifikat ebenfalls vor. In Deutschland ist das das Kraftfahrt-Bundesamt.

Dritter Weg: Sie uebernehmen die Datei von jemandem, der sie schon hat - einem
Kollegen, einem Betrieb, einem anderen Programm. Das ist zulaessig, denn das
Zertifikat ist ein oeffentliches Dokument. Pruefen Sie es dann aber nach,
siehe Punkt 4.


3. Wohin die Datei gehoert
--------------------------

Entweder in diesen Ordner - dann gilt sie fuer Ihr Archiv -, oder systemweit
fuer alle Benutzer des Rechners nach

    /usr/local/share/tachoarchiv/erca/

Der Dateiname ist beliebig; TachoArchiv erkennt am Inhalt, worum es sich
handelt. Mehrere Wurzelgenerationen duerfen nebeneinander liegen. Danach
"Archiv - Signaturen pruefen" aufrufen.


4. Nachpruefen, wenn Sie die Datei nicht selbst geholt haben
------------------------------------------------------------

Das Wurzelzertifikat ist der Vertrauensanker der gesamten Pruefung. Wer es
austauscht, bekommt danach auch fuer gefaelschte Karten ein gruenes
"bestaetigt" - die Pruefung waere dann wertlos.

"Hilfe - Zertifikate untersuchen" zeigt den SHA-256-Fingerabdruck jeder
hinterlegten Datei. Vergleichen Sie ihn mit dem Wert aus amtlicher Quelle oder
mit dem Fingerabdruck einer Datei, von der Sie wissen, dass sie echt ist.
Stimmt er ueberein, ist die Datei unverfaelscht - gleich ueber wie viele Haende
sie gelaufen ist.

Geben Sie den Fingerabdruck mit weiter, wenn Sie die Datei an jemanden
weiterreichen.


5. Was die Pruefung aussagt
---------------------------

Sie belegt, dass die archivierten Daten seit dem Auslesen unveraendert sind und
von einer Karte stammen, deren Zertifikat sich auf die hinterlegte Wurzel
zurueckfuehren laesst. Sie ersetzt keine zertifizierte Kontrollsoftware, und
sie sagt nichts darueber, ob ein Zertifikat zwischenzeitlich gesperrt wurde.

Diese Dateien sind oeffentlich. Sie werden nicht verschluesselt, auch wenn der
Zugangsschutz des Archivs eingeschaltet ist.
"""

    @property
    def erca_dir(self) -> Path:
        """Hier liegen die amtlichen Wurzelschlüssel – öffentlich, also unverschlüsselt."""
        return self.base / "erca"

    def prepare_erca(self) -> Path:
        """Legt den Ordner an und erklärt darin, was hineingehört.

        Ein leerer Ordner im Dateimanager beantwortet die Frage „wohin damit"
        besser als jede Zeile in der README.
        """
        folder = self.erca_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
            note = folder / "BITTE-HIER-ABLEGEN.txt"
            if not note.exists():
                note.write_text(self.ERCA_README, encoding="utf-8")
        except OSError:
            pass
        return folder

    def roots(self) -> RootStore:
        """Archiv des Benutzers zuerst, danach die systemweiten Ordner."""
        return RootStore(self.erca_dir)

    def check_signatures(self, card_number: str | None = None) -> dict[str, Status]:
        """Prüft die Kartensignaturen je Download. Schlüssel wie bei verify(): "c<id>"."""
        roots = self.roots()
        out: dict[str, Status] = {}
        for d in self.downloads(card_number):
            try:
                states = verify_card(DddFile.parse(self._load(d.path)), roots)
            except (OSError, ValueError, VaultError) as e:
                out[f"c{d.id}"] = Status("unsupported", str(e))
                continue
            out[f"c{d.id}"] = summary(states)
        return out

    def close(self) -> None:
        self.close_db()
