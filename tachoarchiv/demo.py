"""Erzeugt eine Demo-Fahrerkarte (Gen1-DDD, Dummy-Signaturen) mit typischen Verstößen."""
from __future__ import annotations

import datetime as dt
import struct

from .ddd import DddFile
from .parser import AVAIL, DRIVE, REST, WORK, ActivityChange

UTC = dt.timezone.utc


def _tr(t: dt.datetime | None) -> bytes:
    return struct.pack(">I", int(t.timestamp()) if t else 0)


def _txt(s: str, n: int) -> bytes:
    return bytes([1]) + s.encode("iso8859_1").ljust(n - 1, b" ")[: n - 1]


def encode_activity(days: list[tuple[dt.datetime, int, list[ActivityChange]]],
                    struct_len: int, rotate: int = 0) -> bytes:
    buf = bytearray(struct_len)
    recs = []
    prev = 0
    for i, (date, dist, changes) in enumerate(days):
        body = _tr(date) + bytes.fromhex(f"{i + 1:04d}") + struct.pack(">H", dist)
        body += b"".join(struct.pack(">H", c.encode()) for c in changes)
        rec = struct.pack(">HH", prev, len(body) + 4) + body
        prev = len(rec)
        recs.append(rec)
    pos = 0
    offsets = []
    for rec in recs:
        offsets.append(pos)
        buf[pos:pos + len(rec)] = rec
        pos += len(rec)
    if pos > struct_len:
        raise ValueError("buffer too small")
    oldest, newest = offsets[0], offsets[-1]
    if rotate:
        buf = buf[-rotate:] + buf[:-rotate]
        oldest = (oldest + rotate) % struct_len
        newest = (newest + rotate) % struct_len
    return struct.pack(">HH", oldest, newest) + bytes(buf)


def _day(plan: list[tuple[int, int]], absent_from: int | None = None) -> list[ActivityChange]:
    out = []
    for minute, act in plan:
        absent = 1 if absent_from is not None and minute >= absent_from else 0
        out.append(ActivityChange(minute, 0, 0, absent, act))
    return out


NORMAL = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (810, WORK),
          (825, REST), (870, DRIVE), (960, WORK), (990, REST)]
SHORT = [(0, REST), (300, WORK), (315, DRIVE), (555, WORK), (600, REST)]
NO_BREAK = [(0, REST), (300, WORK), (315, DRIVE), (615, REST), (660, DRIVE), (840, REST)]
LONG = [(0, REST), (240, WORK), (255, DRIVE), (525, REST), (570, DRIVE), (840, REST),
        (885, DRIVE), (945, WORK), (990, REST)]
LATE = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (840, WORK),
        (900, REST), (1020, DRIVE), (1260, WORK), (1320, REST)]
AFTER_LATE = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (660, WORK),
              (690, REST)]
FREE = [(0, REST)]
# Nachtfähre: Ruhezeit ab 14:00, zweimal kurz unterbrochen (Art. 9 Abs. 1 – zulässig)
FERRY = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (810, WORK),
         (840, REST), (1200, WORK), (1220, REST), (1380, WORK), (1400, REST)]
# dasselbe mit drei Unterbrechungen – die dritte ist nicht mehr gedeckt
FERRY_BAD = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (810, WORK),
             (840, REST), (1200, WORK), (1215, REST), (1320, WORK), (1335, REST),
             (1410, WORK), (1425, REST)]
FERRY_NEXT = [(0, REST), (360, DRIVE), (600, WORK), (615, REST), (660, DRIVE), (870, WORK),
              (900, REST)]
FERRY_DAYS = (23, 30)          # Tage mit Überfahrt, Kennzeichnung jeweils 19:00 UTC
FERRY_MARK = 1140


