"""Auswertung nach VO (EG) 561/2006 i. d. F. VO (EU) 2020/1054 (Mobilitätspaket I),
VO (EU) 165/2014, VO (EU) 581/2010 sowie optional ArbZG § 21a / RL 2002/15/EG.

Rechtsstand: September 2026 (inkl. 56-Tage-Mitführpflicht seit 31.12.2024 und
Tachographenpflicht für > 2,5 t im grenzüberschreitenden Verkehr seit 01.07.2026).

Alle Berechnungen erfolgen in UTC, wie vom Fahrtenschreiber aufgezeichnet.
Die Auswertung ist eine Hilfe und ersetzt keine behördliche oder anwaltliche Prüfung.
"""
from __future__ import annotations

import bisect
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from .parser import AVAIL, COND_FERRY_BEGIN, COND_FERRY_END, DRIVE, REST, WORK, CardData

UTC = dt.timezone.utc
UNKNOWN = 4
H = 60
# Grenzwerte als Namen – dieselben Zahlen stehen sonst verstreut in den Prüfungen
DAY_DRIVE = 9 * H                       # Art. 6 Abs. 1
DAY_DRIVE_EXT = 10 * H                  # zweimal je Woche zulässig
WEEK_DRIVE = 56 * H                     # Art. 6 Abs. 2
TWO_WEEK_DRIVE = 90 * H                 # Art. 6 Abs. 3
EXT_PER_WEEK = 2
REDUCED_PER_WEEK = 3                    # reduzierte Tagesruhen zwischen Wochenruhen
WEEKLY_LIMIT = dt.timedelta(hours=144)  # Art. 8 Abs. 6: sechs 24-Stunden-Zeitraeume
DAY = dt.timedelta(days=1)

# Art. 9 Abs. 1: Ruhezeit auf Fähre/Zug höchstens zweimal, zusammen höchstens 1 h
# unterbrechbar; bei regelmäßiger wöchentlicher Ruhezeit nur bei Überfahrten ab 8 h.
FERRY_MAX_CUTS = 2
FERRY_MAX_CUT = 60
FERRY_WEEKLY_MIN = 8 * H
FERRY_MAX_OPEN = dt.timedelta(hours=24)

LEGAL = {
    # Nur noch Schluessel: die Fundstelle wird in der Sprache des Berichts gesetzt.
    # Ein polnischer Bericht soll "rozporzadzenie (WE) nr 561/2006" nennen, nicht "VO (EG)".
    "art6": "legal_art6",
    "art7": "legal_art7",
    "art8": "legal_art8",
    "art8_6": "legal_art8_6",
    "art9": "legal_art9",
    "arbzg4": "legal_arbzg4",
    "arbzg3": "legal_arbzg3",
    "arbzg21a": "legal_arbzg21a",
    "dl": "legal_dl",
    "card": "legal_card",
    "gap": "legal_gap",
    "carry": "legal_carry",
}


