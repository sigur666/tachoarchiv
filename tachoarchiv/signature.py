"""Prüfung der Kartensignaturen (Anhang IC, Anlage 11).

Wie die Kette aufgebaut ist
---------------------------
Jede signierte Datei eines Downloads trägt eine Signatur, erzeugt mit dem
privaten Schlüssel der Karte. Der öffentliche Schlüssel der Karte steckt im
Kartenzertifikat (EF 0xC100), das vom Mitgliedstaat signiert ist; dessen
Zertifikat (EF 0xC108) ist von der europäischen Wurzelinstanz ERCA signiert.

Daraus folgt etwas Unbequemes: **ohne den öffentlichen Wurzelschlüssel der ERCA
lässt sich gar nichts prüfen.** Bei Generation 1 steckt der öffentliche Schlüssel
eines Zertifikats innerhalb der Signatur und wird erst durch das Nachrechnen mit
dem Schlüssel des Ausstellers sichtbar. Fehlt der Wurzelschlüssel, bleibt die
Kette zu – dann meldet dieses Modul ``no_root`` und behauptet nichts.

Der Wurzelschlüssel wird nicht mitgeliefert: er ist amtlich und soll aus
amtlicher Quelle kommen. Wo er hingehört, steht in der README.

Was die Prüfung aussagt
-----------------------
Sie sagt, dass die Daten seit dem Auslesen unverändert sind und von einer Karte
stammen, deren Zertifikat sich auf die hinterlegte Wurzel zurückführen lässt.
Sie ersetzt keine zertifizierte Kontrollsoftware. Ein Fehlschlag heißt hier
nie „gefälscht", sondern „nicht bestätigt" – mit Grund.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from .ddd import G1_FILES, G2_FILES, DddFile

# Zustände einer Prüfung
OK = "ok"                      # Signatur bestätigt
FAILED = "failed"              # Signatur passt nicht zu den Daten
NO_ROOT = "no_root"            # Wurzelschlüssel fehlt – nicht prüfbar
UNSUPPORTED = "unsupported"    # Format nicht gelesen – nicht prüfbar
NO_SIG = "no_sig"              # keine Signatur vorhanden
PARTIAL = "partial"            # Daten bestätigt, aber nicht bis zur Wurzel

CERT_LEN = 194                 # Gen 1: 128 Signatur + 58 Rest + 8 CAR
SIG_LEN = 128
RECOVERED = 106                # Teil der Nachricht, der in der Signatur steckt
HASH_LEN = 20                  # SHA-1


@dataclass
class Status:
    state: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.state == OK

    @property
    def checkable(self) -> bool:
        return self.state in (OK, FAILED, PARTIAL)


@dataclass
class Gen1Key:
    """Öffentlicher RSA-Schlüssel mit seiner Kennung (CHR)."""
    chr: bytes
    n: int
    e: int


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _recover(sig: bytes, key: Gen1Key) -> bytes | None:
    """ISO 9796-2: aus der Signatur den wiederherstellbaren Teil zurückrechnen."""
    if len(sig) != SIG_LEN:
        return None
    x = pow(_int(sig), key.e, key.n).to_bytes(SIG_LEN, "big")
    if x[0] != 0x6A or x[-1] != 0xBC:
        return None
    return x[1:1 + RECOVERED + HASH_LEN]        # Cr || H


def parse_gen1_certificate(cert: bytes, issuer: Gen1Key) -> Gen1Key | None:
    """Rechnet ein Zertifikat der Generation 1 mit dem Schlüssel des Ausstellers auf.

    Der Inhalt ergibt sich aus dem wiederhergestellten Teil und dem Klartextrest;
    stimmt der mitgeführte SHA-1 nicht, ist das Zertifikat nicht echt.
    """
    if len(cert) != CERT_LEN:
        return None
    body = _recover(cert[:SIG_LEN], issuer)
    if body is None:
        return None
    cr, h = body[:RECOVERED], body[RECOVERED:]
    content = cr + cert[SIG_LEN:SIG_LEN + 58]   # Cr || Cn'
    if hashlib.sha1(content).digest() != h:
        return None
    # CPI(1) CAR(8) CHA(7) EOV(4) CHR(8) n(128) e(8)
    return Gen1Key(chr=content[20:28], n=_int(content[28:156]), e=_int(content[156:164]))


def verify_gen1_data(data: bytes, sig: bytes, key: Gen1Key) -> Status:
    """Prüft die Signatur einer Datei gegen den öffentlichen Schlüssel der Karte."""
    body = _recover(sig, key)
    if body is None:
        return Status(UNSUPPORTED, "signature format")
    recovered, h = body[:RECOVERED], body[RECOVERED:]
    if hashlib.sha1(data).digest() != h:
        return Status(FAILED, "hash mismatch")
    # Der wiederherstellbare Teil trägt den Anfang der Daten. Manche Geräte
    # füllen ihn abweichend; der Hash ist das Entscheidende, deshalb nur ein
    # zusätzlicher Hinweis und kein Fehlschlag.
    if len(data) >= RECOVERED and recovered != data[:RECOVERED]:
        return Status(OK, "recovered part differs")
    return Status(OK)


SYSTEM_ROOTS = ("/usr/local/share/tachoarchiv/erca", "/usr/share/tachoarchiv/erca")


class RootStore:
    """Hinterlegte Wurzelschlüssel der ERCA.

    Gesucht wird in mehreren Ordnern: zuerst im Archiv des Benutzers, dann an den
    systemweiten Stellen. So kann ein Rechner die Zertifikate einmal für alle
    Benutzer vorhalten, und wer das Programm weitergibt, kann sie beilegen.

    Erkannt wird am Inhalt: Generation 2 als Zertifikat (beginnt mit 7F 21),
    Generation 1 als 144 Byte (8 Byte Kennung, 128 Byte Modulus, 8 Byte Exponent)
    oder 136 Byte ohne Kennung.
    """

    def __init__(self, folder=None, system: bool = True):
        folders = []
        if folder is not None:
            folders += [Path(f) for f in (folder if isinstance(folder, (list, tuple)) else [folder])]
        if system:
            folders += [Path(f) for f in SYSTEM_ROOTS]
        self.folders = folders
        self.folder = folders[0] if folders else None
        self.sources: list[tuple[Path, str]] = []
        self.gen1: list[Gen1Key] = []
        self.gen2: list[Gen2Key] = []
        seen = set()
        for base in folders:
            if not base.is_dir():
                continue
            for path in sorted(base.iterdir()):
                if path.is_file():
                    self._load(path, seen)

    def _load(self, path: Path, seen: set | None = None) -> None:
        """Erkennt am Inhalt, worum es sich handelt – der Dateiname ist beliebig."""
        try:
            raw = path.read_bytes()
        except OSError:
            return
        digest = hashlib.sha256(raw).hexdigest()
        if seen is not None:
            if digest in seen:          # dieselbe Datei in mehreren Ordnern
                return
            seen.add(digest)
        if len(raw) == 144:
            self.gen1.append(Gen1Key(raw[:8], _int(raw[8:136]), _int(raw[136:144])))
            self.sources.append((path, digest))
            return
        if len(raw) == 136:
            self.gen1.append(Gen1Key(b"\xff" * 8, _int(raw[:128]), _int(raw[128:136])))
            self.sources.append((path, digest))
            return
        key = parse_gen2_certificate(raw)       # Wurzelzertifikat, selbst signiert
        if key is not None:
            self.gen2.append(key)
            self.sources.append((path, digest))

    @property
    def empty(self) -> bool:
        return not (self.gen1 or self.gen2)

    def find(self, car: bytes) -> Gen1Key | None:
        """Wurzelschlüssel zur Ausstellerkennung; ohne Kennung der erste passende."""
        for key in self.gen1:
            if key.chr == car or key.chr == b"\xff" * 8:
                return key
        return None

    def find_gen2(self, car: bytes) -> Gen2Key | None:
        for key in self.gen2:
            if key.chr == car:
                return key
        return None


def _car_of(cert: bytes) -> bytes:
    """Die Kennung des Ausstellers steht im Klartext am Ende des Zertifikats."""
    return cert[-8:] if len(cert) == CERT_LEN else b""


# --------------------------------------------------------------- Generation 2

"""Smart Tachograph (Anlage 11 Teil B).

