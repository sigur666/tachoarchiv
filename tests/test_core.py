"""Tests der Kernlogik (ohne Qt). Ausführen: python3 -m pytest tests  oder  python3 tests/test_core.py"""
import datetime as dt
import pathlib
import re
import struct
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tachoarchiv import i18n  # noqa: E402
from tachoarchiv.analysis import Settings, analyze  # noqa: E402
from tachoarchiv.archive import Archive, DuplicateError  # noqa: E402
from tachoarchiv.ddd import DddError, DddFile  # noqa: E402
from tachoarchiv.demo import build_demo  # noqa: E402
from tachoarchiv import tachocard  # noqa: E402
from tachoarchiv.vu import parse_vu  # noqa: E402
from tachoarchiv.parser import (DRIVE, REST, WORK, ActivityChange, CardData, CardInfo,  # noqa: E402
                                ConditionRecord, DailyRecord, parse_card)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 17, 8, tzinfo=UTC)


def _demo():
    return parse_card(DddFile.parse(build_demo(NOW.date())))


def _card(plans, start=dt.datetime(2026, 9, 7, tzinfo=UTC)):
    days = []
    for i, plan in enumerate(plans):
        ch = [ActivityChange(m, 0, 0, 0, a) for m, a in plan]
        days.append(DailyRecord(start + dt.timedelta(days=i), i, 0, ch))
    c = CardData(info=CardInfo(card_number="X", last_download=NOW,
                               expiry_date=NOW + dt.timedelta(days=900)))
    c.days = days
    return c


def keys(res):
    return [f.key for f in res.findings]


def test_parse_demo():
    c = _demo()
    assert c.info.card_number == "DF00001234567000"
    assert c.info.surname == "Demo-Mustermann"
    assert len(c.days) == 38 and len(c.vehicles) == 1 and len(c.events) == 1


def test_demo_findings():
    k = keys(analyze(_demo(), Settings(now=NOW)))
    for expected in ("v_break", "v_daily_drive_ext", "v_daily_rest", "v_daily_drive",
                     "w_download_due", "w_card_expiry"):
        assert expected in k, expected


def test_split_break_is_valid():
    plan = [(0, REST), (360, DRIVE), (570, REST), (585, DRIVE), (645, REST), (675, DRIVE), (855, REST)]
    assert "v_break" not in keys(analyze(_card([plan, [(0, REST)]]), Settings(now=NOW)))


def test_split_break_wrong_order():
    plan = [(0, REST), (360, DRIVE), (570, REST), (600, DRIVE), (645, REST), (660, DRIVE), (855, REST)]
    assert "v_break" in keys(analyze(_card([plan, [(0, REST)]]), Settings(now=NOW)))


def test_weekly_driving_limit():
    long_day = [(0, REST), (240, DRIVE), (510, REST), (555, DRIVE), (825, REST), (870, DRIVE),
                (930, REST)]
    plans = [long_day] * 6 + [[(0, REST)]] * 2
    res = analyze(_card(plans), Settings(now=NOW))
    assert "v_weekly_drive" in keys(res)          # 6 x 10 h = 60 h
    assert "v_weekly_rest_late" not in keys(res)


def test_reduced_rest_count():
    # Arbeit bis 20:00, Beginn 05:00 -> 9 h Ruhe: viermal reduziert
    day = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (840, REST),
           (885, WORK), (1200, REST)]
    res = analyze(_card([day] * 5 + [[(0, REST)]] * 2), Settings(now=NOW, check_arbzg=False))
    assert keys(res).count("v_reduced_count") == 1


def test_arbzg_breaks():
    day = [(0, REST), (360, WORK), (720, DRIVE), (780, REST), (1200, REST)]
    k = keys(analyze(_card([day, [(0, REST)]]), Settings(now=NOW)))
    assert "v_arbzg_6h" in k and "v_arbzg_breaks" in k
    k2 = keys(analyze(_card([day, [(0, REST)]]), Settings(now=NOW, check_arbzg=False)))
    assert "v_arbzg_6h" not in k2


# --------------------------------------------------------------- Fähre / Eisenbahn

FERRY_START = dt.datetime(2026, 9, 7, tzinfo=UTC)
FERRY_DAY = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (810, WORK),
             (840, REST), (1200, WORK), (1220, REST), (1380, WORK), (1400, REST)]
FERRY_DAY3 = FERRY_DAY[:-2] + [(1380, WORK), (1395, REST), (1410, WORK), (1425, REST)]
FERRY_NEXT = [(0, REST), (360, DRIVE), (600, WORK), (615, REST), (660, DRIVE), (900, REST)]


def _mark(card, day, minute, typ=3):
    card.conditions.append(
        ConditionRecord(FERRY_START + dt.timedelta(days=day, minutes=minute), typ))
    card.conditions.sort(key=lambda c: c.time)
    return card


def test_ferry_interrupted_rest_allowed():
    """Art. 9 Abs. 1: zweimal unterbrochene regelmäßige Tagesruhe bleibt gültig."""
    card = _mark(_card([FERRY_DAY, FERRY_NEXT, [(0, REST)]], FERRY_START), 0, 1140)
    k = keys(analyze(card, Settings(now=NOW, check_arbzg=False)))
    assert "i_ferry_rest" in k
    assert "v_daily_rest" not in k
    assert "v_ferry_limit" not in k


def test_ferry_without_marker_breaks_rest():
    """Ohne Kennzeichnung der Überfahrt gilt die Ruhezeit als unterbrochen."""
    card = _card([FERRY_DAY, FERRY_NEXT, [(0, REST)]], FERRY_START)
    assert "v_daily_rest" in keys(analyze(card, Settings(now=NOW, check_arbzg=False)))
    marked = _mark(_card([FERRY_DAY, FERRY_NEXT, [(0, REST)]], FERRY_START), 0, 1140)
    assert "v_daily_rest" in keys(analyze(marked, Settings(now=NOW, check_arbzg=False,
                                                          ferry_rule=False)))


def test_ferry_three_interruptions():
    card = _mark(_card([FERRY_DAY3, FERRY_NEXT, [(0, REST)]], FERRY_START), 0, 1140)
    k = keys(analyze(card, Settings(now=NOW, check_arbzg=False)))
    assert "v_ferry_limit" in k and "i_ferry_rest" not in k