def build_demo(today: dt.date | None = None) -> bytes:
    today = today or dt.datetime.now(UTC).date()
    start = today - dt.timedelta(days=today.weekday() + 35)   # Montag vor 5 Wochen
    days = []
    for i in range(35 + today.weekday()):
        d = start + dt.timedelta(days=i)
        wd = d.weekday()
        if wd >= 5:
            plan, dist, absent = FREE, 0, 0
        else:
            plan, dist, absent = NORMAL, 610, None
            if i == 2:
                plan, dist = NO_BREAK, 560
            if i in (8, 9, 10):
                plan, dist = LONG, 780
            if i == 11:
                plan, dist = SHORT, 310
            if i == 16:
                plan, dist = LATE, 690
            if i == 17:
                plan, dist = AFTER_LATE, 520
            if i == FERRY_DAYS[0]:
                plan, dist = FERRY, 520
            if i == FERRY_DAYS[1]:
                plan, dist = FERRY_BAD, 520
            if i - 1 in FERRY_DAYS:
                plan, dist = FERRY_NEXT, 470
        date = dt.datetime(d.year, d.month, d.day, tzinfo=UTC)
        ch = _day(plan, absent)
        if wd >= 5:
            ch = [ActivityChange(0, 0, 0, 1, REST)]
        days.append((date, dist, ch))

    struct_len = 13776
    now = dt.datetime.combine(today, dt.time(6, 0), UTC)
    ddd = DddFile()
    ddd.add(0x0002, 0, bytes(25))
    ddd.add(0x0005, 0, bytes(8))
    app = bytes([1]) + struct.pack(">H", 0) + bytes([12, 24]) + struct.pack(">HHB", struct_len, 84, 112)
    sig = bytes(128)
    ddd.add(0x0501, 0, app); ddd.add(0x0501, 1, sig)
    ddd.add(0xC100, 0, bytes(194))
    ddd.add(0xC108, 0, bytes(194))
    ident = (bytes([13]) + b"DF00001234567000" + _txt("Kraftfahrt-Bundesamt", 36)
             + _tr(now - dt.timedelta(days=1700)) + _tr(now - dt.timedelta(days=1700))
             + _tr(now + dt.timedelta(days=45))
             + _txt("Demo-Mustermann", 36) + _txt("Max", 36) + bytes.fromhex("19800412") + b"de")
    ddd.add(0x0520, 0, ident); ddd.add(0x0520, 1, sig)
    ddd.add(0x050E, 0, _tr(now - dt.timedelta(days=40))); ddd.add(0x050E, 1, sig)
    ddd.add(0x0521, 0, _txt("Stadt Leipzig", 36) + bytes([13]) + b"B072RRE2I55     ")
    ddd.add(0x0521, 1, sig)
    ev = bytearray(6 * 12 * 24)
    t = dt.datetime.combine(start + dt.timedelta(days=3), dt.time(7, 12), UTC)
    ev[0:24] = bytes([4]) + _tr(t) + _tr(t + dt.timedelta(minutes=9)) + bytes([13]) + _txt("L-TA 2026", 14)
    ddd.add(0x0502, 0, bytes(ev)); ddd.add(0x0502, 1, sig)
    ddd.add(0x0503, 0, bytes(2 * 24 * 24)); ddd.add(0x0503, 1, sig)
    ddd.add(0x0504, 0, encode_activity(days, struct_len, rotate=4000)); ddd.add(0x0504, 1, sig)
    veh = bytearray(2 + 84 * 31)
    first = dt.datetime.combine(start, dt.time(5, 0), UTC)
    rec = (struct.pack(">I", 412000)[1:] + struct.pack(">I", 425400)[1:] + _tr(first) + _tr(now)
           + bytes([13]) + _txt("L-TA 2026", 14) + b"\x00\x01")
    veh[2:33] = rec
    ddd.add(0x0505, 0, bytes(veh)); ddd.add(0x0505, 1, sig)
    places = bytearray(1 + 112 * 10)
    places[1:11] = _tr(first) + bytes([0, 13, 0x0D]) + struct.pack(">I", 412000)[1:]
    ddd.add(0x0506, 0, bytes(places)); ddd.add(0x0506, 1, sig)
    ddd.add(0x0507, 0, _tr(now) + bytes([13]) + _txt("L-TA 2026", 14)); ddd.add(0x0507, 1, sig)
    ddd.add(0x0508, 0, bytes(46)); ddd.add(0x0508, 1, sig)
    cond = bytearray(56 * 5)
    for n, day_no in enumerate(FERRY_DAYS):          # Gen 1 kennt nur die Beginn-Kennzeichnung
        t = dt.datetime.combine(start + dt.timedelta(days=day_no), dt.time(0, 0), UTC) \
            + dt.timedelta(minutes=FERRY_MARK)
        cond[n * 5:(n + 1) * 5] = _tr(t) + bytes([3])
    ddd.add(0x0522, 0, bytes(cond)); ddd.add(0x0522, 1, sig)
    return ddd.to_bytes()


# --------------------------------------------------------------------- Fahrzeugdatei

def _speed_profile(day: dt.date) -> list[tuple[dt.datetime, list[int]]]:
    """Ein Fahrtag in Minutenblöcken zu je 60 Sekundenwerten.

    Erfunden, aber so geformt, wie ein Massenspeicher es liefert: ruhige Fahrt
    knapp unter der Grenze, zwei bewusste Überschreitungen, Pausen bei 0.
    """
    import math
    out = []
    for minute in range(0, 1440):
        hour = minute / 60
        driving = (5.0 <= hour < 9.0) or (9.75 <= hour < 13.0) or (14.0 <= hour < 16.5)
        values = []
        for sec in range(60):
            if not driving:
                values.append(0)
                continue
            v = 82 + 4 * math.sin(hour * 0.9 + sec / 600)
            if 7.0 <= hour < 7.3 or 11.1 <= hour < 11.4:        # Ortsdurchfahrt
                v = 48
            if 8.1 <= hour < 8.35:                              # Gefälle
                v = 97
            if 15.2 <= hour < 15.5:
                v = 94
            values.append(int(round(v)))
        if any(values):
            out.append((dt.datetime.combine(day, dt.time(minute // 60, minute % 60), UTC), values))
    return out


def build_demo_vu(today: dt.date | None = None) -> bytes:
    """Erzeugt eine Fahrzeugdatei (Generation 1) mit Übersicht und Geschwindigkeit.

    Nur zum Vorführen: die Signaturen sind leer und die Werte erfunden. Eine echte
    Datei aus einem Fahrtenschreiber sieht im Aufbau genauso aus.
    """
    today = today or dt.date.today()
    now = dt.datetime.combine(today, dt.time(18, 22), UTC)
    begin = now - dt.timedelta(days=28)
    head = bytearray(491)
    head[388:405] = b"WDB9634261L123456"
    head[405] = 13                                   # D
    head[406:420] = _txt("MA-TA 1234", 14)
    head[420:424] = _tr(now)
    head[424:428] = _tr(begin)
    head[428:432] = _tr(now)
    head[433:437] = _tr(now)
    head[439:455] = b"DF00001234567000"
    head[455:491] = _txt("Spedition Muster GmbH (Demo)", 36)
    overview = bytes(head) + b"\x00" + b"\x00" + bytes(128)   # keine Sperren, keine Kontrollen

    blocks = []
    for offset in (2, 1):
        for start, values in _speed_profile(today - dt.timedelta(days=offset)):
            blocks.append(_tr(start) + bytes(values))
    speed = struct.pack(">H", len(blocks)) + b"".join(blocks) + bytes(128)
    return b"\x76\x01" + overview + b"\x76\x04" + speed
