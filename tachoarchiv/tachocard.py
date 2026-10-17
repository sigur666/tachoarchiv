"""Auslesen einer Fahrerkarte (Gen1 und Gen2) mit Kartensignaturen.

Ablauf je signierter Datei (Anhang IC, Anlage 7, Kap. 3):
SELECT EF -> PERFORM HASH OF FILE -> READ BINARY -> PSO: COMPUTE DIGITAL SIGNATURE
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import i18n
from .ddd import G1_FILES, G2_FILES, MF_FILES, DddFile
from .pcsc import Card

AID_G1 = bytes.fromhex("FF544143484F")   # "TACHO"
AID_G2 = bytes.fromhex("FF534D524454")   # "SMRDT"

SW_OK = 0x9000
SW_SECURITY = 0x6982      # Sicherheitsbedingung nicht erfüllt


@dataclass
class Note:
    """Rueckmeldung zum Download: "warning" = Datei fehlt, "info" = ohne Folgen."""
    text: str
    severity: str = "warning"


class CardError(Exception):
    def __init__(self, what: str, sw: int):
        self.sw = sw
        super().__init__(f"{what}: SW={sw:04X}")


def _cmd(card: Card, apdu: bytes, what: str) -> bytes:
    data, sw = card.transmit(apdu)
    if sw != SW_OK:
        raise CardError(what, sw)
    return data


# Nicht jede Karte akzeptiert die Form aus Anhang IC, Anlage 2 (P2 = 0C, ohne
# Rückgabedaten). Verbreitet ist auch P2 = 00 (FCI) oder P2 = 04 (FCP); manche
# Karten lehnen eine abweichende Form mit 6A86 „falsche Parameter P1/P2“ ab.
# Darum wird der Reihe nach probiert und die erste erfolgreiche Form gemerkt.
SELECT_P2 = (0x0C, 0x00, 0x04)


def _select(card: Card, p1: int, p2: int, data: bytes) -> int:
    apdu = bytes([0x00, 0xA4, p1, p2]) + (bytes([len(data)]) + data if data else b"")
    return card.transmit(apdu)[1]


def _select_any(card: Card, p1: int, data: bytes, what: str, required: bool = True) -> int:
    first = None
    for p2 in SELECT_P2:
        sw = _select(card, p1, p2, data)
        if sw == SW_OK:
            return sw
        first = first if first is not None else sw
        if sw not in (0x6A86, 0x6B00, 0x6700, 0x6E00, 0x6D00):
            break                      # echter Fehler (z. B. Datei fehlt) – nicht weiter raten
    if required:
        raise CardError(what, first if first is not None else 0x6F00)
    return first if first is not None else 0x6F00


def select_mf(card: Card) -> int:
    """Wählt das Stammverzeichnis; liefert SW (Fehler ist nicht zwingend fatal).

    Manche Karten – etwa Karten der 2. Generation – lassen das Stammverzeichnis
    überhaupt nicht auswählen und antworten in jeder Form mit 6A86. Der Download
    läuft trotzdem, weil die Anwendungen über ihren Namen ausgewählt werden.
    """
    sw = _select_any(card, 0x00, bytes.fromhex("3F00"), "SELECT MF", required=False)
    if sw == SW_OK:
        return sw
    for p1 in (0x00, 0x04):           # ohne Dateikennung bzw. „Auswahl über leeren Namen“
        for p2 in SELECT_P2:
            if _select(card, p1, p2, b"") == SW_OK:
                return SW_OK
    return sw


def select_aid(card: Card, aid: bytes) -> bool:
    return _select_any(card, 0x04, aid, "SELECT AID", required=False) == SW_OK


def select_ef(card: Card, fid: int) -> None:
    _select_any(card, 0x02, bytes([fid >> 8, fid & 0xFF]), f"SELECT {fid:04X}")


HASH_APDU = bytes.fromhex("802A9000")

# Länge der Signatur: Gen1 ist RSA mit 128 Byte. Gen2 rechnet mit elliptischen
# Kurven, die Länge hängt von der Kurve ab (64, 96 oder 132 Byte). Le=00 steht für
# „so viel wie kommt“ – Karten mit strenger Längenprüfung lehnen das mit 6700 ab,
# darum werden die möglichen Längen der Reihe nach probiert.
SIG_LE = {1: (0x80, 0x00, 0x40, 0x60, 0x84), 2: (0x00, 0x40, 0x60, 0x84, 0x80)}


def read_signature(card: Card, fid: int, gen: int) -> bytes:
    what = f"SIGNATURE {fid:04X}"
    first = None
    for i, le in enumerate(SIG_LE[gen]):
        if i:
            # Der Hash gehört zum Sicherheitskontext des Befehls und wird vor jedem
            # weiteren Versuch neu gebildet.
            _cmd(card, HASH_APDU, f"PERFORM HASH {fid:04X}")
        data, sw = card.transmit(bytes([0x00, 0x2A, 0x9E, 0x9A, le]))
        if sw == SW_OK and data:
            return data
        first = first if first is not None else (sw if sw != SW_OK else 0x6700)
        if sw not in (0x6700, 0x6A86, 0x6B00) and sw != SW_OK:
            break
    raise CardError(what, first if first is not None else 0x6F00)


def read_all(card: Card, chunk: int = 0xC8, what: str = "") -> bytes:
    """Liest eine Datei vollständig.

    Nachgiebige Karten liefern einfach weniger Bytes als angefordert oder melden
    mit 6Cxx die richtige Länge. Strenge Karten antworten stattdessen mit 6700
    („falsche Länge“), sobald mehr angefordert wird, als die Datei noch hergibt –
    dann wird die Blockgröße halbiert, bis der Rest passt.
    """
    out = bytearray()
    off = 0
    size = chunk
    while off <= 0x7FFF:
        data, sw = card.transmit(bytes([0x00, 0xB0, off >> 8, off & 0xFF, size]))
        if sw == SW_OK:
            if not data:
                break
            out += data
            off += len(data)
            if len(data) < size:            # nachgiebige Karte: Datei zu Ende
                break
        elif sw == 0x6282:                  # Dateiende erreicht
            out += data
            break
        elif sw == 0x6700:                  # falsche Länge – kleineren Block versuchen
            if size <= 1:
                if not out:                 # gar nichts lesbar: echter Fehler, nicht Dateiende
                    raise CardError(f"READ BINARY {what}@{off}".replace("  ", " "), sw)
                break                       # sonst: Datei zu Ende
            size = max(1, size // 2)
        elif sw in (0x6B00, 0x6A86):        # Offset hinter dem Dateiende
            break
        else:
            raise CardError(f"READ BINARY {what}@{off}".replace("  ", " "), sw)
    return bytes(out)


def _read_app(card: Card, files, gen: int, ddd: DddFile, warn: list[str],
              progress: Callable[[int, int], None], step: list[int], total: int) -> None:
    app_data, app_sig = (0, 1) if gen == 1 else (2, 3)
    for fid, signed, optional in files:
        step[0] += 1
        progress(step[0], total)
        try:
            select_ef(card, fid)
        except CardError as e:
            if not optional:
                warn.append(Note(str(e)))
            continue
        try:
            if signed:
                _cmd(card, HASH_APDU, f"PERFORM HASH {fid:04X}")
            ddd.add(fid, app_data, read_all(card, what=f"{fid:04X} "))
        except CardError as e:
            # Lieber eine Datei weniger als gar kein Download. 6982 heißt, dass die
            # Karte die Datei nur einem authentisierten Fahrzeuggerät zeigt – das ist
            # kein Fehler des Downloads, sondern eine Eigenschaft der Datei.
            warn.append(Note(str(e), "info" if e.sw == SW_SECURITY else "warning"))
            continue
        if signed:
            try:
                ddd.add(fid, app_sig, read_signature(card, fid, gen))
            except CardError as e:
                # Die Nutzdaten sind gelesen; ohne Signatur ist die Datei nur nicht
                # mehr auf Echtheit prüfbar – das ist kein Grund, alles zu verwerfen.
                warn.append(Note(str(e)))


PROBE = [
    ("SELECT MF (P2=0C)", "00A4000C023F00"),
    ("SELECT MF (P2=00)", "00A40000023F00"),
    ("SELECT MF (P2=04)", "00A40004023F00"),
    ("SELECT MF ohne FID", "00A4000C00"),
    ("SELECT MF ohne Lc", "00A4000C"),
    ("SELECT über leeren Namen", "00A4040C00"),
    ("SELECT AID Gen1", "00A4040C06FF544143484F"),
    ("SELECT AID Gen1 (P2=00)", "00A4040006FF544143484F"),
    ("SELECT EF_ICC (0002)", "00A4020C020002"),
    ("SELECT AID Gen2", "00A4040C06FF534D524454"),
    ("SELECT AID Gen2 (P2=00)", "00A4040006FF534D524454"),
    ("SELECT EF_Identification (0520)", "00A4020C020520"),
    ("READ BINARY 16 Byte", "00B0000010"),
    ("READ BINARY 200 Byte", "00B00000C8"),
    ("PERFORM HASH OF FILE", "802A9000"),
    ("PSO Signatur Le=00", "002A9E9A00"),
    ("PERFORM HASH OF FILE", "802A9000"),
    ("PSO Signatur Le=80 (128)", "002A9E9A80"),
    ("PERFORM HASH OF FILE", "802A9000"),
    ("PSO Signatur Le=40 (64)", "002A9E9A40"),
    ("PERFORM HASH OF FILE", "802A9000"),
    ("PSO Signatur Le=84 (132)", "002A9E9A84"),
]


CARD_TYPES = {0: "keine Karte", 1: "Fahrerkarte", 2: "Werkstattkarte (PIN erforderlich)",
              3: "Kontrollkarte", 4: "Unternehmenskarte"}


def _card_type(card: Card) -> str:
    """Kartenart aus EF_Application_Identification (erstes Byte)."""
    for aid in (AID_G2, AID_G1):
        if not select_aid(card, aid):
            continue
        try:
            select_ef(card, 0x0501)
            data = read_all(card, chunk=0x10)
        except CardError as e:
            return f"nicht lesbar ({e})"
        if data:
            return CARD_TYPES.get(data[0], f"unbekannt ({data[0]})")
    return "keine Tachographenanwendung"


def probe(card: Card) -> list[str]:
    """Diagnose: sendet die üblichen Auswahlbefehle und protokolliert die Antworten.

    Dient dazu, bei einer nicht lesbaren Karte festzustellen, welche Befehlsform
    sie akzeptiert. Es werden ausschließlich lesende Befehle gesendet.
    """
    atr = card.atr()
    lines = [f"ATR: {atr.hex(' ').upper() or '–'}", f"Protokoll: {card.protocol}", ""]
    card.begin()
    try:
        for what, hexa in PROBE:
            try:
                data, sw = card.transmit(bytes.fromhex(hexa))
                note = f"SW={sw:04X}"
                if sw == SW_OK:
                    note += " OK"
                if data:
                    # Nur die Länge, nie der Inhalt: gelesene Bytes sind Fahrerdaten
                    # (die Datei 0520 beginnt zum Beispiel mit der Kartennummer).
                    note += f", {len(data)} Byte gelesen"
                lines.append(f"{hexa:<24} {what:<28} {note}")
            except Exception as e:                      # pragma: no cover - Hardwarepfad
                lines.append(f"{hexa:<24} {what:<28} {type(e).__name__}: {e}")
        try:
            lines += ["", f"Kartenart: {_card_type(card)}"]
        except Exception as e:                          # pragma: no cover - Hardwarepfad
            lines += ["", f"Kartenart: nicht bestimmbar ({type(e).__name__}: {e})"]
    finally:
        card.end()
    return lines


def download_card(card: Card,
                  progress: Callable[[int, int], None] = lambda a, b: None) -> tuple[bytes, list[Note]]:
    """Liest die Karte vollständig und liefert (DDD-Bytes, Rückmeldungen)."""
    ddd = DddFile()
    warn: list[Note] = []
    total = len(MF_FILES) + len(G1_FILES) + len(G2_FILES)
    step = [0]
    card.begin()
    try:
        sw = select_mf(card)
        mf_ok = sw == SW_OK
        if not mf_ok:
            # Die Anwendungen lassen sich über ihren Namen (AID) trotzdem auswählen;
            # es fehlen dann nur EF_ICC und EF_IC, die zur Auswertung nicht nötig sind.
            warn.append(Note(i18n.tr("note_no_mf", sw=f"{sw:04X}"), "info"))
            step[0] += len(MF_FILES)
            progress(step[0], total)
        else:
            for fid, _, _ in MF_FILES:
                step[0] += 1
                progress(step[0], total)
                try:
                    select_ef(card, fid)
                    ddd.add(fid, 0, read_all(card))
                except CardError as e:
                    warn.append(Note(str(e)))

        has_g1 = select_aid(card, AID_G1)
        if has_g1:
            _read_app(card, G1_FILES, 1, ddd, warn, progress, step, total)

        if mf_ok:                      # sonst waere es nur ein zweiter Fehlversuch
            select_mf(card)
        if select_aid(card, AID_G2):
            _read_app(card, G2_FILES, 2, ddd, warn, progress, step, total)
        elif not has_g1:
            raise CardError("no tachograph application", 0x6A82)
    finally:
        card.end()
    progress(total, total)
    return ddd.to_bytes(), warn
