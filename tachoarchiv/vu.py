"""Fahrzeug-Download (Massenspeicher) nach Anhang IB/IC, Anlage 7.

Eine Fahrzeugdatei ist die Aneinanderreihung der Übertragungsantworten des
Fahrtenschreibers. Jeder Block beginnt mit 0x76, gefolgt von der Kennung des
Datenbereichs (TREP):

    Gen 1        Gen 2        Gen 2 V2     Inhalt
    0x01         0x21         0x31         Übersicht
    0x02         0x22         0x32         Aktivitäten eines Tages
    0x03         0x23         0x33         Ereignisse und Störungen
    0x04         0x24         0x34         Geschwindigkeitsverlauf
    0x05         0x25         0x35         Technische Daten

Für die Archivierung wird die Datei nie verändert; ausgewertet werden nur die
Kopfdaten aus dem Übersichtsblock. Schlägt das fehl, bleibt die Datei trotzdem
archivierbar – sie wird dann ohne Kennzeichen abgelegt.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .parser import ia5, nation, text, time_real, u16

TREP_NAMES = {
    1: "overview", 2: "activities", 3: "events", 4: "speed", 5: "technical",
    0x21: "overview", 0x22: "activities", 0x23: "events", 0x24: "speed", 0x25: "technical",
    0x31: "overview", 0x32: "activities", 0x33: "events", 0x34: "speed", 0x35: "technical",
}
OVERVIEW = (0x01, 0x21, 0x31)
ACTIVITIES = (0x02, 0x22, 0x32)


class VuError(ValueError):
    pass


@dataclass
class VuInfo:
    vin: str = ""
    nation: str = ""
    registration: str = ""
    generation: int = 1
    version: int = 1                      # 2 = Smart Tachograph Version 2
    current_time: dt.datetime | None = None
    period_begin: dt.datetime | None = None
    period_end: dt.datetime | None = None
    downloaded_at: dt.datetime | None = None
    company: str = ""
    card_number: str = ""
    blocks: list[int] = field(default_factory=list)
    days: int = 0                         # Anzahl der Aktivitätsblöcke (Tage)

    @property
    def plate(self) -> str:
        return " ".join(p for p in (self.nation, self.registration) if p)

    @property
    def label(self) -> str:
        return self.plate or self.vin or "unbekannt"


@dataclass
class VuFile:
    blocks: list[tuple[int, bytes]] = field(default_factory=list)

    def get(self, treps) -> bytes | None:
        for t, d in self.blocks:
            if t in treps:
                return d
        return None


MIN_BLOCK = 130            # jeder Block endet mit einer Signatur (Gen 1: 128 Byte)


def _is_start(raw: bytes, i: int) -> bool:
    return i + 1 < len(raw) and raw[i] == 0x76 and raw[i + 1] in TREP_NAMES


def _len_gen2(raw: bytes, start: int) -> int | None:
    """Gen 2: Die Satzfelder tragen ihre Länge selbst – der Block ist exakt messbar."""
    pos = start
    while pos + 5 <= len(raw):
        if _is_start(raw, pos):
            break                                       # nächster Block beginnt
        size, count = u16(raw, pos + 1), u16(raw, pos + 3)
        if size == 0 or pos + 5 + size * count > len(raw):
            return None
        pos += 5 + size * count
    return pos - start if pos > start else None


def _len_overview_gen1(raw: bytes, start: int) -> int | None:
    """Gen 1: Die Übersicht hat feste Feldlängen, nur die Sperren zählen variabel."""
    pos = start + 194 + 194 + 17 + 15 + 4 + 8 + 1 + 58
    if pos + 1 > len(raw):
        return None
    pos += 1 + raw[pos] * 98                            # Unternehmenssperren
    if pos + 1 > len(raw):
        return None
    pos += 1 + raw[pos] * 31 + 128                      # Kontrollen + Signatur
    return pos - start if pos <= len(raw) else None


def _len_guess(raw: bytes, start: int, trep: int) -> int:
    """Rückfall: bis zum nächsten plausiblen Blockanfang."""
    i = start + MIN_BLOCK
    while i < len(raw) - 1:
        if _is_start(raw, i):
            nxt = raw[i + 1]
            if nxt > trep or (nxt == trep and trep in ACTIVITIES):
                return i - start
        i += 1
    return len(raw) - start


def split_blocks(raw: bytes) -> list[tuple[int, bytes]]:
    """Zerlegt die Datei in Blöcke.

    Die Übertragungsantworten enthalten keine Längenangabe. Bei Generation 2 lässt
    sich die Länge aus den Satzfeldern exakt bestimmen, bei Generation 1 nur für den
    Übersichtsblock; die übrigen Blöcke werden anhand des nächsten plausiblen
    Blockanfangs abgegrenzt. Für die Archivierung ist das ohne Belang – die Datei
    wird unverändert gespeichert –, es betrifft nur die Angabe, was sie enthält.
    """
    if not _is_start(raw, 0):
        raise VuError("no vu file")
    out: list[tuple[int, bytes]] = []
    pos = 0
    while _is_start(raw, pos):
        trep = raw[pos + 1]
        body = pos + 2
        ln = _len_gen2(raw, body) if trep >= 0x20 else (
            _len_overview_gen1(raw, body) if trep == 0x01 else None)
        if ln is None or ln <= 0 or body + ln > len(raw):
            ln = _len_guess(raw, body, trep)
        out.append((trep, raw[body:body + ln]))
        pos = body + ln
    return out


def _record_arrays(b: bytes) -> list[tuple[int, list[bytes]]]:
    """Gen 2: Folge von Satzfeldern, je 1 Byte Typ, 2 Byte Satzlänge, 2 Byte Anzahl."""
    out = []
    pos = 0
    while pos + 5 <= len(b):
        rtype = b[pos]
        size = u16(b, pos + 1)
        count = u16(b, pos + 3)
        pos += 5
        if size == 0 or pos + size * count > len(b):
            break
        out.append((rtype, [b[pos + i * size: pos + (i + 1) * size] for i in range(count)]))
        pos += size * count
    return out


def _parse_overview_gen1(b: bytes, info: VuInfo) -> None:
    o = 194 + 194                                       # zwei Zertifikate
    if len(b) < o + 44:
        raise VuError("overview too short")
    info.vin = ia5(b[o:o + 17])
    info.nation = nation(b[o + 17])
    info.registration = text(b[o + 18:o + 32])
    info.current_time = time_real(b, o + 32)
    info.period_begin = time_real(b, o + 36)
    info.period_end = time_real(b, o + 40)
    o += 45                                             # + CardSlotsStatus
    if len(b) >= o + 58:
        info.downloaded_at = time_real(b, o)
        info.card_number = ia5(b[o + 6:o + 22])
        info.company = text(b[o + 22:o + 58])


def _parse_overview_gen2(b: bytes, info: VuInfo) -> None:
    arrays = _record_arrays(b)
    if len(arrays) < 6:
        raise VuError("overview too short")
    # Reihenfolge nach Anhang IC: Zertifikate, FIN, Kennzeichen, Zeit, Zeitraum, …
    def rec(i: int) -> bytes:
        return arrays[i][1][0] if i < len(arrays) and arrays[i][1] else b""
    info.vin = ia5(rec(2))
    plate = rec(3)
    if len(plate) >= 15:
        info.nation = nation(plate[0])
        info.registration = text(plate[1:15])
    info.current_time = time_real(rec(4))
    period = rec(5)
    if len(period) >= 8:
        info.period_begin = time_real(period, 0)
        info.period_end = time_real(period, 4)
    act = rec(7)
    if len(act) >= 23:
        info.downloaded_at = time_real(act, 0)
        info.card_number = ia5(act[6:22])
        info.company = text(act[23:]) if len(act) > 23 else ""


def parse_vu(raw: bytes) -> tuple[VuFile, VuInfo]:
    """Zerlegt eine Fahrzeugdatei und liest die Kopfdaten des Übersichtsblocks."""
    vf = VuFile(split_blocks(raw))
    info = VuInfo(blocks=[t for t, _ in vf.blocks])
    info.days = sum(1 for t in info.blocks if t in ACTIVITIES)
    treps = set(info.blocks)
    if treps & {0x31, 0x32, 0x33, 0x34, 0x35}:
        info.generation, info.version = 2, 2
    elif treps & {0x21, 0x22, 0x23, 0x24, 0x25}:
        info.generation, info.version = 2, 1
    head = vf.get(OVERVIEW)
    if head is None:
        raise VuError("no overview block")
    if info.generation == 1:
        _parse_overview_gen1(head, info)
    else:
        _parse_overview_gen2(head, info)
    return vf, info


def is_vu_file(raw: bytes) -> bool:
    return len(raw) > 2 and raw[0] == 0x76 and raw[1] in TREP_NAMES


# --------------------------------------------------------------------- Geschwindigkeit

SPEED = (0x04, 0x24, 0x34)
SPEED_BLOCK = 64                 # 4 Byte Beginn der Minute + 60 Werte, einer je Sekunde
MAX_SPEED = 250                  # darüber ist der Satz unglaubwürdig, nicht der Lkw schnell
NOT_AVAILABLE = 0xFF             # das Gerät hat für diese Sekunde keinen Wert
EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


@dataclass
class SpeedBlock:
    """Eine Minute Geschwindigkeit, ein Wert je Sekunde (km/h); -1 = kein Wert."""
    start: dt.datetime
    speeds: list[int]


@dataclass
class Overspeed:
    """Ein zusammenhängender Abschnitt über dem Grenzwert."""
    start: dt.datetime
    seconds: int
    peak: int
    average: int


def _plausible(block: SpeedBlock, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    if not (EPOCH <= block.start <= now + dt.timedelta(days=366)):
        return False
    return len(block.speeds) == 60 and all(-1 <= s <= MAX_SPEED for s in block.speeds)


def _blocks_from(body: bytes, offset: int, count: int | None = None) -> list[SpeedBlock]:
    out = []
    pos = offset
    n = 0
    while pos + SPEED_BLOCK <= len(body) and (count is None or n < count):
        when = time_real(body, pos)
        if when is None:
            break
        blk = SpeedBlock(when, [-1 if v == NOT_AVAILABLE else v
                                for v in body[pos + 4:pos + SPEED_BLOCK]])
        if not _plausible(blk):
            break
        out.append(blk)
        pos += SPEED_BLOCK
        n += 1
    return out


def parse_speed(vf: VuFile) -> list[SpeedBlock]:
    """Liest die Geschwindigkeitsblöcke (TREP 0x04/0x24/0x34).

    Generation 1 trägt vor den Sätzen eine Anzahl, Generation 2 legt sie in
    Satzfeldern ab. Beides wird geprüft: Zeitstempel und Werte müssen plausibel
    sein, sonst gilt der Satz als nicht lesbar und wird übergangen – lieber keine
    Kurve als eine erfundene.
    """
    out: list[SpeedBlock] = []
    for trep, body in vf.blocks:
        if trep not in SPEED:
            continue
        if trep >= 0x20:
            for _, records in _record_arrays(body):
                if not records or len(records[0]) != SPEED_BLOCK:
                    continue
                joined = b"".join(records)
                out += _blocks_from(joined, 0, len(records))
        else:
            count = u16(body, 0) if len(body) >= 2 else 0
            blocks = _blocks_from(body, 2, count) if count else []
            if not blocks:                      # Anzahl unglaubwürdig: ohne sie lesen
                blocks = _blocks_from(body, 2)
            out += blocks
    out.sort(key=lambda b: b.start)
    return out


def speed_days(blocks: list[SpeedBlock]) -> dict[dt.date, list[SpeedBlock]]:
    days: dict[dt.date, list[SpeedBlock]] = {}
    for b in blocks:
        days.setdefault(b.start.date(), []).append(b)
    return days


def speed_series(blocks: list[SpeedBlock], day: dt.date) -> list[int]:
    """Der Tag als 86400 Sekundenwerte; -1 steht für „nicht aufgezeichnet“."""
    series = [-1] * 86400
    for b in blocks:
        if b.start.date() != day:
            continue
        base = b.start.hour * 3600 + b.start.minute * 60
        for i, v in enumerate(b.speeds):
            if 0 <= base + i < 86400:
                series[base + i] = v
    return series


def overspeed(blocks: list[SpeedBlock], day: dt.date, limit: int,
              min_seconds: int = 5, gap: int = 30) -> list[Overspeed]:
    """Abschnitte über dem Grenzwert.

    Kurze Ausreißer und kurze Unterbrechungen werden zusammengefasst – sonst
    zerfällt eine Überschreitung in hundert Zeilen, sobald die Nadel am Grenzwert
    pendelt. Unterbrechungen bis 30 s gelten als derselbe Abschnitt.
    """
    series = speed_series(blocks, day)
    spans: list[list[int]] = []
    start = None
    for i, v in enumerate(series + [-1]):
        if v > limit and start is None:
            start = i
        elif v <= limit and start is not None:
            if spans and start - (spans[-1][0] + spans[-1][1]) < gap:
                spans[-1][1] = i - spans[-1][0]
            else:
                spans.append([start, i - start])
            start = None
    midnight = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
    out = []
    for begin, length in spans:
        seg = [v for v in series[begin:begin + length] if v >= 0]
        if length < min_seconds or not seg:
            continue
        out.append(Overspeed(midnight + dt.timedelta(seconds=begin), length,
                             max(seg), round(sum(seg) / len(seg))))
    return out


def speed_stats(blocks: list[SpeedBlock], day: dt.date, limit: int) -> dict:
    series = speed_series(blocks, day)
    recorded = [v for v in series if v >= 0]
    moving = [v for v in recorded if v > 0]
    peak = max(recorded, default=0)
    peak_at = series.index(peak) if peak else 0
    return {
        "recorded": len(recorded),
        "moving": len(moving),
        "peak": peak,
        "peak_at": dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
                   + dt.timedelta(seconds=peak_at) if peak else None,
        "average": round(sum(moving) / len(moving)) if moving else 0,
        "over": sum(1 for v in recorded if v > limit),
        "distance": round(sum(moving) / 3600),      # km, aus Sekundenwerten
    }
