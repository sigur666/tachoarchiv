#!/usr/bin/env python3
"""Erzeugt die lateinische Fassung des Serbischen aus der kyrillischen.

Die serbische Schriftumschrift ist eindeutig (Gajica), deshalb wird sie
gerechnet statt getippt. Aufruf nach jeder Änderung an locale/sr.json:

    python3 tools/sr_latn.py

Lateinische Anteile – Platzhalter, Verordnungsnummern, Befehlszeilen –
bleiben unangetastet, weil nur kyrillische Zeichen ersetzt werden.
"""
from __future__ import annotations

import json
import pathlib
import sys

MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}
UPPER = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž",
    "З": "Z", "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N",
    "Њ": "Nj", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "Ć", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
}
DIGRAPHS = {"Љ": "LJ", "Њ": "NJ", "Џ": "DŽ"}


def transliterate(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch in UPPER:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            # In durchgehender Großschreibung auch den Digraphen groß setzen
            if ch in DIGRAPHS and (nxt in UPPER or nxt in DIGRAPHS):
                out.append(DIGRAPHS[ch])
            else:
                out.append(UPPER[ch])
        else:
            out.append(MAP.get(ch, ch))
    return "".join(out)


def main() -> int:
    base = pathlib.Path(__file__).resolve().parents[1] / "tachoarchiv" / "locale"
    src = json.loads((base / "sr.json").read_text(encoding="utf-8"))
    out = {k: transliterate(v) for k, v in src.items()}
    out["date_fmt"] = src["date_fmt"]                    # Formatzeichen nicht anfassen
    (base / "sr-latn.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"sr-latn.json geschrieben, {len(out)} Einträge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