def mins(td: dt.timedelta) -> int:
    return int(td.total_seconds() // 60)


def overlap(a0, a1, b0, b1) -> int:
    return max(0, mins(min(a1, b1) - max(a0, b0)))


def monday(d: dt.datetime) -> dt.datetime:
    d0 = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return d0 - dt.timedelta(days=d0.weekday())


@dataclass
class Settings:
    unknown_as_rest: bool = True
    check_arbzg: bool = True
    ferry_rule: bool = True
    check_coverage: bool = True
    coverage_days: int = 56          # Nachweispflicht: laufender Tag + 56 vorausgehende
    now: dt.datetime | None = None


@dataclass
class Segment:
    start: dt.datetime
    end: dt.datetime
    activity: int
    crew: bool = False
    manual: bool = False
    gap: bool = False

    @property
    def dur(self) -> int:
        return mins(self.end - self.start)


@dataclass
class Item:
    start: dt.datetime
    end: dt.datetime
    kind: int          # REST steht für "ruhe-artig" (Ruhe/ggf. unbekannt)
    crew: bool = False

    @property
    def dur(self) -> int:
        return mins(self.end - self.start)


@dataclass
class Crossing:
    """Fähr- oder Eisenbahnüberfahrt laut Kartenaufzeichnung (specific condition)."""
    start: dt.datetime
    end: dt.datetime
    estimated: bool = False

    @property
    def dur(self) -> int:
        return mins(self.end - self.start)


@dataclass
class RestBlock:
    """Ruhezeit; bei Fähre/Zug ggf. über zulässige Unterbrechungen hinweg zusammengefasst."""
    start: dt.datetime
    end: dt.datetime
    dur: int                                             # tatsächliche Ruhe ohne Unterbrechungen
    crew: bool = False
    cuts: list[tuple[dt.datetime, dt.datetime]] = field(default_factory=list)
    crossing: int = 0                                    # längste zugehörige Überfahrt in Minuten

    @property
    def cut_total(self) -> int:
        return sum(mins(b - a) for a, b in self.cuts)

    def within(self, a: dt.datetime, b: dt.datetime) -> int:
        """Ruheminuten im Fenster [a, b) ohne die Unterbrechungen."""
        t = overlap(self.start, self.end, a, b)
        for c0, c1 in self.cuts:
            t -= overlap(c0, c1, a, b)
        return max(0, t)


@dataclass
class Finding:
    key: str
    severity: str      # violation | warning | info
    time: dt.datetime
    legal: str
    params: dict = field(default_factory=dict)


@dataclass
class Shift:
    start: dt.datetime
    end: dt.datetime
    rest_end: dt.datetime
    rest_kind: str
    driving: int
    work: int
    avail: int
    crew: bool


@dataclass
class DaySummary:
    date: dt.date
    segments: list[tuple[int, int, int, bool]]
    totals: dict[int, int]
    distance: int
    manual: bool


@dataclass
class WeekSummary:
    monday: dt.datetime
    totals: dict[int, int]

    @property
    def worktime(self) -> int:
        return self.totals.get(DRIVE, 0) + self.totals.get(WORK, 0)

    @property
    def iso(self) -> tuple[int, int]:
        y, w, _ = self.monday.isocalendar()
        return y, w


@dataclass
class Result:
    segments: list[Segment]
    items: list[Item]
    shifts: list[Shift]
    days: list[DaySummary]
    weeks: list[WeekSummary]
    findings: list[Finding]
    data_start: dt.datetime | None
    data_end: dt.datetime | None
    weekly_rests: list[tuple[dt.datetime, dt.datetime, str]] = field(default_factory=list)
    crossings: list[Crossing] = field(default_factory=list)

    def counts(self, since: dt.datetime | None = None) -> dict[str, int]:
        c = {"violation": 0, "warning": 0, "info": 0}
        for f in self.findings:
            if since is None or f.time >= since:
                c[f.severity] += 1
        return c


# --------------------------------------------------------------------------- Zeitleiste

def build_segments(card: CardData) -> list[Segment]:
    raw: list[Segment] = []
    for d in sorted(card.days, key=lambda r: r.date):
        by_min = {}
        for c in d.changes:
            if c.minute < 1440:
                by_min[c.minute] = c
        ch = [by_min[k] for k in sorted(by_min)]
        for i, c in enumerate(ch):
            e = ch[i + 1].minute if i + 1 < len(ch) else 1440
            if c.absent:
                # 'c' = Folgeaktivitätsstatus: 1 = bekannt (Nachtrag), 0 = unbekannt
                act, manual, crew = (c.activity, True, False) if c.crew else (UNKNOWN, False, False)
            else:
                act, manual, crew = c.activity, False, bool(c.crew)
            raw.append(Segment(d.date + dt.timedelta(minutes=c.minute),
                               d.date + dt.timedelta(minutes=e), act, crew, manual))
    out: list[Segment] = []
    for s in raw:
        if out:
            if s.start > out[-1].end:
                out.append(Segment(out[-1].end, s.start, UNKNOWN, gap=True))
            elif s.start < out[-1].end:
                s.start = out[-1].end
        if s.end <= s.start:
            continue
        p = out[-1] if out else None
        if p and p.activity == s.activity and p.crew == s.crew and p.manual == s.manual \
                and p.gap == s.gap and p.end == s.start:
            p.end = s.end
        else:
            out.append(s)
    return out


def build_items(segs: list[Segment], unknown_as_rest: bool) -> list[Item]:
    items: list[Item] = []
    for s in segs:
        restlike = s.activity == REST or (s.activity == UNKNOWN and unknown_as_rest)
        kind = REST if restlike else s.activity
        p = items[-1] if items else None
        if p and p.kind == kind and p.end == s.start and (kind == REST or p.crew == s.crew):
            p.end = s.end
        else:
            items.append(Item(s.start, s.end, kind, s.crew and s.activity == DRIVE))
    return items


class _Index:
    """Schnelle Summen über Zeitfenster."""

    def __init__(self, segs: list[Segment]):
        self.segs = segs
        self.starts = [s.start for s in segs]

    def sum(self, a: dt.datetime, b: dt.datetime, acts: tuple[int, ...]) -> int:
        i = max(0, bisect.bisect_right(self.starts, a) - 1)
        total = 0
        while i < len(self.segs) and self.segs[i].start < b:
            s = self.segs[i]
            if s.activity in acts:
                total += overlap(s.start, s.end, a, b)
            i += 1
        return total


# --------------------------------------------------------------------------- Fähre/Zug

def ferry_crossings(card: CardData, segs: list[Segment], out: list[Finding]) -> list[Crossing]:
    """Überfahrten aus den Kennzeichnungen der Karte (Art. 34 Abs. 6 VO 165/2014).

    Karten der 1. Generation kennen nur eine Beginn-Kennzeichnung; das Ende wird
    dann auf den Beginn der nächsten Lenkzeit geschätzt (höchstens 24 h).
    """
    data_end = segs[-1].end if segs else None
    drives = [s.start for s in segs if s.activity == DRIVE]
    res: list[Crossing] = []

    def close(start: dt.datetime) -> None:
        i = bisect.bisect_right(drives, start)
        end = drives[i] if i < len(drives) else (data_end or start + FERRY_MAX_OPEN)
        end = min(end, start + FERRY_MAX_OPEN)
        if end > start:
            res.append(Crossing(start, end, estimated=True))

    open_at: dt.datetime | None = None
    for c in sorted((c for c in card.conditions if c.time), key=lambda c: c.time):
        if c.type == COND_FERRY_BEGIN:
            if open_at is not None:
                close(open_at)
            open_at = c.time
        elif c.type == COND_FERRY_END and open_at is not None:
            if c.time > open_at:
                res.append(Crossing(open_at, c.time))
            open_at = None
    if open_at is not None:
        close(open_at)
    for c in res:
        if c.estimated:
            out.append(Finding("i_ferry_open", "info", c.start, LEGAL["art9"],
                               {"start": c.start, "end": c.end}))
    return res


def _crossing_at(crossings: list[Crossing], a: dt.datetime, b: dt.datetime) -> Crossing | None:
    """Überfahrt, in die die Unterbrechung [a, b) fällt (längste bei Überschneidung)."""
    best = None
    for c in crossings:
        if overlap(c.start, c.end, a, b) > 0 and (best is None or c.dur > best.dur):
            best = c
    return best


def build_rest_blocks(items: list[Item], crossings: list[Crossing],
                      out: list[Finding]) -> list[RestBlock]:
    """Ruhezeiten; auf Fähre/Zug werden zulässige Unterbrechungen übersprungen."""
    blocks: list[RestBlock] = []
    n = len(items)
    i = 0
    while i < n:
        if items[i].kind != REST:
            i += 1
            continue
        blk = RestBlock(items[i].start, items[i].end, items[i].dur)
        last = i
        broke = False
        while crossings:
            k = last + 1
            while k < n and items[k].kind != REST:
                k += 1
            if k >= n or k == last + 1:
                break
            c0, c1 = items[last].end, items[k].start
            cross = _crossing_at(crossings, c0, c1)
            if cross is None:
                break
            cut = mins(c1 - c0)
            if len(blk.cuts) >= FERRY_MAX_CUTS or blk.cut_total + cut > FERRY_MAX_CUT:
                if blk.dur >= 3 * H:
                    out.append(Finding("v_ferry_limit", "violation", c0, LEGAL["art9"],
                                       {"count": len(blk.cuts) + 1,
                                        "value": blk.cut_total + cut}))
                    broke = True
                break
            blk.cuts.append((c0, c1))
            blk.crossing = max(blk.crossing, cross.dur)
            blk.end, blk.dur, last = items[k].end, blk.dur + items[k].dur, k
        if blk.cuts:
            if blk.dur >= 11 * H:
                out.append(Finding("i_ferry_rest", "info", blk.start, LEGAL["art9"],
                                   {"count": len(blk.cuts), "value": blk.cut_total}))
            elif blk.dur >= 3 * H and not broke:
                # Art. 9 Abs. 1 gilt nur für die regelmäßige Tages- und die Wochenruhezeit.
                out.append(Finding("v_ferry_reduced", "violation", blk.start, LEGAL["art9"],
                                   {"value": blk.dur}))
        blocks.append(blk)
        i = last + 1
    return blocks


# --------------------------------------------------------------------------- Regeln

def _check_breaks(items: list[Item], out: list[Finding]) -> None:
    """Art. 7: nach 4,5 h Lenkzeit 45 min Unterbrechung (teilbar 15 + 30)."""
    acc = 0
    split = False
    cur: Finding | None = None
    for it in items:
        if it.kind == REST:
            d = it.dur
            if d >= 45 or (split and d >= 30):
                acc, split, cur = 0, False, None
            elif d >= 15:
                split = True
        elif it.kind == DRIVE:
            d = it.dur
            if acc + d > 270:
                if cur is None:
                    cur = Finding("v_break", "violation",
                                  it.start + dt.timedelta(minutes=max(0, 270 - acc)),
                                  LEGAL["art7"], {"drive": acc + d})
                    out.append(cur)
                else:
                    cur.params["drive"] = acc + d
            acc += d


def _find_shifts(items: list[Item], rests: list[RestBlock], idx: _Index, data_end: dt.datetime,
                 out: list[Finding]) -> list[Shift]:
    rest_starts = [r.start for r in rests]
    shifts: list[Shift] = []
    work_items = [it for it in items if it.kind != REST]
    if not work_items:
        return shifts
    work_starts = [w.start for w in work_items]
    S = work_items[0].start
    reduced = 0
    ext_per_week: dict[dt.datetime, int] = defaultdict(int)

    while S is not None and S < data_end:
        crew = any(it.crew for it in work_items
                   if S <= it.start < S + DAY and it.kind == DRIVE)
        W = S + (dt.timedelta(hours=30) if crew else DAY)
        i = bisect.bisect_left(rest_starts, S)
        had3 = False
        chosen = None
        kind = ""
        best, best_len = None, 0
        while i < len(rests) and rests[i].start < W:
            b = rests[i]
            cl = b.within(S, W)
            if cl > best_len:
                best, best_len = b, cl
            if crew:
                if cl >= 9 * H:
                    kind = "crew"
            elif cl >= 11 * H:
                kind = "regular"
            elif cl >= 9 * H:
                kind = "split" if had3 else "reduced"
            elif cl >= 3 * H:
                had3 = True
            if kind:
                if b.dur >= 24 * H:
                    kind = "weekly"
                chosen = b
                break
            i += 1

        if chosen is None:
            if W > data_end:
                break
            out.append(Finding("v_daily_rest", "violation", S, LEGAL["art8"],
                               {"value": best_len, "start": S,
                                "limit": 9 * H}))
            j = bisect.bisect_left(rest_starts, S)
            while j < len(rests) and rests[j].dur < 9 * H:
                j += 1
            chosen = rests[j] if j < len(rests) else best
            if chosen is None or chosen.end <= S:
                break
            kind = "weekly" if chosen.dur >= 24 * H else "insufficient"

        end = max(chosen.start, S)
        drv = idx.sum(S, end, (DRIVE,))
        sh = Shift(S, end, chosen.end, kind, drv, idx.sum(S, end, (WORK,)),
                   idx.sum(S, end, (AVAIL,)), crew)
        shifts.append(sh)

        wk = monday(S)
        if drv > 9 * H:
            ext_per_week[wk] += 1
            if drv > 10 * H:
                out.append(Finding("v_daily_drive", "violation", S, LEGAL["art6"],
                                   {"value": drv, "limit": 10 * H}))
            elif ext_per_week[wk] > 2:
                out.append(Finding("v_daily_drive_ext", "violation", S, LEGAL["art6"],
                                   {"value": drv, "count": ext_per_week[wk]}))
        if kind == "reduced":
            reduced += 1
            if reduced > 3:
                out.append(Finding("v_reduced_count", "violation", chosen.start, LEGAL["art8"],
                                   {"count": reduced}))
        elif kind == "weekly":
            reduced = 0

        nxt = bisect.bisect_left(work_starts, chosen.end)
        S = work_items[nxt].start if nxt < len(work_items) else None
    return shifts


def _check_weekly_rests(rests: list[RestBlock], data_start: dt.datetime, data_end: dt.datetime,
                        out: list[Finding]) -> list[tuple[dt.datetime, dt.datetime, str]]:
    weekly = []
    for b in rests:
        if b.dur < 24 * H:
            continue
        edge = b.start <= data_start or b.end >= data_end
        kind = "regular" if b.dur >= 45 * H else ("edge" if edge else "reduced")
        weekly.append((b, kind))
        # Art. 9 Abs. 1 UAbs. 2: regelmäßige Wochenruhe nur bei Überfahrt ab 8 h unterbrechbar.
        if b.cuts and b.dur >= 45 * H and b.crossing < FERRY_WEEKLY_MIN:
            out.append(Finding("v_ferry_weekly_short", "violation", b.start, LEGAL["art9"],
                               {"value": b.crossing, "limit": FERRY_WEEKLY_MIN}))

    limit = dt.timedelta(hours=144)
    for (p, pk), (n, nk) in zip(weekly, weekly[1:]):
        if n.start - p.end > limit:
            out.append(Finding("v_weekly_rest_late", "violation", p.end + limit, LEGAL["art8_6"],
                               {"value": mins(n.start - p.end)}))
        if pk == "reduced" and nk == "reduced":
            out.append(Finding("w_two_reduced", "warning", n.start, LEGAL["art8_6"], {}))
    if weekly and data_end - weekly[-1][0].end > limit:
        last = weekly[-1][0]
        out.append(Finding("v_weekly_rest_late", "violation", last.end + limit, LEGAL["art8_6"],
                           {"value": mins(data_end - last.end)}))

    for b, kind in weekly:
        if kind != "reduced":
            continue
        deficit = 45 * H - b.dur
        deadline = monday(b.start) + dt.timedelta(weeks=4)
        ok = False
        for c in rests:
            if c.start <= b.end or c.end > deadline:
                continue
            req = 45 * H if c.dur >= 45 * H else (24 * H if c.dur >= 24 * H else 9 * H)
            if c.dur - req >= deficit:
                ok = True
                break
        if not ok:
            if deadline <= data_end:
                out.append(Finding("v_weekly_rest_comp", "violation", deadline, LEGAL["art8_6"],
                                   {"deficit": deficit, "deadline": deadline}))
            else:
                out.append(Finding("i_weekly_rest_comp_open", "info", b.end, LEGAL["art8_6"],
                                   {"deficit": deficit, "deadline": deadline}))
    return [(b.start, b.end, k) for b, k in weekly]


def _weeks(idx: _Index, data_start: dt.datetime, data_end: dt.datetime) -> list[WeekSummary]:
    weeks = []
    m = monday(data_start)
    while m < data_end:
        e = m + dt.timedelta(days=7)
        totals = {a: idx.sum(m, e, (a,)) for a in (REST, AVAIL, WORK, DRIVE, UNKNOWN)}
        weeks.append(WeekSummary(m, totals))
        m = e
    return weeks


def _check_weekly_driving(weeks: list[WeekSummary], out: list[Finding]) -> None:
    for i, w in enumerate(weeks):
        d = w.totals[DRIVE]
        if d > 56 * H:
            out.append(Finding("v_weekly_drive", "violation", w.monday, LEGAL["art6"], {"value": d}))
        if i > 0:
            two = d + weeks[i - 1].totals[DRIVE]
            if two > 90 * H:
                out.append(Finding("v_fortnight_drive", "violation", weeks[i - 1].monday,
                                   LEGAL["art6"], {"value": two}))


def _check_arbzg(shifts: list[Shift], items: list[Item], weeks: list[WeekSummary],
                 out: list[Finding]) -> None:
    starts = [it.start for it in items]
    for sh in shifts:
        i = bisect.bisect_left(starts, sh.start)
        chain = 0
        breaks = 0
        flagged = False
        while i < len(items) and items[i].start < sh.end:
            it = items[i]
            if it.kind == REST:
                if it.dur >= 15:
                    breaks += it.dur
                    chain, flagged = 0, False
            elif it.kind in (WORK, DRIVE):
                chain += it.dur
                if chain > 6 * H and not flagged:
                    out.append(Finding("v_arbzg_6h", "violation", it.start, LEGAL["arbzg4"],
                                       {"value": chain}))
                    flagged = True
                elif flagged:
                    out[-1].params["value"] = max(out[-1].params["value"], chain)
            i += 1
        work = sh.driving + sh.work
        need = 45 if work > 9 * H else (30 if work > 6 * H else 0)
        if breaks < need:
            out.append(Finding("v_arbzg_breaks", "violation", sh.start, LEGAL["arbzg4"],
                               {"value": breaks, "work": work, "limit": need}))
        if work > 10 * H:
            out.append(Finding("w_arbzg_daily", "warning", sh.start, LEGAL["arbzg3"],
                               {"value": work}))
    for w in weeks:
        if w.worktime > 60 * H:
            out.append(Finding("v_arbzg_weekly", "violation", w.monday, LEGAL["arbzg21a"],
                               {"value": w.worktime}))
    used = [w for w in weeks if w.worktime > 0][-16:]
    if len(used) >= 4:
        avg = sum(w.worktime for w in used) // len(used)
        if avg > 48 * H:
            out.append(Finding("w_arbzg_avg", "warning", used[-1].monday, LEGAL["arbzg21a"],
                               {"value": avg, "count": len(used)}))


def _check_admin(card: CardData, segs: list[Segment], now: dt.datetime, out: list[Finding]) -> None:
    info = card.info
    if info.last_download:
        days = (now - info.last_download).days
        if days > 28:
            out.append(Finding("w_download_due", "warning", now, LEGAL["dl"], {"count": days}))
    else:
        out.append(Finding("w_download_never", "warning", now, LEGAL["dl"], {}))
    if info.expiry_date:
        if info.expiry_date < now:
            out.append(Finding("v_card_expired", "violation", info.expiry_date, LEGAL["card"],
                               {"date": info.expiry_date}))
        elif info.expiry_date - now < dt.timedelta(days=60):
            out.append(Finding("w_card_expiry", "warning", now, LEGAL["card"],
                               {"date": info.expiry_date}))
    for s in segs:
        if s.gap and s.dur >= 24 * H:
            out.append(Finding("i_gap", "info", s.start, LEGAL["gap"], {"start": s.start, "end": s.end}))


def remaining(res: "Result", now: dt.datetime | None = None) -> dict:
    """Was ist zum Stichzeitpunkt noch zulässig?

    Eine Prognose, keine Zusage: gerechnet wird aus den vorliegenden Daten. Fahrten
    ohne Karte oder nach dem letzten Download sind darin nicht enthalten, und die
    Tageslenkzeit bezieht sich auf die Schicht, die den Stichzeitpunkt umschließt –
    liegt er außerhalb jeder Schicht, beginnt die Zählung wieder bei null.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    this_monday = monday(now)
    prev_monday = this_monday - dt.timedelta(days=7)
    by_monday = {w.monday: w for w in res.weeks}
    week_used = by_monday[this_monday].totals.get(DRIVE, 0) if this_monday in by_monday else 0
    prev_used = by_monday[prev_monday].totals.get(DRIVE, 0) if prev_monday in by_monday else 0

    current = next((s for s in res.shifts if s.start <= now <= s.rest_end), None)
    day_used = current.driving if current else 0
    week_shifts = [s for s in res.shifts if monday(s.start) == this_monday]
    extensions = sum(1 for s in week_shifts if s.driving > DAY_DRIVE)

    last_weekly_end = max((e for _, e, _ in res.weekly_rests), default=None)
    reduced = sum(1 for s in res.shifts
                  if s.rest_kind == "reduced" and (last_weekly_end is None or s.end > last_weekly_end))
    weekly_due = last_weekly_end + WEEKLY_LIMIT if last_weekly_end else None
    weekly = mins(weekly_due - now) if weekly_due else None

    limit = DAY_DRIVE_EXT if extensions < EXT_PER_WEEK else DAY_DRIVE
    return {
        "limit": limit,
        "day": max(limit - day_used, 0),
        "day_used": day_used,
        "week": max(WEEK_DRIVE - week_used, 0),
        "week_used": week_used,
        "fortnight": max(TWO_WEEK_DRIVE - week_used - prev_used, 0),
        "fortnight_used": week_used + prev_used,
        "extensions": max(EXT_PER_WEEK - extensions, 0),
        "reduced": max(REDUCED_PER_WEEK - reduced, 0),
        "weekly": weekly,
        "weekly_due": weekly_due,
    }


def coverage(data_start: dt.datetime | None, data_end: dt.datetime | None,
             now: dt.datetime, days: int) -> tuple[int, int, dt.date | None]:
    """Abdeckung des Nachweiszeitraums: (abgedeckte Tage, Tage gesamt, erster Tag).

    Nachzuweisen sind der laufende Tag und die `days` vorausgehenden Tage
    (Art. 36 VO (EU) 165/2014, seit 31.12.2024 56 Tage).
    """
    # Gezählt werden nur abgeschlossene Tage: der laufende Tag ist noch nicht vorbei
    # und liegt ohnehin auf der Karte im Fahrzeug.
    last_day = now.date() - dt.timedelta(days=1)
    first_day = last_day - dt.timedelta(days=days - 1)
    if data_start is None or data_end is None:
        return 0, days, None
    # Endet die Aufzeichnung genau um Mitternacht, enthält der Folgetag keine Daten.
    end = (data_end - dt.timedelta(seconds=1)) if data_end.time() == dt.time(0) else data_end
    first = max(data_start.date(), first_day)
    last = min(end.date(), last_day)
    if last < first:
        return 0, days, None
    return (last - first).days + 1, days, first


def _check_coverage(data_start, data_end, now: dt.datetime, days: int,
                    out: list[Finding]) -> None:
    covered, total, _ = coverage(data_start, data_end, now, days)
    if covered < total:
        out.append(Finding("w_coverage", "warning", now, LEGAL["carry"],
                           {"count": total - covered, "days": total,
                            "start": data_start, "end": data_end}))


def _days(card: CardData, segs: list[Segment], data_start, data_end) -> list[DaySummary]:
    dist = {r.date.date(): r.distance for r in card.days}
    out = []
    d0 = data_start.replace(hour=0, minute=0, second=0, microsecond=0)
    i = 0
    while d0 < data_end:
        d1 = d0 + DAY
        while i < len(segs) and segs[i].end <= d0:
            i += 1
        j = i
        parts = []
        totals = defaultdict(int)
        manual = False
        while j < len(segs) and segs[j].start < d1:
            s = segs[j]
            a, b = max(s.start, d0), min(s.end, d1)
            if b > a:
                parts.append((mins(a - d0), mins(b - d0), s.activity, s.manual))
                totals[s.activity] += mins(b - a)
                manual = manual or s.manual
            j += 1
        out.append(DaySummary(d0.date(), parts, dict(totals), dist.get(d0.date(), 0), manual))
        d0 = d1
    return out


def analyze(card: CardData, settings: Settings | None = None) -> Result:
    st = settings or Settings()
    now = st.now or dt.datetime.now(UTC)
    segs = build_segments(card)
    findings: list[Finding] = []
    if not segs:
        _check_admin(card, segs, now, findings)
        if st.check_coverage:
            _check_coverage(None, None, now, st.coverage_days, findings)
        return Result(segs, [], [], [], [], findings, None, None)
    data_start, data_end = segs[0].start, segs[-1].end
    items = build_items(segs, st.unknown_as_rest)
    idx = _Index(segs)

    crossings = ferry_crossings(card, segs, findings) if st.ferry_rule else []
    rests = build_rest_blocks(items, crossings, findings)

    _check_breaks(items, findings)
    shifts = _find_shifts(items, rests, idx, data_end, findings)
    weekly = _check_weekly_rests(rests, data_start, data_end, findings)
    weeks = _weeks(idx, data_start, data_end)
    _check_weekly_driving(weeks, findings)
    if st.check_arbzg:
        _check_arbzg(shifts, items, weeks, findings)
    _check_admin(card, segs, now, findings)
    if st.check_coverage:
        _check_coverage(data_start, data_end, now, st.coverage_days, findings)
    order = {"violation": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (f.time, order[f.severity]))
    return Result(segs, items, shifts, _days(card, segs, data_start, data_end), weeks,
                  findings, data_start, data_end, weekly, crossings)