def test_ferry_reduced_daily_rest_not_covered():
    """Nur die regelmäßige Tagesruhe (11 h) darf unterbrochen werden."""
    short = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (840, WORK),
             (1200, REST), (1290, WORK), (1310, REST)]
    nxt = [(0, REST), (330, DRIVE), (570, WORK), (600, REST)]
    card = _mark(_card([short, nxt, [(0, REST)]], FERRY_START), 0, 1260)
    k = keys(analyze(card, Settings(now=NOW, check_arbzg=False)))
    assert "v_ferry_reduced" in k and "i_ferry_rest" not in k


def test_ferry_weekly_rest_needs_eight_hours():
    """Art. 9 Abs. 1 UAbs. 2: regelmäßige Wochenruhe nur bei Überfahrt ab 8 h."""
    work = [(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE), (810, WORK), (840, REST)]
    cut = [(0, REST), (600, WORK), (620, REST)]
    back = [(0, REST), (720, DRIVE), (960, REST)]
    plans = [work, cut, [(0, REST)], back]
    short = _mark(_mark(_card(plans, FERRY_START), 1, 480), 1, 720, typ=4)      # 4 h Überfahrt
    k = keys(analyze(short, Settings(now=NOW, check_arbzg=False)))
    assert "v_ferry_weekly_short" in k
    long = _mark(_mark(_card(plans, FERRY_START), 1, 240), 1, 900, typ=4)       # 11 h Überfahrt
    assert "v_ferry_weekly_short" not in keys(analyze(long, Settings(now=NOW, check_arbzg=False)))


def test_ferry_end_estimated():
    card = _mark(_card([FERRY_DAY, FERRY_NEXT, [(0, REST)]], FERRY_START), 0, 1140)
    res = analyze(card, Settings(now=NOW, check_arbzg=False))
    assert len(res.crossings) == 1 and res.crossings[0].estimated
    assert res.crossings[0].end == FERRY_START + dt.timedelta(days=1, minutes=360)
    assert "i_ferry_open" in keys(res)


# --------------------------------------------------------------- Fahrzeug-Download

def _tr4(t):
    return struct.pack(">I", int(t.timestamp()))


def _vu_gen1(vin="WDB96340310L123456", plate="L-TA 2026", locks=1, controls=2, days=3):
    now = NOW
    head = bytearray()
    head += bytes(range(256)) * 2                      # zwei "Zertifikate" (2 x 194)
    head = bytearray(bytes(head)[:388])
    head += vin.encode("ascii").ljust(17, b" ")[:17]
    head += bytes([13]) + bytes([1]) + plate.encode("iso8859_1").ljust(13, b" ")[:13]
    head += _tr4(now) + _tr4(now - dt.timedelta(days=60)) + _tr4(now)
    head += bytes([3])                                 # Kartenschaechte
    head += _tr4(now) + bytes([2, 13]) + b"DF00001234567000"
    head += bytes([1]) + b"Muster Spedition GmbH".ljust(35, b" ")
    head += bytes([locks]) + bytes(98 * locks)
    head += bytes([controls]) + bytes(31 * controls)
    head += bytes(128)                                 # Signatur
    raw = b"\x76\x01" + bytes(head)
    for i in range(days):                              # Aktivitaeten je Tag
        raw += b"\x76\x02" + bytes(200) + bytes(128)
    raw += b"\x76\x03" + bytes(300) + bytes(128)
    raw += b"\x76\x04" + bytes(500) + bytes(128)
    raw += b"\x76\x05" + bytes(250) + bytes(128)
    return raw


def _array(rtype, records):
    size = len(records[0]) if records else 0
    return bytes([rtype]) + struct.pack(">HH", size, len(records)) + b"".join(records)


def _vu_gen2(vin="WDB96340310L654321", plate="L-TA 2030", v2=False, days=2):
    now = NOW
    base = 0x31 if v2 else 0x21
    head = (_array(1, [bytes(204)]) + _array(2, [bytes(204)])
            + _array(3, [vin.encode("ascii").ljust(17, b" ")[:17]])
            + _array(4, [bytes([13, 1]) + plate.encode("iso8859_1").ljust(13, b" ")[:13]])
            + _array(5, [_tr4(now)])
            + _array(6, [_tr4(now - dt.timedelta(days=90)) + _tr4(now)])
            + _array(7, [bytes([3])])
            + _array(8, [_tr4(now) + bytes([2, 13]) + b"DF00001234567000" + bytes([2])
                         + bytes([1]) + b"Muster Spedition GmbH".ljust(35, b" ")])
            + _array(9, [bytes(98)]) + _array(10, [bytes(31)])
            + _array(11, [bytes(64)]))                 # Signatur
    raw = bytes([0x76, base]) + head
    for _ in range(days):
        raw += bytes([0x76, base + 1]) + _array(20, [bytes(100)]) + _array(11, [bytes(64)])
    raw += bytes([0x76, base + 2]) + _array(30, [bytes(80)]) + _array(11, [bytes(64)])
    raw += bytes([0x76, base + 4]) + _array(40, [bytes(60)]) + _array(11, [bytes(64)])
    return raw


def test_vu_gen1_header():
    vf, info = parse_vu(_vu_gen1())
    assert info.vin == "WDB96340310L123456"[:17]
    assert info.nation == "D" and info.registration == "L-TA 2026"
    assert info.company == "Muster Spedition GmbH"
    assert info.card_number == "DF00001234567000"
    assert info.generation == 1 and info.days == 3
    assert [t for t, _ in vf.blocks] == [1, 2, 2, 2, 3, 4, 5]


def test_vu_gen2_header_and_blocks():
    vf, info = parse_vu(_vu_gen2())
    assert info.generation == 2 and info.version == 1
    assert info.vin == "WDB96340310L654321"[:17]
    assert info.registration == "L-TA 2030" and info.days == 2
    assert [t for t, _ in vf.blocks] == [0x21, 0x22, 0x22, 0x23, 0x25]


def test_vu_gen2_v2_detected():
    _, info = parse_vu(_vu_gen2(v2=True))
    assert info.generation == 2 and info.version == 2


def test_vu_blocks_exact_for_gen2():
    """Die Satzfelder tragen ihre Laenge – die Grenzen duerfen nicht geraten werden."""
    raw = _vu_gen2(days=4)
    vf, _ = parse_vu(raw)
    assert sum(len(d) + 2 for _, d in vf.blocks) == len(raw)