Zertifikate sind hier „card verifiable certificates" in BER-TLV:

    7F21  Zertifikat
      7F4E  Rumpf            <- darüber wird signiert
        5F29 Profilkennung
        42   Aussteller (CAR)
        7F49 Schlüssel: 06 Kurven-OID, 86 Punkt (04||X||Y)
        5F20 Inhaber (CHR)
        7F4C Berechtigung, 5F25/5F24 Gültigkeit
      5F37  Signatur (r||s, roh)

Die Dateien eines Downloads sind mit dem Schlüssel aus dem **Signaturzertifikat**
der Karte (EF 0xC101) signiert, nicht mit dem für die gegenseitige
Authentisierung (0xC100).
"""

TAG_CERT = 0x7F21
TAG_BODY = 0x7F4E
TAG_CAR = 0x42
TAG_PK = 0x7F49
TAG_OID = 0x06
TAG_POINT = 0x86
TAG_CHR = 0x5F20
TAG_SIG = 0x5F37

# Kurven nach Anlage 11; der Hash richtet sich nach der Schlüssellänge.
CURVES = {
    "1.2.840.10045.3.1.7": ("SECP256R1", 256),
    "1.3.132.0.34": ("SECP384R1", 384),
    "1.3.132.0.35": ("SECP521R1", 521),
    "1.3.36.3.3.2.8.1.1.7": ("BrainpoolP256R1", 256),
    "1.3.36.3.3.2.8.1.1.11": ("BrainpoolP384R1", 384),
    "1.3.36.3.3.2.8.1.1.13": ("BrainpoolP512R1", 512),
}


@dataclass
class Gen2Key:
    """Öffentlicher Schlüssel eines Gen-2-Zertifikats."""
    chr: bytes
    car: bytes
    curve: str
    point: bytes
    bits: int

    @property
    def hash_name(self) -> str:
        return "sha256" if self.bits <= 256 else ("sha384" if self.bits <= 384 else "sha512")


def _tlv(data: bytes) -> list[tuple[int, bytes]]:
    """BER-TLV, so weit wie hier gebraucht: Mehrbyte-Kennungen und lange Längen."""
    out = []
    i = 0
    while i < len(data):
        tag = data[i]
        i += 1
        if tag & 0x1F == 0x1F:                      # Kennung geht weiter
            tag = (tag << 8) | data[i]
            i += 1
        if i >= len(data):
            break
        ln = data[i]
        i += 1
        if ln & 0x80:
            count = ln & 0x7F
            if count == 0 or i + count > len(data):
                break
            ln = int.from_bytes(data[i:i + count], "big")
            i += count
        if i + ln > len(data):
            break
        out.append((tag, data[i:i + ln]))
        i += ln
    return out


def _find(items, tag):
    for t, v in items:
        if t == tag:
            return v
    return None


def _oid(raw: bytes) -> str:
    """OID aus der DER-Darstellung – die Kurve steht als solche im Zertifikat."""
    if not raw:
        return ""
    parts = [str(raw[0] // 40), str(raw[0] % 40)]
    value = 0
    for b in raw[1:]:
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(str(value))
            value = 0
    return ".".join(parts)


def _split_cert(cert: bytes) -> tuple[bytes, bytes, bytes] | None:
    """Liefert (Rumpf-TLV, Rumpfinhalt, Signatur)."""
    items = _tlv(cert)
    inner = _find(items, TAG_CERT)
    if inner is not None:
        items = _tlv(inner)
    body = _find(items, TAG_BODY)
    sig = _find(items, TAG_SIG)
    if body is None or sig is None:
        return None
    # Über den Rumpf wird einschließlich seiner Kennung und Länge signiert.
    start = (inner or cert).find(body)
    header = 2 + (1 if len(body) < 0x80 else 1 + (len(body).bit_length() + 7) // 8)
    body_tlv = (inner or cert)[max(start - header, 0):start + len(body)]
    return body_tlv, body, sig


def _key_from_body(body: bytes) -> Gen2Key | None:
    items = _tlv(body)
    pk = _find(items, TAG_PK)
    if pk is None:
        return None
    inner = _tlv(pk)
    oid = _oid(_find(inner, TAG_OID) or b"")
    point = _find(inner, TAG_POINT)
    if oid not in CURVES or not point or point[0] != 0x04:
        return None
    curve, bits = CURVES[oid]
    return Gen2Key(chr=_find(items, TAG_CHR) or b"", car=_find(items, TAG_CAR) or b"",
                   curve=curve, point=bytes(point), bits=bits)


def _public_key(key: Gen2Key):
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.EllipticCurvePublicKey.from_encoded_point(getattr(ec, key.curve)(), key.point)


def _verify_ecdsa(key: Gen2Key, signature: bytes, message: bytes) -> bool:
    """Rohe Signatur r||s gegen den Schlüssel prüfen."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    if len(signature) % 2:
        return False
    half = len(signature) // 2
    r = int.from_bytes(signature[:half], "big")
    s_ = int.from_bytes(signature[half:], "big")
    der = utils.encode_dss_signature(r, s_)
    algorithm = {"sha256": hashes.SHA256, "sha384": hashes.SHA384,
                 "sha512": hashes.SHA512}[key.hash_name]()
    try:
        _public_key(key).verify(der, message, ec.ECDSA(algorithm))
        return True
    except (InvalidSignature, ValueError):
        return False


