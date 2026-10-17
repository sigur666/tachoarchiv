"""Berichte: HTML (für PDF-Druck über Qt) und CSV."""
from __future__ import annotations

import csv
import datetime as dt
import html

from . import __version__
from .analysis import AVAIL, DRIVE, REST, UNKNOWN, WORK, Result
from . import i18n
from .i18n import event_name, fmt_date, fmt_dt, fmt_dur, fmt_finding, tr
from .parser import CardData

UTC = dt.timezone.utc
SEV_COLOR = {"violation": "#b3261e", "warning": "#8a5a00", "info": "#35607a"}
# Flächen für Tage mit Befunden. Hell gewählt, damit die Zahlen im Ausdruck lesbar bleiben.
SEV_TINT = {"violation": "#fdecea", "warning": "#fcf3e2"}
SEV_RANK = {"violation": 2, "warning": 1}


def _e(s) -> str:
    return html.escape(str(s))


def day_marks(findings) -> dict[dt.date, tuple[str, str]]:
    """Je Tag die schwerste Bewertung und einen Text dazu.

    Die Farbe allein darf die Aussage nicht tragen – im Schwarzweißdruck und bei
    Farbenblindheit bleibt die Spalte mit dem Klartext lesbar.
    """
    counts: dict[dt.date, dict[str, int]] = {}
    for f in findings:
        if f.severity in SEV_RANK:
            counts.setdefault(f.time.date(), {}).setdefault(f.severity, 0)
            counts[f.time.date()][f.severity] += 1
    marks = {}
    for day, per_sev in counts.items():
        sev = max(per_sev, key=lambda s: SEV_RANK[s])
        parts = [f"{per_sev[s]} × {tr('sev_' + s)}" for s in ("violation", "warning") if s in per_sev]
        marks[day] = (sev, ", ".join(parts))
    return marks


def build_html(card: CardData, res: Result, since: dt.datetime | None, period_label: str,
               scope: str = "full", with_warnings: bool = False, language: str | None = None,
               period_key: str = "", control_days: int = 56) -> str:
    """Baut den Bericht.

    ``scope`` ist "full" (alles) oder "violations" (Kopfdaten und Verstöße).
    ``language`` setzt die Berichtssprache unabhängig von der Oberfläche – damit
    lässt sich ein Bericht für jemanden ausdrucken, der die Programmsprache nicht
    liest. Die Sprache wird danach wieder zurückgestellt.
    """
    previous = i18n.language()
    if language and language != previous:
        i18n.set_language(language)
    try:
        if period_key:
            # Der Zeitraum gehoert in die Sprache des Berichts, nicht in die der Oberflaeche.
            period_label = (tr(period_key, days=control_days) if period_key == "period_control"
                            else tr(period_key))
        return _build(card, res, since, period_label, scope, with_warnings)
    finally:
        i18n.set_language(previous)