def test_vu_archive_roundtrip():
    raw = _vu_gen1()
    with tempfile.TemporaryDirectory() as d:
        a = Archive(d)
        dl, info = a.add_any(raw, "file", "M_0001.DDD")
        assert dl.path.exists() and not (dl.path.stat().st_mode & 0o222)
        assert dl.path.read_bytes() == raw                 # unveraendert
        assert info.registration == "L-TA 2026"
        try:
            a.add_any(raw, "file")
            raise AssertionError("Duplikat nicht erkannt")
        except DuplicateError:
            pass
        v = a.vehicles()
        assert len(v) == 1 and v[0]["count"] == 1 and v[0]["registration"] == "L-TA 2026"
        assert a.verify() == {f"v{dl.id}": True}


def test_archive_keeps_cards_and_vehicles_apart():
    with tempfile.TemporaryDirectory() as d:
        a = Archive(d)
        a.add_any(build_demo(NOW.date()), "file", "karte.ddd")
        a.add_any(_vu_gen2(), "file", "fahrzeug.ddd")
        assert len(a.drivers()) == 1 and len(a.vehicles()) == 1
        assert len(a.downloads()) == 1 and len(a.vu_downloads()) == 1
        assert len(a.verify()) == 2


def test_vu_header_unreadable_still_archived():
    """Kopfdaten kaputt: Die Datei muss trotzdem aufbewahrt werden."""
    raw = b"\x76\x01" + bytes(300)
    with tempfile.TemporaryDirectory() as d:
        dl, info = Archive(d).add_any(raw, "file", "defekt.ddd")
        assert dl.path.read_bytes() == raw and dl.vin == "unbekannt"


# --------------------------------------------------------------- Nachweiszeitraum