def parse_gen2_certificate(cert: bytes, issuer: "Gen2Key | None" = None) -> Gen2Key | None:
    """Liest ein Gen-2-Zertifikat; mit ``issuer`` wird zusätzlich die Signatur geprüft.

    Ohne Aussteller wird nur gelesen – das ist der Fall für die hinterlegte Wurzel,
    die als Vertrauensanker gilt und sich selbst signiert.
    """
    parts = _split_cert(cert)
    if parts is None:
        return None
    body_tlv, body, sig = parts
    key = _key_from_body(body)
    if key is None:
        return None
    if issuer is not None:
        # Signiert wird der Rumpf einschließlich seiner Kennung 7F4E und der Länge.
        # An einer echten Fahrerkarte bestätigt (10.10.2026); die Lesart ohne Kennung
        # wird nicht mehr zugelassen, sie würde die Prüfung nur aufweichen.
        if not _verify_ecdsa(issuer, sig, body_tlv):
            return None
    return key


def verify_gen2_data(data: bytes, sig: bytes, key: Gen2Key) -> Status:
    if not sig:
        return Status(NO_SIG)
    return Status(OK) if _verify_ecdsa(key, sig, data) else Status(FAILED, "signature mismatch")


def _gen2_card_key(ddd: DddFile, roots: RootStore) -> tuple[Gen2Key | None, Status, bool]:
    """Kette Wurzel -> Mitgliedstaat -> Signaturzertifikat der Karte.

    Anders als bei Generation 1 steht der öffentliche Schlüssel eines Zertifikats
    im Klartext im Rumpf. Deshalb lässt sich auch ohne hinterlegte Wurzel schon
    feststellen, ob die Dateien unverändert sind und ob das Kartenzertifikat
    wirklich vom angegebenen Mitgliedstaat stammt – nur die Wurzel bleibt dann
    unbestätigt. Der dritte Rückgabewert sagt, ob die Kette bis zur Wurzel reicht.

    Signiert werden die Dateien mit dem Schlüssel aus EF 0xC101; 0xC100 gehört zur
    gegenseitigen Authentisierung und taugt dafür nicht.
    """
    sign_cert = ddd.get(0xC101, 2)
    ca_cert = ddd.get(0xC108, 2)
    link_cert = ddd.get(0xC109, 2)
    if not sign_cert:
        return None, Status(UNSUPPORTED, "no card signing certificate"), False
    if not ca_cert:
        return None, Status(UNSUPPORTED, "certificate missing"), False
    ca_body = _split_cert(ca_cert)
    ca_info = _key_from_body(ca_body[1]) if ca_body else None
    if ca_info is None:
        return None, Status(UNSUPPORTED, "member state certificate"), False

    root = roots.find_gen2(ca_info.car)
    if root is None and link_cert:
        # Das Verknüpfungszertifikat trägt den neuen Wurzelschlüssel, signiert mit
        # dem alten. Wer den alten hinterlegt hat, kommt darüber weiter.
        link_body = _split_cert(link_cert)
        link_info = _key_from_body(link_body[1]) if link_body else None
        if link_info is not None:
            old = roots.find_gen2(link_info.car)
            if old is not None and parse_gen2_certificate(link_cert, old) is not None:
                root = link_info if link_info.chr == ca_info.car else None

    if root is None:
        # Ohne Wurzel: so weit prüfen, wie es geht, und das auch so nennen.
        card_key = parse_gen2_certificate(sign_cert, ca_info)
        if card_key is None:
            return None, Status(FAILED, "card certificate"), False
        return card_key, Status(PARTIAL), False

    ca_key = parse_gen2_certificate(ca_cert, root)
    if ca_key is None:
        return None, Status(FAILED, "member state certificate"), False
    card_key = parse_gen2_certificate(sign_cert, ca_key)
    if card_key is None:
        return None, Status(FAILED, "card certificate"), False
    return card_key, Status(OK), True


