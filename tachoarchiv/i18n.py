"""Übersetzungen. Die Texte liegen als JSON je Sprache unter ``locale/``.

Neue Sprache: Datei ``locale/<code>.json`` anlegen (Schlüssel wie in ``de.json``)
und den Code mit dem Namen in der eigenen Sprache in LANGUAGES eintragen.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

# Anzeigename jeweils in der Sprache selbst; Reihenfolge = Reihenfolge im Menü.
LANGUAGES = {
    "de": "Deutsch",
    "en": "English",
    "ar": "العربية",
    "be": "Беларуская",
    "bg": "Български",
    "cs": "Čeština",
    "el": "Ελληνικά",
    "es": "Español",
    "et": "Eesti",
    "fr": "Français",
    "hi": "हिन्दी",
    "hr": "Hrvatski",
    "hu": "Magyar",
    "it": "Italiano",
    "lt": "Lietuvių",
    "lv": "Latviešu",
    "nl": "Nederlands",
    "pa": "ਪੰਜਾਬੀ",
    "pl": "Polski",
    "pt": "Português",
    "ro": "Română",
    "ru": "Русский",
    "sk": "Slovenčina",
    "sl": "Slovenščina",
    "sq": "Shqip",
    "sr": "Српски",
    "sr-latn": "Srpski (latinica)",
    "tr": "Türkçe",
    "uk": "Українська",
    "ur": "اردو",
}

# ISO 639-3. Serbisch in lateinischer Schrift hat keinen eigenen Dreibuchstabencode;
# dort kommt der Schriftzusatz nach ISO 15924 dazu.
ISO3 = {
    "de": "deu", "en": "eng", "ar": "ara", "be": "bel", "bg": "bul", "cs": "ces",
    "el": "ell", "es": "spa", "et": "est", "fr": "fra", "hi": "hin", "hr": "hrv",
    "hu": "hun", "it": "ita", "lt": "lit", "lv": "lav", "nl": "nld", "pa": "pan",
    "pl": "pol", "pt": "por", "ro": "ron", "ru": "rus", "sk": "slk", "sl": "slv",
    "sq": "sqi", "sr": "srp", "sr-latn": "srp-Latn", "tr": "tur", "uk": "ukr",
    "ur": "urd",
}

# Sprachen mit Schreibrichtung von rechts nach links
RTL = {"ur", "ar", "fa", "he"}

_LOCALE = Path(__file__).with_name("locale")
_current = "de"


def _load() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for code in LANGUAGES:
        f = _LOCALE / f"{code}.json"
        try:
            out[code] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[code] = {}
    return out


TR: dict[str, dict[str, str]] = _load()


def set_language(lang: str) -> None:
    global _current
    _current = lang if TR.get(lang) else "en"


def language() -> str:
    return _current


def is_rtl(lang: str | None = None) -> bool:
    return (lang or _current) in RTL


def iso3(code: str) -> str:
    return ISO3.get(code, code)


def language_label(code: str) -> str:
    """Wie die Sprache in der Auswahl steht: Code und Eigenname.

    Der Code allein wäre kürzer, aber wer die Oberfläche auf seine Sprache stellen
    soll, erkennt „ਪੰਜਾਬੀ“ sofort und „pan“ nicht unbedingt.
    """
    return f"{iso3(code)} – {LANGUAGES.get(code, code)}"


def tr(key: str, **kw) -> str:
    s = TR.get(_current, {}).get(key) or TR.get("en", {}).get(key) or key
    try:
        return s.format(**kw) if kw else s
    except (KeyError, IndexError, ValueError):
        return s


DURATION_KEYS = {"value", "drive", "work", "limit", "deficit"}


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in TR else "en"


def language() -> str:
    return _current


def tr(key: str, **kw) -> str:
    s = TR[_current].get(key) or TR["en"].get(key) or key
    return s.format(**kw) if kw else s


def fmt_dur(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    m = abs(int(minutes))
    return f"{sign}{m // 60}:{m % 60:02d} h"


def fmt_date(d: dt.date | dt.datetime | None) -> str:
    if d is None:
        return "–"
    return d.strftime(TR[_current]["date_fmt"])


def fmt_dt(d: dt.datetime | None) -> str:
    if d is None:
        return "–"
    return d.strftime(TR[_current]["date_fmt"] + " %H:%M")


def fmt_finding(f) -> str:
    params = {}
    for k, v in f.params.items():
        if isinstance(v, dt.datetime):
            params[k] = fmt_dt(v)
        elif isinstance(v, dt.date):
            params[k] = fmt_date(v)
        elif k in DURATION_KEYS:
            params[k] = fmt_dur(v)
        else:
            params[k] = v
    return tr(f.key, **params)


def event_name(code: int, fault: bool = False) -> str:
    if 1 <= code <= 10:
        return tr(f"ev_{code}")
    if 0x10 <= code <= 0x1F:
        return tr("ev_sec")
    if 0x20 <= code <= 0x2F:
        return tr("ev_fault_vu")
    if 0x30 <= code <= 0x3F:
        return tr("ev_fault_card")
    return tr("ev_other", code=f"{code:02X}")
