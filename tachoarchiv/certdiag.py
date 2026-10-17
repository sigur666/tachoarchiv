"""Aufbau der Kartenzertifikate beschreiben – ohne Fahrerdaten auszugeben.

Gedacht für den Fall, dass die Signaturprüfung bei einer echten Karte nicht
durchläuft. Ausgegeben werden nur Strukturangaben: Kennungen, Längen, Kurve,
Prüfergebnisse. **Keine Kennungen von Karte oder Inhaber**, denn CHR und CAR
enthalten die Kartennummer.
"""
from __future__ import annotations

from .ddd import DddFile
from .signature import (CURVES, _key_from_body, _oid, _split_cert, _tlv, _verify_ecdsa,
                        parse_gen2_certificate, verify_gen2_data)

CERT_NAMES = {0xC100: "Karte, Authentisierung (C100)", 0xC101: "Karte, Signatur (C101)",
              0xC108: "Mitgliedstaat (C108)", 0xC109: "Verknüpfung (C109)"}


def _tag_map(data: bytes, depth: int = 0) -> list[str]:
    out = []
    for tag, value in _tlv(data):
        if tag == 0 and not value:
            continue                      # Fülldaten, keine Kennung
        out.append(f"{'  ' * depth}{tag:04X}  {len(value):5d} Byte")
        if tag in (0x7F21, 0x7F4E, 0x7F49):
            out += _tag_map(value, depth + 1)
    return out


def describe_roots(roots) -> list[str]:
    """Welche Wurzelzertifikate liegen vor – mit Fingerabdruck zum Vergleichen.

    Ein untergeschobenes Wurzelzertifikat würde die ganze Prüfung wertlos machen.
    Deshalb lässt sich der SHA-256 hier ablesen und mit der amtlichen
    Veröffentlichung vergleichen.
    """
    lines = ["--- Hinterlegte Wurzelzertifikate"]
    for folder in roots.folders:
        lines.append(f"    Ordner: {folder}" + ("" if folder.is_dir() else "  (nicht vorhanden)"))
    if roots.empty:
        lines.append("    keine gefunden")
        return lines + [""]
    for path, digest in roots.sources:
        lines.append(f"    {path.name}")
        lines.append(f"        SHA-256: {digest}")
    for key in roots.gen2:
        lines.append(f"    Generation 2: Kennung {key.chr.hex().upper()}, {key.curve}")
    for key in roots.gen1:
        lines.append(f"    Generation 1: Kennung {key.chr.hex().upper()}, RSA")
    return lines + [""]


def describe(raw: bytes, roots=None) -> list[str]:
    """Beschreibt die Zertifikate und Signaturen eines Downloads."""
    try:
        ddd = DddFile.parse(raw)
    except ValueError as e:
        return [f"Datei nicht lesbar: {e}"]
    gen = ddd.generation
    lines = [f"Generation: {gen}", ""]
    if roots is not None:
        lines += describe_roots(roots)
    if gen != 2:
        return lines + ["Keine Zertifikate der 2. Generation in dieser Datei."]

    keys = {}
    for fid, name in CERT_NAMES.items():
        cert = ddd.get(fid, 2)
        lines.append(f"--- {name}")
        if not cert:
            lines.append("    nicht vorhanden")
            lines.append("")
            continue
        lines.append(f"    Länge: {len(cert)} Byte")
        if not cert.strip(b"\x00") or not cert.strip(b"\xff"):
            # Manche Karten führen die Datei, lassen sie aber leer.
            lines += ["    nur Füllbytes – die Karte führt die Datei, nutzt sie aber nicht", ""]
            continue
        lines += ["    " + z for z in _tag_map(cert)]
        parts = _split_cert(cert)
        if parts is None:
            lines += ["    Aufbau nicht erkannt (7F4E oder 5F37 fehlt)", ""]
            continue
        body_tlv, body, sig = parts
        lines.append(f"    Rumpf mit Kennung: {len(body_tlv)} Byte, Inhalt {len(body)} Byte, "
                     f"Signatur {len(sig)} Byte")
        inner = _tlv(body)
        pk = next((v for t, v in inner if t == 0x7F49), None)
        if pk:
            oid = _oid(next((v for t, v in _tlv(pk) if t == 0x06), b""))
            curve = CURVES.get(oid, ("unbekannt", 0))
            point = next((v for t, v in _tlv(pk) if t == 0x86), b"")
            lines.append(f"    Kurve: {oid} -> {curve[0]}, Punkt {len(point)} Byte, "
                         f"erstes Byte {point[:1].hex().upper() or '--'}")
        key = _key_from_body(body)
        keys[fid] = (key, body_tlv, body, sig)
        lines.append("    Schlüssel gelesen: " + ("ja" if key else "nein"))
        lines.append("")

    # Welche Lesart passt: Signatur über den Rumpf mit oder ohne Kennung?
    def check(child, parent):
        if child not in keys or parent not in keys:
            return "nicht prüfbar (Zertifikat fehlt)"
        _, body_tlv, body, sig = keys[child]
        parent_key = keys[parent][0]
        if parent_key is None:
            return "nicht prüfbar (Ausstellerschlüssel fehlt)"
        with_tag = _verify_ecdsa(parent_key, sig, body_tlv)
        without = _verify_ecdsa(parent_key, sig, body)
        if with_tag:
            return "bestätigt (über Rumpf mit Kennung 7F4E)"
        if without:
            return ("passt nur über den Rumpfinhalt OHNE Kennung – bitte melden, "
                    "das Programm prüft diese Lesart nicht")
        return "nicht bestätigt – keine der beiden Lesarten passt"

    lines.append("--- Zertifikatssignaturen")
    lines.append("    erwartet: Signatur über den Rumpf mit Kennung 7F4E")
    lines.append(f"    C101 gegen C108: {check(0xC101, 0xC108)}")
    lines.append(f"    C100 gegen C108: {check(0xC100, 0xC108)}")
    if 0xC109 in keys:
        lines.append(f"    C108 gegen C109: {check(0xC108, 0xC109)}")

    lines += ["", "--- Dateisignaturen (mit dem Schlüssel aus C101)"]
    sign_key = keys.get(0xC101, (None,))[0]
    if sign_key is None:
        lines.append("    C101 fehlt oder ist nicht lesbar")
    else:
        lines.append(f"    Hash nach Schlüssellänge: {sign_key.hash_name}")
        ok = bad = 0
        for fid, app, data in ddd.entries:
            if app != 2 or fid in CERT_NAMES:
                continue
            sig = ddd.get(fid, 3)
            if not sig:
                continue
            state = verify_gen2_data(data, sig, sign_key).state
            if state == "ok":
                ok += 1
            else:
                bad += 1
                lines.append(f"    {fid:04X}: nicht bestätigt "
                             f"(Daten {len(data)} Byte, Signatur {len(sig)} Byte)")
        lines.append(f"    bestätigt: {ok}, nicht bestätigt: {bad}")
    lines += ["", "Diese Ausgabe enthält keine Fahrerdaten – nur Längen, Kennungen und "
              "Prüfergebnisse."]
    return lines