def _span(days_ago: int, days: int):
    """Karte mit `days` aufgezeichneten Tagen, beginnend vor `days_ago` Tagen (0:00 Uhr)."""
    start = (NOW - dt.timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _card([[(0, REST), (300, WORK), (315, DRIVE), (555, REST), (600, DRIVE),
                   (810, WORK), (840, REST)]] * days, start)


def test_coverage_complete():
    card = _span(60, 60)
    assert "w_coverage" not in keys(analyze(card, Settings(now=NOW, check_arbzg=False)))


def test_coverage_incomplete():
    card = _span(20, 20)
    f = [x for x in analyze(card, Settings(now=NOW, check_arbzg=False)).findings
         if x.key == "w_coverage"]
    assert len(f) == 1 and f[0].params["days"] == 56
    assert f[0].params["count"] == 56 - 20          # 20 Tage vorhanden, Rest fehlt


def test_coverage_days_configurable():
    card = _span(30, 30)
    st = Settings(now=NOW, check_arbzg=False, coverage_days=28)
    assert "w_coverage" not in keys(analyze(card, st))
    assert "w_coverage" in keys(analyze(card, Settings(now=NOW, check_arbzg=False)))


def test_coverage_can_be_switched_off():
    card = _span(5, 5)
    st = Settings(now=NOW, check_arbzg=False, check_coverage=False)
    assert "w_coverage" not in keys(analyze(card, st))


def test_coverage_helper():
    from tachoarchiv.analysis import coverage
    start = NOW - dt.timedelta(days=10)
    covered, total, first = coverage(start, NOW, NOW, 56)
    assert (covered, total, first) == (10, 56, start.date())   # ohne den laufenden Tag
    assert coverage(None, None, NOW, 56) == (0, 56, None)
    old_end = NOW - dt.timedelta(days=100)
    assert coverage(old_end - dt.timedelta(days=5), old_end, NOW, 56)[0] == 0


# --------------------------------------------------------------- Kartenzugriff (ohne Hardware)

class FakeCard:
    """Karte, die nur bestimmte P2-Werte akzeptiert – bildet reale Eigenheiten nach."""

    def __init__(self, select_p2=(0x0C,), mf=True):
        self.select_p2 = select_p2
        self.mf = mf
        self.sent = []

    def transmit(self, apdu):
        self.sent.append(apdu.hex().upper())
        ins, p1, p2 = apdu[1], apdu[2], apdu[3]
        if ins == 0xA4:
            if p2 not in self.select_p2:
                return b"", 0x6A86              # falsche Parameter P1/P2
            if (p1 == 0x00 or (p1 == 0x04 and len(apdu) < 6)) and not self.mf:
                return b"", 0x6A82              # Stammverzeichnis nicht waehlbar
            return b"", 0x9000
        if ins == 0xB0:
            return bytes(16), 0x6282            # Dateiende
        if ins == 0x2A:
            return bytes(128), 0x9000
        return b"", 0x6D00

    def begin(self):
        pass

    def end(self):
        pass

    def atr(self):
        return bytes.fromhex("3B00")

    @property
    def protocol(self):
        return "T=1"


def test_select_mf_accepts_other_p2():
    card = FakeCard(select_p2=(0x00,))
    assert tachocard.select_mf(card) == 0x9000
    assert card.sent[0].startswith("00A4000C")          # erst die Form aus der Vorschrift
    assert card.sent[1].startswith("00A40000")          # dann die Alternative


def test_select_ef_reports_card_error():
    card = FakeCard(select_p2=())
    try:
        tachocard.select_ef(card, 0x0520)
        raise AssertionError("kein Fehler gemeldet")
    except tachocard.CardError as e:
        assert e.sw == 0x6A86


def test_download_without_selectable_mf():
    """Auch wenn das Stammverzeichnis nicht waehlbar ist, muss der Download laufen."""
    card = FakeCard(select_p2=(0x0C,), mf=False)
    raw, warn = tachocard.download_card(card)
    assert raw and any(n.severity == "info" for n in warn)
    assert DddFile.parse(raw).get(0x0520, 0) is not None


class AlcorGen2Card(FakeCard):
    """Karte der 2. Generation (Alcor Micro AU9540, T=1): MF nie waehlbar (6A86),
    Auswahl nur mit P2=0C, EF unter dem Stammverzeichnis nicht vorhanden."""

    def transmit(self, apdu):
        self.sent.append(apdu.hex().upper())
        ins, p1, p2 = apdu[1], apdu[2], apdu[3]
        if ins == 0xA4:
            if p2 != 0x0C:
                return b"", 0x6A86
            if p1 == 0x00 or (p1 == 0x04 and len(apdu) < 6):
                return b"", 0x6A86              # Stammverzeichnis in keiner Form
            if p1 == 0x02 and apdu[5:7] in (b"\x00\x02", b"\x00\x05"):
                return b"", 0x6A82              # EF_ICC/EF_IC nur unter dem MF
            return b"", 0x9000
        if ins == 0xB0:
            return bytes(16), 0x6282
        if ins == 0x2A:
            return bytes(128 if apdu[2] == 0x9E else 0), 0x9000
        return b"", 0x6D00


class StrictLengthCard(FakeCard):
    """Karte, die mehr Bytes als vorhanden mit 6700 ablehnt, statt weniger zu liefern."""

    def __init__(self, sizes, sig_le=0x80):
        super().__init__(select_p2=(0x0C,), mf=False)
        self.sizes = sizes
        self.sig_le = sig_le
        self.content = {f: bytes((i + 1) % 251 for i in range(n)) for f, n in sizes.items()}
        self.cur = None

    def transmit(self, apdu):
        self.sent.append(apdu.hex().upper())
        ins, p1, p2 = apdu[1], apdu[2], apdu[3]
        if ins == 0xA4:
            if p2 != 0x0C:
                return b"", 0x6A86
            if p1 == 0x02:
                fid = (apdu[5] << 8) | apdu[6]
                if fid not in self.content:
                    return b"", 0x6A82
                self.cur = fid
                return b"", 0x9000
            if p1 == 0x04 and len(apdu) >= 6:
                return b"", 0x9000
            return b"", 0x6A86
        if ins == 0xB0:
            if self.cur is None:
                return b"", 0x6986
            body = self.content[self.cur]
            off = (p1 << 8) | p2
            want = apdu[4] or 256
            if off >= len(body):
                return b"", 0x6B00
            if want > len(body) - off:
                return b"", 0x6700              # strenge Laengenpruefung
            return body[off:off + want], 0x9000
        if ins == 0x2A:
            if apdu[2] != 0x9E:                 # PERFORM HASH OF FILE
                self.hashed = True
                return b"", 0x9000
            if apdu[4] != self.sig_le:          # strenge Laengenpruefung
                return b"", 0x6700
            if not getattr(self, "hashed", False):
                return b"", 0x6985              # Signatur ohne vorherigen Hash
            self.hashed = False
            return bytes(self.sig_le), 0x9000
        return b"", 0x6D00


def test_signature_length_is_probed():
    """Gen2-Karten liefern je nach Kurve 64, 96 oder 132 Byte Signatur."""
    for le in (0x40, 0x60, 0x84, 0x80):
        card = StrictLengthCard({0x0501: 10}, sig_le=le)
        tachocard.select_ef(card, 0x0501)
        card.transmit(tachocard.HASH_APDU)
        assert len(tachocard.read_signature(card, 0x0501, 2)) == le, hex(le)


def test_download_with_unusual_signature_length():
    card = StrictLengthCard({0x0501: 10, 0x0520: 143, 0x0504: 900}, sig_le=0x40)
    raw, warn = tachocard.download_card(card)
    ddd = DddFile.parse(raw)
    assert len(ddd.get(0x0501, 3)) == 64          # Anhang 3 = Signatur der 2. Generation
    assert not [n for n in warn if "SIGNATURE" in n.text]


def test_download_survives_missing_signature():
    """Ohne brauchbare Signatur werden die Nutzdaten trotzdem archiviert."""
    card = StrictLengthCard({0x0501: 10, 0x0520: 143}, sig_le=0x11)
    raw, warn = tachocard.download_card(card)
    assert DddFile.parse(raw).get(0x0520, 2) is not None
    assert [n for n in warn if "SIGNATURE" in n.text and n.severity == "warning"]


def test_read_all_handles_strict_length():
    for size in (10, 143, 200, 201, 1234, 13776):
        card = StrictLengthCard({0x0501: size})
        tachocard.select_ef(card, 0x0501)
        assert tachocard.read_all(card) == card.content[0x0501], size


def test_download_card_with_strict_length():
    """Die erste Datei ist nur 10 Byte lang – genau hier scheiterte der Download."""
    sizes = {0x0501: 10, 0xC100: 194, 0xC108: 194, 0x0520: 143, 0x050E: 4,
             0x0521: 53, 0x0504: 13776, 0x0505: 2606, 0x0506: 841, 0x0502: 864,
             0x0503: 576, 0x0507: 19, 0x0508: 46, 0x0522: 280}
    card = StrictLengthCard(sizes)
    raw, warn = tachocard.download_card(card)
    ddd = DddFile.parse(raw)
    assert len(ddd.get(0x0501, 0)) == 10
    assert len(ddd.get(0x0504, 0)) == 13776
    assert not [n for n in warn if "READ BINARY" in n.text]


def test_unreadable_file_does_not_abort_download():
    """Eine Datei mit 6982 (Sicherheitsbedingung) darf den Download nicht beenden."""
    card = StrictLengthCard({0x0501: 10, 0x0520: 143, 0x0504: 900})
    blocked = {0x0504}
    inner = card.transmit

    def guard(apdu):
        if apdu[1] == 0xB0 and card.cur in blocked:
            return b"", 0x6982
        return inner(apdu)

    card.transmit = guard
    raw, warn = tachocard.download_card(card)
    ddd = DddFile.parse(raw)
    assert ddd.get(0x0520, 2) is not None            # die uebrigen Dateien sind da
    assert ddd.get(0x0504, 2) is None
    note = [n for n in warn if "0504" in n.text and "6982" in n.text]
    assert note and note[0].severity == "info"       # kein Fehler, nur nicht zugaenglich


def test_vu_configuration_not_requested():
    """EF_VU_Configuration (0540) gehoert nicht zum Download-Datensatz."""
    from tachoarchiv.ddd import G2_FILES
    assert 0x0540 not in [f for f, _, _ in G2_FILES]


def test_card_type_in_diagnosis():
    card = StrictLengthCard({0x0501: 10})
    card.content[0x0501] = bytes([4]) + bytes(9)     # Unternehmenskarte
    assert "Unternehmenskarte" in tachocard.probe(card)[-1]


def test_download_alcor_gen2_card():
    card = AlcorGen2Card()
    raw, warn = tachocard.download_card(card)
    ddd = DddFile.parse(raw)
    assert ddd.generation == 2
    assert ddd.get(0x0520, 0) is not None and ddd.get(0x0520, 2) is not None
    assert len([n for n in warn if n.severity == "info"]) == 1   # genau ein MF-Hinweis
    assert not [n for n in warn if "0002" in n.text or "0005" in n.text]


def test_archive_roundtrip():
    raw = build_demo(NOW.date())
    with tempfile.TemporaryDirectory() as d:
        a = Archive(d)
        dl, _ = a.add(raw, "file", "demo.ddd")
        assert dl.path.exists() and not (dl.path.stat().st_mode & 0o222)
        try:
            a.add(raw, "file")
            raise AssertionError("duplicate not detected")
        except DuplicateError:
            pass
        assert a.verify() == {f"c{dl.id}": True}
        assert len(a.load_driver(dl.card_number).days) == 38


def test_vu_file_rejected():
    try:
        DddFile.parse(b"\x76\x01\x00\x00")
        raise AssertionError
    except DddError as e:
        assert str(e) == "vu_file"


def test_translations_complete():
    root = pathlib.Path(__file__).resolve().parents[1] / "tachoarchiv"
    used = set()
    for f in root.glob("*.py"):
        used |= set(re.findall(r'tr\(\s*"([a-z0-9_]+)"', f.read_text()))
        used |= set(re.findall(r'\("((?:period|col|f|tab|act)_[a-z0-9_]+)"', f.read_text()))
        used |= set(re.findall(r'Finding\("([a-z0-9_]+)"', f.read_text()))
    used |= {f"sev_{s}" for s in ("violation", "warning", "info")}
    used |= {"ev_other", "ev_sec", "ev_fault_vu", "ev_fault_card"} | {f"ev_{i}" for i in range(1, 11)}
    used = {u for u in used if not u.endswith("_")}
    base = set(i18n.TR["de"])
    for lang, table in i18n.TR.items():
        missing = used - set(table)
        assert not missing, (lang, missing)
        assert set(table) == base, (lang, base ^ set(table))
    for lang in i18n.TR:
        i18n.set_language(lang)
        for f in analyze(_demo(), Settings(now=NOW)).findings:
            assert i18n.fmt_finding(f)
        for k in base:
            i18n.tr(k) if "{" not in i18n.TR[lang][k] else None
    i18n.set_language("de")


def test_locale_files_match():
    """Jede Sprachdatei: gleiche Schluessel und gleiche Platzhalter wie Deutsch."""
    import json
    root = pathlib.Path(__file__).resolve().parents[1] / "tachoarchiv" / "locale"
    files = sorted(root.glob("*.json"))
    assert len(files) == len(i18n.LANGUAGES), [f.stem for f in files]
    de = json.loads((root / "de.json").read_text(encoding="utf-8"))
    holes = {k: set(re.findall(r"\{(\w+)\}", v)) for k, v in de.items()}
    for f in files:
        assert f.stem in i18n.LANGUAGES, f.stem
        table = json.loads(f.read_text(encoding="utf-8"))
        assert set(table) == set(de), (f.stem, set(de) ^ set(table))
        for k, v in table.items():
            assert set(re.findall(r"\{(\w+)\}", v)) == holes[k], (f.stem, k)
            assert v.strip(), (f.stem, k)


def test_serbian_transliteration():
    """sr-latn wird aus sr gerechnet – beide muessen deckungsgleich bleiben."""
    import json
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    from sr_latn import transliterate
    root = pathlib.Path(__file__).resolve().parents[1] / "tachoarchiv" / "locale"
    cyr = json.loads((root / "sr.json").read_text(encoding="utf-8"))
    lat = json.loads((root / "sr-latn.json").read_text(encoding="utf-8"))
    for k, v in cyr.items():
        expected = v if k == "date_fmt" else transliterate(v)
        assert lat[k] == expected, k
    assert transliterate("ИЗМЕЊЕНО") == "IZMENJENO"      # Digraph in Grossschreibung
    assert transliterate("Њива") == "Njiva"
    assert transliterate("VO (EG) 561/2006 {value}") == "VO (EG) 561/2006 {value}"


def test_rtl_languages():
    assert i18n.is_rtl("ar") and i18n.is_rtl("ur")
    assert not i18n.is_rtl("de") and not i18n.is_rtl("pa") and not i18n.is_rtl("hi")


def _speed_body(start: dt.datetime, minutes: list[list[int]], gen: int) -> bytes:
    """Baut einen Geschwindigkeitsblock, wie ihn das Fahrzeuggerät liefert."""
    recs = b""
    for n, speeds in enumerate(minutes):
        ts = int((start + dt.timedelta(minutes=n)).timestamp())
        recs += struct.pack(">I", ts) + bytes(speeds)
    if gen == 1:
        return struct.pack(">H", len(minutes)) + recs + b"\x00" * 128      # + Signatur
    head = struct.pack(">BHH", 0x01, 64, len(minutes))
    sig = struct.pack(">BHH", 0x02, 64, 1) + b"\x00" * 64
    return head + recs + sig


def test_speed_parsing_and_overspeed():
    """Geschwindigkeitsblöcke beider Generationen, Abschnitte über dem Grenzwert."""
    from tachoarchiv.vu import VuFile, overspeed, parse_speed, speed_series, speed_stats
    start = dt.datetime(2026, 9, 16, 8, 0, tzinfo=dt.timezone.utc)
    minutes = [
        [80] * 60,                                  # unter der Grenze
        [95] * 30 + [80] * 30,                      # 30 s darüber
        [80] * 20 + [92] * 10 + [80] * 2 + [93] * 8 + [80] * 20,   # mit kurzer Unterbrechung
    ]
    for gen, trep in ((1, 0x04), (2, 0x24), (2, 0x34)):
        blocks = parse_speed(VuFile([(trep, _speed_body(start, minutes, gen))]))
        assert len(blocks) == 3, (gen, trep, len(blocks))
        assert blocks[0].start == start and blocks[0].speeds[0] == 80
        series = speed_series(blocks, start.date())
        assert series[8 * 3600] == 80 and series[0] == -1        # außerhalb: nicht aufgezeichnet
        st = speed_stats(blocks, start.date(), 90)
        assert st["peak"] == 95 and st["recorded"] == 180
        assert st["over"] == 30 + 18
        over = overspeed(blocks, start.date(), 90)
        # Der Ausreißer mit 2 s Pause gilt als ein Abschnitt, nicht als zwei
        assert len(over) == 2, [(o.start, o.seconds) for o in over]
        assert over[0].seconds == 30 and over[0].peak == 95
        assert over[1].seconds == 20 and over[1].peak == 93


def test_speed_rejects_nonsense():
    """Unglaubwürdige Sätze liefern lieber nichts als eine erfundene Kurve."""
    from tachoarchiv.vu import VuFile, parse_speed
    junk = struct.pack(">H", 9999) + b"\xAA" * 300
    assert parse_speed(VuFile([(0x04, junk)])) == []
    start = dt.datetime(2026, 9, 16, 8, 0, tzinfo=dt.timezone.utc)
    old = dt.datetime(1998, 5, 1, tzinfo=dt.timezone.utc)        # vor der Epoche des Formats
    assert parse_speed(VuFile([(0x04, _speed_body(old, [[80] * 60], 1))])) == []
    # 0xFF heisst "kein Wert", nicht "255 km/h"
    blocks = parse_speed(VuFile([(0x04, _speed_body(start, [[0xFF] * 60], 1))]))
    assert blocks and set(blocks[0].speeds) == {-1}


def test_archive_protection_round_trip():
    """Schutz ein, Daten verschlüsselt und trotzdem auswertbar, Schutz wieder aus."""
    from tachoarchiv.archive import DB_ENC, DB_PLAIN
    from tachoarchiv.vault import LockedError, Vault, WrongSecret
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        arc = Archive(base)
        dl, _ = arc.add(build_demo(), "file", "demo.ddd")
        assert not dl.path.read_bytes().startswith(b"TAV1")
        recovery = arc.protect("geheim1234")
        enc = arc.downloads()[0].path
        assert enc.read_bytes().startswith(b"TAV1")
        # Name und Ordner duerfen nichts mehr verraten
        assert "Demo" not in enc.name and dl.card_number not in str(enc)
        assert not (base / DB_PLAIN).exists() and (base / DB_ENC).exists()
        assert arc.load_driver(dl.card_number).days          # weiterhin auswertbar
        assert all(arc.verify().values())
        arc.close()

        arc2 = Archive(base, Vault(base))                    # neue Sitzung: gesperrt
        try:
            arc2.drivers()
            raise AssertionError("gesperrtes Archiv muss sich sperren")
        except LockedError:
            pass
        try:
            arc2.unlock("falsches Passwort")
            raise AssertionError("falsches Passwort darf nicht oeffnen")
        except WrongSecret:
            pass
        arc2.unlock(recovery.lower().replace("-", ""))       # tolerant geschrieben
        assert len(arc2.drivers()) == 1
        arc2.lock()
        arc2.unlock("geheim1234")
        assert all(arc2.verify().values())
        arc2.unprotect()
        plain = arc2.downloads()[0].path
        assert not plain.read_bytes().startswith(b"TAV1")
        assert (base / DB_PLAIN).exists() and not (base / DB_ENC).exists()
        assert all(arc2.verify().values())


def test_report_marks_days_with_findings():
    """Tage mit Verstoss/Warnung werden im Bericht hinterlegt – und beschriftet."""
    from tachoarchiv.report import SEV_TINT, build_html, day_marks
    now = dt.datetime(2026, 9, 24, 8, tzinfo=dt.timezone.utc)
    card = parse_card(DddFile.parse(build_demo(now.date())))
    res = analyze(card, Settings(now=now))
    marks = day_marks(res.findings)
    assert marks, "Demodaten muessen Befunde enthalten"
    for day, (sev, text) in marks.items():
        assert sev in SEV_TINT and text
        # Der schwerere Befund bestimmt die Farbe.
        if any(f.severity == "violation" for f in res.findings if f.time.date() == day):
            assert sev == "violation"
    # Hinweise allein faerben nicht.
    info_only = {f.time.date() for f in res.findings if f.severity == "info"} - set(marks)
    html = build_html(card, res, None, "28 Tage")
    assert SEV_TINT["violation"] in html
    for day in info_only:
        assert f"⚠ {day.strftime('%d.%m.%Y')}" not in html


# --------------------------------------------------------------- Signaturpruefung

def _rsa_key():
    """1024-Bit-Schluessel wie in Anlage 11 (dort 1024 Bit, SHA-1)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    n = k.private_numbers().public_numbers.n
    return k, n, 65537


def _sign_raw(priv, x: bytes) -> bytes:
    """Rohe RSA-Operation ohne Polsterung – Anlage 11 polstert selbst (ISO 9796-2)."""
    d = priv.private_numbers().d
    n = priv.private_numbers().public_numbers.n
    return pow(int.from_bytes(x, "big"), d, n).to_bytes(128, "big")


def _wrap(priv, message: bytes, recovered: bytes) -> bytes:
    import hashlib
    x = b"\x6a" + recovered.ljust(106, b"\x00")[:106] + hashlib.sha1(message).digest() + b"\xbc"
    return _sign_raw(priv, x)


def _certificate(priv_issuer, car: bytes, chr_: bytes, n: int, e: int) -> bytes:
    content = (b"\x01" + car + b"\x00" * 7 + b"\x00" * 4 + chr_
               + n.to_bytes(128, "big") + e.to_bytes(8, "big"))
    assert len(content) == 164, len(content)
    return _wrap(priv_issuer, content, content[:106]) + content[106:] + car


def test_signature_chain_verifies():
    """Wurzel -> Mitgliedstaat -> Karte -> Datei, einmal ganz durchgerechnet."""
    from tachoarchiv.ddd import DddFile
    from tachoarchiv.signature import (FAILED, NO_ROOT, OK, Gen1Key, RootStore,
                                       parse_gen1_certificate, summary, verify_card,
                                       verify_gen1_data)
    root_priv, root_n, root_e = _rsa_key()
    ca_priv, ca_n, ca_e = _rsa_key()
    card_priv, card_n, card_e = _rsa_key()
    root_chr = b"ERCA0001"
    ca_cert = _certificate(root_priv, root_chr, b"MSCA0001", ca_n, ca_e)
    card_cert = _certificate(ca_priv, b"MSCA0001", b"CARD0001", card_n, card_e)

    root = Gen1Key(root_chr, root_n, root_e)
    ca_key = parse_gen1_certificate(ca_cert, root)
    assert ca_key is not None and ca_key.n == ca_n
    card_key = parse_gen1_certificate(card_cert, ca_key)
    assert card_key is not None and card_key.n == card_n
    # Falscher Aussteller darf nicht durchgehen
    assert parse_gen1_certificate(card_cert, root) is None

    data = bytes(range(256)) * 3
    sig = _wrap(card_priv, data, data[:106])
    assert verify_gen1_data(data, sig, card_key).state == OK
    assert verify_gen1_data(data + b"x", sig, card_key).state == FAILED

    # Jetzt dasselbe durch die ganze Datei hindurch
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp) / "erca"
        folder.mkdir()
        (folder / "erca_gen1.bin").write_bytes(
            root_chr + root_n.to_bytes(128, "big") + root_e.to_bytes(8, "big"))
        ddd = DddFile.parse(build_demo())
        ddd.entries = [(f, a, d) for f, a, d in ddd.entries if f not in (0xC100, 0xC108)]
        ddd.add(0xC100, 0, card_cert)
        ddd.add(0xC108, 0, ca_cert)
        signed = []
        for fid, app, payload in ddd.entries:
            if app == 0 and fid not in (0xC100, 0xC108, 0x0002, 0x0005):
                signed.append((fid, payload))
        ddd.entries = [(f, a, d) for f, a, d in ddd.entries if a != 1]
        for fid, payload in signed:
            ddd.add(fid, 1, _wrap(card_priv, payload, payload[:106]))
        states = verify_card(ddd, RootStore(folder))
        assert states and all(s.state == OK for s in states.values()), \
            {hex(k): v.state for k, v in states.items() if v.state != OK}
        assert summary(states).state == OK

        # Ohne Wurzelschluessel wird nichts behauptet
        leer = RootStore(pathlib.Path(tmp) / "fehlt")
        assert leer.empty
        states = verify_card(ddd, leer)
        assert all(s.state == NO_ROOT for s in states.values())
        assert summary(states).state == NO_ROOT


def test_signature_detects_tampering():
    """Eine veraenderte Datei faellt auf, ein veraendertes Zertifikat auch."""
    from tachoarchiv.ddd import DddFile
    from tachoarchiv.signature import FAILED, OK, Gen1Key, RootStore, summary, verify_card
    root_priv, root_n, root_e = _rsa_key()
    ca_priv, ca_n, ca_e = _rsa_key()
    card_priv, card_n, card_e = _rsa_key()
    root_chr = b"ERCA0001"
    ca_cert = _certificate(root_priv, root_chr, b"MSCA0001", ca_n, ca_e)
    card_cert = _certificate(ca_priv, b"MSCA0001", b"CARD0001", card_n, card_e)
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp) / "erca"
        folder.mkdir()
        (folder / "root.bin").write_bytes(
            root_chr + root_n.to_bytes(128, "big") + root_e.to_bytes(8, "big"))
        roots = RootStore(folder)

        def build(mangle=None):
            ddd = DddFile.parse(build_demo())
            ddd.entries = [(f, a, d) for f, a, d in ddd.entries
                           if f not in (0xC100, 0xC108) and a != 1]
            ddd.add(0xC100, 0, card_cert)
            ddd.add(0xC108, 0, ca_cert)
            for fid, app, payload in list(ddd.entries):
                if app == 0 and fid not in (0xC100, 0xC108, 0x0002, 0x0005):
                    ddd.add(fid, 1, _wrap(card_priv, payload, payload[:106]))
            if mangle:
                mangle(ddd)
            return ddd

        def flip(ddd):
            for i, (fid, app, payload) in enumerate(ddd.entries):
                if fid == 0x0504 and app == 0:
                    ddd.entries[i] = (fid, app, payload[:-1] + bytes([payload[-1] ^ 0x01]))

        states = verify_card(build(flip), roots)
        assert states[0x0504].state == FAILED
        assert summary(states).state == FAILED

        fremd_priv, fremd_n, fremd_e = _rsa_key()
        fremd_cert = _certificate(fremd_priv, b"MSCA0001", b"CARD0001", card_n, card_e)

        def swap(ddd):
            ddd.entries = [(f, a, fremd_cert if f == 0xC100 and a == 0 else d)
                           for f, a, d in ddd.entries]

        states = verify_card(build(swap), roots)
        assert summary(states).state == FAILED


def _tlv(tag: int, value: bytes) -> bytes:
    """BER-TLV bauen – Kennung ein oder zwei Byte, Länge kurz oder lang."""
    tag_bytes = bytes([tag]) if tag <= 0xFF else bytes([tag >> 8, tag & 0xFF])
    n = len(value)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return tag_bytes + length + value


def _der_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.split(".")]
    out = bytearray([parts[0] * 40 + parts[1]])
    for value in parts[2:]:
        chunk = [value & 0x7F]
        value >>= 7
        while value:
            chunk.append((value & 0x7F) | 0x80)
            value >>= 7
        out += bytes(reversed(chunk))
    return bytes(out)


def _ec_key(curve_name="SECP256R1"):
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(getattr(ec, curve_name)())


def _raw_point(priv) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def _ec_sign(priv, message: bytes, size: int, hash_name="sha256") -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    algorithm = {"sha256": hashes.SHA256, "sha384": hashes.SHA384,
                 "sha512": hashes.SHA512}[hash_name]()
    der = priv.sign(message, ec.ECDSA(algorithm))
    r, s_ = utils.decode_dss_signature(der)
    return r.to_bytes(size, "big") + s_.to_bytes(size, "big")


def _cvc(issuer_priv, issuer_size, car: bytes, chr_: bytes, priv, oid: str,
         hash_name="sha256") -> bytes:
    """Ein Zertifikat nach Anlage 11 Teil B."""
    # Reihenfolge und Kennungen wie auf einer echten Karte nachgemessen:
    # 5F29 Profil, 42 Aussteller, 5F4C Berechtigung, 7F49 Schluessel, 5F20 Inhaber,
    # 5F25/5F24 Gueltigkeit. Die Berechtigung traegt 5F4C, nicht 7F4C.
    body = (_tlv(0x5F29, b"\x00") + _tlv(0x42, car) + _tlv(0x5F4C, b"\xff" * 7)
            + _tlv(0x7F49, _tlv(0x06, _der_oid(oid)) + _tlv(0x86, _raw_point(priv)))
            + _tlv(0x5F20, chr_)
            + _tlv(0x5F25, b"\x00" * 4) + _tlv(0x5F24, b"\x7f" * 4))
    body_tlv = _tlv(0x7F4E, body)
    sig = _ec_sign(issuer_priv, body_tlv, issuer_size, hash_name)
    return _tlv(0x7F21, body_tlv + _tlv(0x5F37, sig))


P256 = "1.2.840.10045.3.1.7"
BP256 = "1.3.36.3.3.2.8.1.1.7"


def _gen2_download(card_sign_priv, certs: dict) -> "object":
    """Baut einen Gen-2-Download aus den Demodaten: Anhang 2 Daten, 3 Signatur."""
    from tachoarchiv.ddd import DddFile
    src = DddFile.parse(build_demo())
    out = DddFile()
    for fid, cert in certs.items():
        out.add(fid, 2, cert)
    for fid, app, payload in src.entries:
        if app != 0 or fid in (0xC100, 0xC108, 0x0002, 0x0005):
            continue
        out.add(fid, 2, payload)
        out.add(fid, 3, _ec_sign(card_sign_priv, payload, 32))
    return out


def test_gen2_signature_chain():
    """Wurzel -> Mitgliedstaat -> Signaturzertifikat der Karte -> Dateien."""
    from tachoarchiv.signature import (FAILED, OK, RootStore, parse_gen2_certificate,
                                       summary, verify_card)
    root = _ec_key()
    msca = _ec_key()
    card_ma = _ec_key()
    card_sign = _ec_key()
    root_cert = _cvc(root, 32, b"ERCAG2_1", b"ERCAG2_1", root, P256)       # selbst signiert
    msca_cert = _cvc(root, 32, b"ERCAG2_1", b"MSCA_D01", msca, P256)
    ma_cert = _cvc(msca, 32, b"MSCA_D01", b"CARDMA01", card_ma, P256)
    sign_cert = _cvc(msca, 32, b"MSCA_D01", b"CARDSG01", card_sign, P256)

    key = parse_gen2_certificate(root_cert)
    assert key is not None and key.chr == b"ERCAG2_1" and key.curve == "SECP256R1"
    assert parse_gen2_certificate(msca_cert, key) is not None
    # Ein Zertifikat, das nicht von dieser Wurzel stammt, faellt durch
    fremd = _ec_key()
    assert parse_gen2_certificate(_cvc(fremd, 32, b"ERCAG2_1", b"MSCA_D01", msca, P256),
                                  key) is None

    ddd = _gen2_download(card_sign, {0xC100: ma_cert, 0xC101: sign_cert, 0xC108: msca_cert})
    assert ddd.generation == 2
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp) / "erca"
        folder.mkdir()
        (folder / "erca_gen2.cert").write_bytes(root_cert)
        roots = RootStore(folder)
        assert not roots.empty and roots.gen2
        states = verify_card(ddd, roots)
        assert states and all(s.state == OK for s in states.values()), \
            {hex(k): (v.state, v.reason) for k, v in states.items() if v.state != OK}
        assert summary(states).state == OK

        # Ohne Wurzel: Daten und Mitgliedstaat bestaetigt, Wurzel bleibt offen.
        # Anders als bei Generation 1 steht der Schluessel im Klartext im Rumpf,
        # deshalb kommt man auch ohne Wurzel bis hierher.
        from tachoarchiv.signature import PARTIAL
        offen = verify_card(ddd, RootStore(pathlib.Path(tmp) / "leer"))
        assert summary(offen).state == PARTIAL
        assert all(s.state == PARTIAL for s in offen.values())

        # Veraenderte Datei faellt auf
        broken = _gen2_download(card_sign, {0xC100: ma_cert, 0xC101: sign_cert,
                                            0xC108: msca_cert})
        for i, (fid, app, payload) in enumerate(broken.entries):
            if fid == 0x0504 and app == 2:
                broken.entries[i] = (fid, app, payload[:-1] + bytes([payload[-1] ^ 0x01]))
        states = verify_card(broken, roots)
        assert states[0x0504].state == FAILED
        assert summary(states).state == FAILED

        assert summary(verify_card(broken, RootStore(pathlib.Path(tmp) / "leer"))).state == FAILED

        # Untergeschobenes Signaturzertifikat faellt auf
        fremde_karte = _ec_key()
        falsch = _gen2_download(fremde_karte, {
            0xC100: ma_cert, 0xC108: msca_cert,
            0xC101: _cvc(fremd, 32, b"MSCA_D01", b"CARDSG01", fremde_karte, P256)})
        assert summary(verify_card(falsch, roots)).state == FAILED


def test_gen2_brainpool_and_link_certificate():
    """Brainpool-Kurven und der Weg ueber ein Verknuepfungszertifikat."""
    from tachoarchiv.signature import OK, RootStore, summary, verify_card
    old_root = _ec_key()
    new_root = _ec_key()
    msca = _ec_key()
    card_sign = _ec_key("BrainpoolP256R1")
    old_cert = _cvc(old_root, 32, b"ERCAG2_1", b"ERCAG2_1", old_root, P256)
    # Die neue Wurzel, signiert mit der alten – so wird der Wechsel überbrückt
    link = _cvc(old_root, 32, b"ERCAG2_1", b"ERCAG2_2", new_root, P256)
    msca_cert = _cvc(new_root, 32, b"ERCAG2_2", b"MSCA_D02", msca, P256)
    sign_cert = _cvc(msca, 32, b"MSCA_D02", b"CARDSG02", card_sign, BP256)
    ddd = _gen2_download(card_sign, {0xC100: sign_cert, 0xC101: sign_cert,
                                     0xC108: msca_cert, 0xC109: link})
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp) / "erca"
        folder.mkdir()
        (folder / "alt.cert").write_bytes(old_cert)       # nur die alte Wurzel liegt vor
        states = verify_card(ddd, RootStore(folder))
        assert summary(states).state == OK, {hex(k): (v.state, v.reason) for k, v in states.items()}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