def _build(card: CardData, res: Result, since: dt.datetime | None, period_label: str,
           scope: str, with_warnings: bool) -> str:
    i = card.info
    findings = [f for f in res.findings if since is None or f.time >= since]
    if scope == "violations":
        keep = {"violation", "warning", "info"} if with_warnings else {"violation"}
        findings = [f for f in findings if f.severity in keep]
    days = [d for d in res.days if since is None or d.date >= since.date()]
    weeks = [w for w in res.weeks if since is None or w.monday + dt.timedelta(days=7) > since]
    c = res.counts(since)
    rows = [
        (tr("f_name"), i.display_name),
        (tr("f_birth"), fmt_date(i.birth_date)),
        (tr("f_card"), f"{i.card_number} ({i.issuing_nation})"),
        (tr("f_valid"), f"{fmt_date(i.validity_begin)} – {fmt_date(i.expiry_date)}"),
        (tr("f_licence"), f"{i.licence_number} ({i.licence_nation})"),
        (tr("f_last_download"), fmt_dt(i.last_download)),
        (tr("report_period"), period_label),
        (tr("f_findings"), tr("count_summary", **c)),
    ]
    out = [
        "<html><head><meta charset='utf-8'><style>",
        "body{font-family:'Noto Sans','DejaVu Sans',sans-serif;font-size:9pt;color:#1a1a1a}",
        "h1{font-size:16pt;margin:0 0 4pt 0} h2{font-size:11pt;margin:14pt 0 4pt 0;border-bottom:1px solid #999}",
        "table{border-collapse:collapse;width:100%} td,th{padding:2pt 4pt;border-bottom:1px solid #ddd;vertical-align:top}",
        "th{text-align:left;background:#eef1f4} .num{text-align:right} .mark{padding-left:10pt}",
        "</style></head><body>",
        f"<h1>{_e(tr('report_title'))}</h1>",
        f"<p>{_e(tr('report_created'))}: {_e(fmt_dt(dt.datetime.now(UTC)))} UTC · TachoArchiv {__version__}</p>",
        "<table>",
    ]
    out += [f"<tr><th width='30%'>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in rows]
    out.append("</table>")

    head_key = "tab_violations" if scope == "violations" and not with_warnings else "tab_findings"
    out.append(f"<h2>{_e(tr(head_key))}</h2><table><tr>"
               f"<th>{_e(tr('col_time'))}</th><th>{_e(tr('col_severity'))}</th>"
               f"<th>{_e(tr('col_message'))}</th><th>{_e(tr('col_legal'))}</th></tr>")
    for f in findings:
        out.append(f"<tr><td>{_e(fmt_dt(f.time))}</td>"
                   f"<td style='color:{SEV_COLOR[f.severity]}'><b>{_e(tr('sev_' + f.severity))}</b></td>"
                   f"<td>{_e(fmt_finding(f))}</td><td>{_e(tr(f.legal))}</td></tr>")
    out.append("</table>")

    if scope == "violations":
        out.append(f"<p><i>{_e(tr('disclaimer'))}</i></p></body></html>")
        return "".join(out)

    out.append(f"<h2>{_e(tr('tab_weeks'))}</h2><table><tr><th>{_e(tr('col_week'))}</th>")
    for k in ("col_drive", "col_work", "col_avail", "col_rest", "col_worktime"):
        out.append(f"<th class='num'>{_e(tr(k))}</th>")
    out.append("</tr>")
    for w in weeks:
        y, n = w.iso
        vals = [w.totals[DRIVE], w.totals[WORK], w.totals[AVAIL], w.totals[REST] + w.totals[UNKNOWN], w.worktime]
        out.append(f"<tr><td>{_e(tr('week_fmt', week=n, year=y))}</td>"
                   + "".join(f"<td class='num'>{fmt_dur(v)}</td>" for v in vals) + "</tr>")
    out.append("</table>")

    marks = day_marks(findings)
    out.append(f"<h2>{_e(tr('tab_days'))}</h2><table><tr><th>{_e(tr('col_date'))}</th>")
    for k in ("col_drive", "col_work", "col_avail", "col_rest", "col_unknown", "col_km"):
        out.append(f"<th class='num'>{_e(tr(k))}</th>")
    out.append(f"<th class='mark' width='22%'>{_e(tr('col_severity'))}</th></tr>")
    for d in days:
        t = d.totals
        sev, text = marks.get(d.date, ("", ""))
        # Qt zeichnet Zellhintergründe nur über das style-Attribut der Zelle selbst.
        bg = f" style='background:{SEV_TINT[sev]}'" if sev else ""
        out.append(f"<tr><td{bg}>{'⚠ ' if sev else ''}{_e(fmt_date(d.date))}{' ✎' if d.manual else ''}</td>"
                   + "".join(f"<td class='num'{bg}>&nbsp;{fmt_dur(t.get(a, 0))}</td>"
                             for a in (DRIVE, WORK, AVAIL, REST, UNKNOWN))
                   + f"<td class='num'{bg}>&nbsp;{d.distance}</td>"
                   + (f"<td class='mark' align='left' style='background:{SEV_TINT[sev]};color:{SEV_COLOR[sev]}'>"
                      f"&nbsp;&nbsp;<b>{_e(text)}</b></td>" if sev else "<td class='mark'></td>")
                   + "</tr>")
    out.append("</table>")

    if card.events:
        out.append(f"<h2>{_e(tr('tab_events'))}</h2><table><tr><th>{_e(tr('col_event'))}</th>"
                   f"<th>{_e(tr('col_from'))}</th><th>{_e(tr('col_to'))}</th><th>{_e(tr('col_vehicle'))}</th></tr>")
        for e in card.events:
            if since is None or (e.begin and e.begin >= since):
                out.append(f"<tr><td>{_e(event_name(e.type, e.fault))}</td><td>{_e(fmt_dt(e.begin))}</td>"
                           f"<td>{_e(fmt_dt(e.end))}</td><td>{_e(e.nation)} {_e(e.registration)}</td></tr>")
        out.append("</table>")
    out.append(f"<p><i>{_e(tr('disclaimer'))}</i></p></body></html>")
    return "".join(out)


def write_csv(path: str, res: Result, since: dt.datetime | None) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow([tr("col_time"), tr("col_severity"), tr("col_message"), tr("col_legal")])
        for f in res.findings:
            if since is None or f.time >= since:
                w.writerow([f.time.strftime("%Y-%m-%d %H:%M"), tr("sev_" + f.severity), fmt_finding(f),
                            tr(f.legal)])
