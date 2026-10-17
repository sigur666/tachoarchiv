"""Dekodierung der Fahrerkarten-Datenstrukturen (Anhang IB/IC, Anlage 1)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .ddd import DddFile

UTC = dt.timezone.utc

REST, AVAIL, WORK, DRIVE = 0, 1, 2, 3

# SpecificConditionType (Anhang IC, Anlage 1)
COND_OUT_BEGIN, COND_OUT_END, COND_FERRY_BEGIN, COND_FERRY_END = 1, 2, 3, 4

NATIONS = [
    "", "A", "AL", "AND", "ARM", "AZ", "B", "BG", "BIH", "BY", "CH", "CY", "CZ", "D", "DK", "E",
    "EST", "F", "FIN", "FL", "FO", "UK", "GE", "GR", "H", "HR", "I", "IRL", "IS", "KZ", "L", "LT",
    "LV", "M", "MC", "MD", "MK", "N", "NL", "P", "PL", "RO", "RSM", "RUS", "S", "SK", "SLO", "TM",
    "TR", "UA", "V", "YU", "MNE", "SRB", "UZ", "TJ",
]
NATIONS_SPECIAL = {0xFD: "EC", 0xFE: "EUR", 0xFF: "WLD"}

CODEPAGES = {1: "iso8859_1", 2: "iso8859_2", 3: "iso8859_3", 4: "iso8859_4", 5: "iso8859_5",
             6: "iso8859_6", 7: "iso8859_7", 8: "iso8859_8", 9: "iso8859_9", 10: "iso8859_10",
             11: "iso8859_11", 13: "iso8859_13", 14: "iso8859_14", 15: "iso8859_15",
             16: "iso8859_16", 80: "koi8_r", 85: "koi8_u"}


def nation(n: int) -> str:
    if n < len(NATIONS):
        return NATIONS[n]
    return NATIONS_SPECIAL.get(n, f"#{n}")


def u16(b: bytes, o: int = 0) -> int:
    return int.from_bytes(b[o:o + 2], "big")


def u24(b: bytes, o: int = 0) -> int:
    return int.from_bytes(b[o:o + 3], "big")


def u32(b: bytes, o: int = 0) -> int:
    return int.from_bytes(b[o:o + 4], "big")


def time_real(b: bytes, o: int = 0) -> dt.datetime | None:
    if len(b) < o + 4:
        return None
    v = u32(b, o)
    if v in (0, 0xFFFFFFFF):
        return None
    return dt.datetime.fromtimestamp(v, UTC)


def bcd(b: bytes) -> int:
    s = b.hex()
    return int(s) if s.isdigit() else 0


def datef(b: bytes) -> dt.date | None:
    s = b.hex()
    try:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def text(b: bytes) -> str:
    if not b:
        return ""
    enc = CODEPAGES.get(b[0], "iso8859_1")
    return b[1:].decode(enc, "replace").strip(" \x00\xff")


def ia5(b: bytes) -> str:
    return b.decode("iso8859_1", "replace").strip(" \x00\xff")


@dataclass
class CardInfo:
    generation: int = 1
    card_number: str = ""
    issuing_nation: str = ""
    authority: str = ""
    issue_date: dt.datetime | None = None
    validity_begin: dt.datetime | None = None
    expiry_date: dt.datetime | None = None
    surname: str = ""
    firstnames: str = ""
    birth_date: dt.date | None = None
    language: str = ""
    licence_nation: str = ""
    licence_number: str = ""
    last_download: dt.datetime | None = None

    @property
    def display_name(self) -> str:
        return ", ".join(p for p in (self.surname, self.firstnames) if p)


@dataclass
class ActivityChange:
    minute: int
    slot: int
    crew: int
    absent: int
    activity: int

    @classmethod
    def decode(cls, v: int) -> "ActivityChange":
        return cls(v & 0x7FF, (v >> 15) & 1, (v >> 14) & 1, (v >> 13) & 1, (v >> 11) & 3)

    def encode(self) -> int:
        return (self.slot << 15) | (self.crew << 14) | (self.absent << 13) | (self.activity << 11) | self.minute


@dataclass
class DailyRecord:
    date: dt.datetime
    presence: int
    distance: int
    changes: list[ActivityChange]


@dataclass
class VehicleUse:
    first_use: dt.datetime | None
    last_use: dt.datetime | None
    odo_begin: int
    odo_end: int
    nation: str
    registration: str
    vin: str = ""


@dataclass
class PlaceRecord:
    time: dt.datetime | None
    entry_type: int
    country: str
    region: int
    odometer: int
    lat: float | None = None
    lon: float | None = None


@dataclass
class EventRecord:
    type: int
    begin: dt.datetime | None
    end: dt.datetime | None
    nation: str
    registration: str
    fault: bool = False


@dataclass
class ControlRecord:
    type: int
    time: dt.datetime | None
    card_number: str
    registration: str
    period_begin: dt.datetime | None
    period_end: dt.datetime | None


@dataclass
class ConditionRecord:
    time: dt.datetime | None
    type: int


@dataclass
class CardData:
    info: CardInfo = field(default_factory=CardInfo)
    days: list[DailyRecord] = field(default_factory=list)
    vehicles: list[VehicleUse] = field(default_factory=list)
    places: list[PlaceRecord] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    controls: list[ControlRecord] = field(default_factory=list)
    conditions: list[ConditionRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- Strukturen

def parse_app_id(b: bytes, gen: int) -> dict:
    d = {"type": b[0], "version": u16(b, 1), "events": b[3], "faults": b[4],
         "activity_len": u16(b, 5), "vehicles": u16(b, 7)}
    d["places"] = b[9] if gen == 1 else u16(b, 9)
    return d


def parse_identification(b: bytes, info: CardInfo) -> None:
    info.issuing_nation = nation(b[0])
    info.card_number = ia5(b[1:17])
    info.authority = text(b[17:53])
    info.issue_date = time_real(b, 53)
    info.validity_begin = time_real(b, 57)
    info.expiry_date = time_real(b, 61)
    if len(b) >= 143:
        info.surname = text(b[65:101])
        info.firstnames = text(b[101:137])
        info.birth_date = datef(b[137:141])
        info.language = ia5(b[141:143])


def parse_licence(b: bytes, info: CardInfo) -> None:
    if len(b) >= 53:
        info.licence_nation = nation(b[36])
        info.licence_number = ia5(b[37:53])


def parse_activity(b: bytes, struct_len: int | None = None) -> list[DailyRecord]:
    if len(b) < 16:
        return []
    oldest, newest = u16(b, 0), u16(b, 2)
    buf = b[4:]
    if struct_len and struct_len <= len(buf):
        buf = buf[:struct_len]
    size = len(buf)

    def get(off: int, n: int) -> bytes:
        off %= size
        if off + n <= size:
            return buf[off:off + n]
        return buf[off:] + buf[: (off + n) - size]

    records: list[DailyRecord] = []
    pos = newest
    seen: set[int] = set()
    while pos < size and pos not in seen:
        seen.add(pos)
        hdr = get(pos, 12)
        prev_len, rec_len = u16(hdr, 0), u16(hdr, 2)
        if rec_len < 12 or rec_len > size:
            break
        rec = get(pos, rec_len)
        date = time_real(rec, 4)
        if date is not None:
            changes = [ActivityChange.decode(u16(rec, 12 + 2 * i)) for i in range((rec_len - 12) // 2)]
            records.append(DailyRecord(date, bcd(rec[8:10]), u16(rec, 10), changes))
        if pos == oldest or prev_len == 0:
            break
        pos = (pos - prev_len) % size
    records.reverse()
    return records


def parse_vehicles(b: bytes, gen: int) -> list[VehicleUse]:
    ptr_len, rec_len = (2, 31) if gen == 1 else (2, 48)
    out = []
    for o in range(ptr_len, len(b) - rec_len + 1, rec_len):
        r = b[o:o + rec_len]
        first = time_real(r, 6)
        if first is None:
            continue
        out.append(VehicleUse(first, time_real(r, 10), u24(r, 0), u24(r, 3), nation(r[14]),
                              text(r[15:29]), ia5(r[31:48]) if gen == 2 else ""))
    out.sort(key=lambda v: v.first_use)
    return out


def _coord(v: int) -> float | None:
    if v & 0x800000:
        v -= 0x1000000
    if abs(v) > 1800000 or v == -0x800000:
        return None
    a = abs(v)
    deg = a // 1000 + (a % 1000) / 10 / 60
    return -deg if v < 0 else deg


def parse_places(b: bytes, gen: int) -> list[PlaceRecord]:
    ptr_len, rec_len = (1, 10) if gen == 1 else (2, 21)
    out = []
    for o in range(ptr_len, len(b) - rec_len + 1, rec_len):
        r = b[o:o + rec_len]
        t = time_real(r, 0)
        if t is None:
            continue
        p = PlaceRecord(t, r[4], nation(r[5]), r[6], u24(r, 7))
        if gen == 2 and time_real(r, 10):
            p.lat, p.lon = _coord(u24(r, 15)), _coord(u24(r, 18))
        out.append(p)
    out.sort(key=lambda p: p.time)
    return out


def parse_events(b: bytes, fault: bool) -> list[EventRecord]:
    out = []
    for o in range(0, len(b) - 23, 24):
        r = b[o:o + 24]
        begin = time_real(r, 1)
        if r[0] == 0 and begin is None:
            continue
        if begin is None:
            continue
        out.append(EventRecord(r[0], begin, time_real(r, 5), nation(r[9]), text(r[10:24]), fault))
    return out


def parse_controls(b: bytes) -> list[ControlRecord]:
    out = []
    for o in range(0, len(b) - 45, 46):
        r = b[o:o + 46]
        t = time_real(r, 1)
        if t is None:
            continue
        out.append(ControlRecord(r[0], t, ia5(r[7:23]), text(r[24:38]), time_real(r, 38), time_real(r, 42)))
    return out


def parse_conditions(b: bytes, gen: int) -> list[ConditionRecord]:
    start = 0 if gen == 1 else 2
    out = []
    for o in range(start, len(b) - 4, 5):
        t = time_real(b, o)
        if t is not None and b[o + 4]:
            out.append(ConditionRecord(t, b[o + 4]))
    out.sort(key=lambda c: c.time)
    return out


# --------------------------------------------------------------------------- Gesamt

def _parse_app(ddd: DddFile, gen: int, card: CardData) -> list[DailyRecord]:
    a = 0 if gen == 1 else 2
    app_raw = ddd.get(0x0501, a)
    app = parse_app_id(app_raw, gen) if app_raw and len(app_raw) >= 10 else {}
    ident = ddd.get(0x0520, a)
    if ident:
        parse_identification(ident, card.info)
    lic = ddd.get(0x0521, a)
    if lic:
        parse_licence(lic, card.info)
    dl = ddd.get(0x050E, a)
    if dl:
        card.info.last_download = time_real(dl, 0)
    for fid, fn in ((0x0505, lambda b: parse_vehicles(b, gen)),):
        raw = ddd.get(fid, a)
        if raw:
            card.vehicles = fn(raw)
    raw = ddd.get(0x0506, a)
    if raw:
        card.places = parse_places(raw, gen)
    ev = ddd.get(0x0502, a) or b""
    fl = ddd.get(0x0503, a) or b""
    if ev or fl:
        card.events = parse_events(ev, False) + parse_events(fl, True)
        card.events.sort(key=lambda e: e.begin)
    raw = ddd.get(0x0508, a)
    if raw:
        card.controls = parse_controls(raw)
    raw = ddd.get(0x0522, a)
    if raw:
        card.conditions = parse_conditions(raw, gen)
    raw = ddd.get(0x0504, a)
    return parse_activity(raw, app.get("activity_len")) if raw else []


def parse_card(ddd: DddFile) -> CardData:
    card = CardData()
    card.info.generation = ddd.generation
    days: dict[dt.datetime, DailyRecord] = {}
    if ddd.get(0x0520, 0) is not None:
        for r in _parse_app(ddd, 1, card):
            days[r.date] = r
    if ddd.get(0x0520, 2) is not None:
        for r in _parse_app(ddd, 2, card):
            days[r.date] = r
    card.days = [days[k] for k in sorted(days)]
    return card


def merge_cards(cards: list[CardData]) -> CardData:
    """Führt mehrere Downloads desselben Fahrers zusammen (ältester zuerst)."""
    merged = CardData()
    days: dict[dt.datetime, DailyRecord] = {}
    seen_v, seen_e, seen_c, seen_p, seen_s = set(), set(), set(), set(), set()
    for c in cards:
        merged.info = c.info
        for d in c.days:
            days[d.date] = d
        for v in c.vehicles:
            k = (v.first_use, v.registration)
            if k not in seen_v:
                seen_v.add(k)
                merged.vehicles.append(v)
        for e in c.events:
            k = (e.type, e.begin, e.fault)
            if k not in seen_e:
                seen_e.add(k)
                merged.events.append(e)
        for x in c.controls:
            if x.time not in seen_c:
                seen_c.add(x.time)
                merged.controls.append(x)
        for p in c.places:
            k = (p.time, p.entry_type)
            if k not in seen_p:
                seen_p.add(k)
                merged.places.append(p)
        for s in c.conditions:
            k = (s.time, s.type)
            if k not in seen_s:
                seen_s.add(k)
                merged.conditions.append(s)
    merged.days = [days[k] for k in sorted(days)]
    merged.vehicles.sort(key=lambda v: v.first_use)
    merged.events.sort(key=lambda e: e.begin)
    merged.places.sort(key=lambda p: p.time)
    return merged