def verify_card(ddd: DddFile, roots: RootStore) -> dict[int, Status]:
    """Prüft alle signierten Dateien eines Downloads. Schlüssel: FID."""
    gen = ddd.generation
    files = G2_FILES if gen == 2 else G1_FILES
    data_app, sig_app = (2, 3) if gen == 2 else (0, 1)
    result: dict[int, Status] = {}

    if gen == 2:
        key2, problem2, anchored = _gen2_card_key(ddd, roots)
        for fid, signed, _ in files:
            data = ddd.get(fid, data_app)
            if not signed or data is None:
                continue
            sig = ddd.get(fid, sig_app)
            if sig is None:
                result[fid] = Status(NO_SIG)
            elif key2 is None:
                result[fid] = problem2
            else:
                state = verify_gen2_data(data, sig, key2)
                if state.state == OK and not anchored:
                    state = Status(PARTIAL, "root not confirmed")
                result[fid] = state
        return result

    card_cert = ddd.get(0xC100, data_app)
    ca_cert = ddd.get(0xC108, data_app)
    key: Gen1Key | None = None
    problem = Status(NO_ROOT, "no root key")
    if roots.empty:
        problem = Status(NO_ROOT, "no root key")
    elif not card_cert or not ca_cert:
        problem = Status(UNSUPPORTED, "certificate missing")
    else:
        root = roots.find(_car_of(ca_cert))
        if root is None:
            problem = Status(NO_ROOT, "root key does not match")
        else:
            ca_key = parse_gen1_certificate(ca_cert, root)
            if ca_key is None:
                problem = Status(FAILED, "member state certificate")
            else:
                key = parse_gen1_certificate(card_cert, ca_key)
                if key is None:
                    problem = Status(FAILED, "card certificate")

    for fid, signed, _ in files:
        data = ddd.get(fid, data_app)
        if not signed or data is None:
            continue
        sig = ddd.get(fid, sig_app)
        if sig is None:
            result[fid] = Status(NO_SIG)
        elif key is None:
            result[fid] = problem
        else:
            result[fid] = verify_gen1_data(data, sig, key)
    return result


def summary(states: dict[int, Status]) -> Status:
    """Ein Gesamtzustand für die Anzeige – das Schwächste bestimmt."""
    if not states:
        return Status(NO_SIG)
    values = list(states.values())
    if any(s.state == FAILED for s in values):
        return Status(FAILED, next(s.reason for s in values if s.state == FAILED))
    if any(s.state == NO_ROOT for s in values):
        return Status(NO_ROOT)
    if any(s.state == PARTIAL for s in values):
        return Status(PARTIAL)
    if any(s.state == UNSUPPORTED for s in values):
        return Status(UNSUPPORTED, next(s.reason for s in values if s.state == UNSUPPORTED))
    if all(s.state == NO_SIG for s in values):
        return Status(NO_SIG)
    return Status(OK)
