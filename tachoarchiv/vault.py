"""Zugangsschutz für das Archiv.

Hintergrund: Mehrere Leute teilen sich oft ein Benutzerkonto. Dateirechte
trennen dann niemanden – wer den Ordner öffnet, hat die Dateien. Schutz bietet
nur Verschlüsselung.

Aufbau: ein zufälliger Archivschlüssel (32 Byte) verschlüsselt die Dateien mit
AES-256-GCM. Der Archivschlüssel selbst liegt mehrfach umschlossen in
``zugang.json`` – einmal unter dem Passwort, einmal unter dem
Wiederherstellungsschlüssel. So lässt sich das Passwort ändern, ohne das
Archiv neu zu verschlüsseln.

Was das leistet und was nicht: Ohne Passwort sind die Dateien unlesbar, auch
im selben Benutzerkonto. Solange das Archiv entsperrt ist, kommt jeder an die
Daten, der an den laufenden Rechner kommt. Gegen Schadprogramme mit
Administratorrechten hilft nur die Verschlüsselung des Datenträgers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:                      # ohne das Paket läuft alles außer dem Schutz
    AESGCM = None

MAGIC = b"TAV1"
NONCE = 12
KEY = 32
# scrypt-Parameter: rund 100 ms auf einem heutigen Rechner, 64 MB Speicher.
SCRYPT = {"n": 1 << 16, "r": 8, "p": 1, "dklen": KEY, "maxmem": 128 * 1024 * 1024}
CONFIG = "zugang.json"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # ohne I/O/0/1 – besser abzuschreiben


class VaultError(Exception):
    pass


class NotAvailable(VaultError):
    """Das Paket python3-cryptography fehlt – ohne es gibt es keine Verschlüsselung."""


def available() -> bool:
    return AESGCM is not None


class LockedError(VaultError):
    """Das Archiv ist verschlüsselt und derzeit gesperrt."""


class WrongSecret(VaultError):
    """Passwort oder Wiederherstellungsschlüssel passt nicht."""


def make_recovery_key() -> str:
    """20 Zeichen in Vierergruppen – zum Ausdrucken und Abschreiben."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(20))
    return "-".join(raw[i:i + 4] for i in range(0, 20, 4))


def _normalise(secret: str) -> str:
    """Wiederherstellungsschlüssel tolerant lesen (Bindestriche, Klein-/Großschreibung)."""
    plain = secret.replace("-", "").replace(" ", "").upper()
    if len(plain) == 20 and all(c in ALPHABET for c in plain):
        return plain
    return secret


def _derive(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(_normalise(secret).encode("utf-8"), salt=salt, **SCRYPT)


def _wrap(key: bytes, secret: str) -> dict:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(NONCE)
    ct = AESGCM(_derive(secret, salt)).encrypt(nonce, key, None)
    return {"salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
            "key": base64.b64encode(ct).decode()}


def _unwrap(entry: dict, secret: str) -> bytes:
    try:
        return AESGCM(_derive(secret, base64.b64decode(entry["salt"]))).decrypt(
            base64.b64decode(entry["nonce"]), base64.b64decode(entry["key"]), None)
    except Exception as e:                       # bewusst breit: jeder Fehlschlag ist "passt nicht"
        raise WrongSecret() from e


class Vault:
    """Verwaltet Schlüssel und Zustand; verschlüsselt einzelne Dateien."""

    def __init__(self, base: str | os.PathLike):
        self.base = Path(base)
        self._key: bytes | None = None
        self._config = self._read_config()

    # ------------------------------------------------------------------ Zustand
    def _read_config(self) -> dict:
        try:
            return json.loads((self.base / CONFIG).read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_config(self, data: dict) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        path = self.base / CONFIG
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        self._config = data

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("wrapped"))

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    @property
    def ready(self) -> bool:
        """Darf gelesen und geschrieben werden?"""
        return (not self.enabled) or self.unlocked

    # ------------------------------------------------------------------ Schlüssel
    def enable(self, password: str) -> str:
        """Schutz einschalten. Gibt den Wiederherstellungsschlüssel zurück – einmalig."""
        if not available():
            raise NotAvailable()
        if self.enabled:
            raise VaultError("already enabled")
        if len(password) < 8:
            raise VaultError("password too short")
        key = secrets.token_bytes(KEY)
        recovery = make_recovery_key()
        self._write_config({"version": 1, "kdf": "scrypt",
                            "wrapped": {"password": _wrap(key, password),
                                        "recovery": _wrap(key, recovery)}})
        self._key = key
        self._protect_folder(True)
        return recovery

    def disable(self) -> None:
        if not self.unlocked:
            raise LockedError()
        self._key = None
        try:
            (self.base / CONFIG).unlink()
        except OSError:
            pass
        self._config = {}
        self._protect_folder(False)

    def unlock(self, secret: str) -> None:
        if not self.enabled:
            return
        if not available():
            raise NotAvailable()
        last = WrongSecret()
        for name in ("password", "recovery"):
            entry = self._config["wrapped"].get(name)
            if not entry:
                continue
            try:
                self._key = _unwrap(entry, secret)
                return
            except WrongSecret as e:
                last = e
        raise last

    def lock(self) -> None:
        self._key = None

    def change_password(self, new: str) -> None:
        if not self.unlocked:
            raise LockedError()
        if len(new) < 8:
            raise VaultError("password too short")
        data = dict(self._config)
        data["wrapped"] = dict(data["wrapped"], password=_wrap(self._key, new))
        self._write_config(data)

    def new_recovery_key(self) -> str:
        """Ersetzt den alten Wiederherstellungsschlüssel – der gilt danach nicht mehr."""
        if not self.unlocked:
            raise LockedError()
        recovery = make_recovery_key()
        data = dict(self._config)
        data["wrapped"] = dict(data["wrapped"], recovery=_wrap(self._key, recovery))
        self._write_config(data)
        return recovery

    def _protect_folder(self, on: bool) -> None:
        """Zusätzlich die Ordnerrechte enger ziehen – schadet nicht, trennt aber kein
        gemeinsames Benutzerkonto. Der eigentliche Schutz ist die Verschlüsselung."""
        try:
            os.chmod(self.base, 0o700 if on else 0o755)
        except OSError:
            pass

    # ------------------------------------------------------------------ Dateien
    def encrypt(self, raw: bytes) -> bytes:
        if not self.enabled:
            return raw
        if not self.unlocked:
            raise LockedError()
        nonce = secrets.token_bytes(NONCE)
        return MAGIC + nonce + AESGCM(self._key).encrypt(nonce, raw, None)

    def decrypt(self, raw: bytes) -> bytes:
        """Entschlüsselt, wenn nötig. Unverschlüsselte Dateien kommen unverändert zurück."""
        if not raw.startswith(MAGIC):
            return raw
        if not self.unlocked:
            raise LockedError()
        try:
            return AESGCM(self._key).decrypt(raw[len(MAGIC):len(MAGIC) + NONCE],
                                             raw[len(MAGIC) + NONCE:], None)
        except Exception as e:
            raise VaultError("archive file damaged") from e

    @staticmethod
    def is_encrypted(raw: bytes) -> bool:
        return raw.startswith(MAGIC)
