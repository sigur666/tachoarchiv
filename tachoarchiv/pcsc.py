"""Minimaler PC/SC-Zugriff über ctypes (pcsc-lite).

Keine externen Python-Pakete nötig. Im Flatpak wird der Socket des
Host-pcscd über ``--socket=pcsc`` durchgereicht.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from ctypes import POINTER, byref, c_char_p, c_long, c_ubyte, c_ulong, c_void_p

SCARD_S_SUCCESS = 0x00000000
SCARD_E_NO_SMARTCARD = 0x8010000C
SCARD_E_NO_SERVICE = 0x8010001D
SCARD_E_SERVICE_STOPPED = 0x8010001E
SCARD_E_NO_READERS_AVAILABLE = 0x8010002E
SCARD_W_REMOVED_CARD = 0x80100069
SCARD_W_UNRESPONSIVE_CARD = 0x80100066

SCARD_SCOPE_SYSTEM = 2
SCARD_SHARE_SHARED = 2
SCARD_PROTOCOL_T0 = 1
SCARD_PROTOCOL_T1 = 2
SCARD_LEAVE_CARD = 0


class PCSCError(Exception):
    def __init__(self, func: str, code: int):
        self.func = func
        self.code = code & 0xFFFFFFFF
        super().__init__(f"{func}: 0x{self.code:08X}")

    @property
    def no_service(self) -> bool:
        return self.code in (SCARD_E_NO_SERVICE, SCARD_E_SERVICE_STOPPED) or self.func == "load"

    @property
    def no_card(self) -> bool:
        return self.code in (SCARD_E_NO_SMARTCARD, SCARD_W_REMOVED_CARD, SCARD_W_UNRESPONSIVE_CARD)


class _IoRequest(ctypes.Structure):
    _fields_ = [("dwProtocol", c_ulong), ("cbPciLength", c_ulong)]


_LIB = None


def _lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    candidates = [
        os.environ.get("TACHOARCHIV_PCSCLIB"),
        "/app/lib/libpcsclite.so.1",
        ctypes.util.find_library("pcsclite"),
        "libpcsclite.so.1",
        "libpcsclite.so",
    ]
    for cand in candidates:
        if not cand:
            continue
        try:
            lib = ctypes.CDLL(cand)
            break
        except OSError:
            continue
    else:
        raise PCSCError("load", SCARD_E_NO_SERVICE)

    lib.SCardEstablishContext.argtypes = [c_ulong, c_void_p, c_void_p, POINTER(c_long)]
    lib.SCardEstablishContext.restype = c_long
    lib.SCardReleaseContext.argtypes = [c_long]
    lib.SCardReleaseContext.restype = c_long
    lib.SCardListReaders.argtypes = [c_long, c_char_p, c_char_p, POINTER(c_ulong)]
    lib.SCardListReaders.restype = c_long
    lib.SCardConnect.argtypes = [c_long, c_char_p, c_ulong, c_ulong, POINTER(c_long), POINTER(c_ulong)]
    lib.SCardConnect.restype = c_long
    lib.SCardDisconnect.argtypes = [c_long, c_ulong]
    lib.SCardDisconnect.restype = c_long
    lib.SCardBeginTransaction.argtypes = [c_long]
    lib.SCardBeginTransaction.restype = c_long
    lib.SCardEndTransaction.argtypes = [c_long, c_ulong]
    lib.SCardEndTransaction.restype = c_long
    lib.SCardTransmit.argtypes = [c_long, POINTER(_IoRequest), POINTER(c_ubyte), c_ulong,
                                  POINTER(_IoRequest), POINTER(c_ubyte), POINTER(c_ulong)]
    lib.SCardTransmit.restype = c_long
    lib.SCardStatus.argtypes = [c_long, c_char_p, POINTER(c_ulong), POINTER(c_ulong),
                                POINTER(c_ulong), POINTER(c_ubyte), POINTER(c_ulong)]
    lib.SCardStatus.restype = c_long
    _LIB = lib
    return lib


def _check(func: str, rv: int) -> None:
    if (rv & 0xFFFFFFFF) != SCARD_S_SUCCESS:
        raise PCSCError(func, rv)


class Card:
    def __init__(self, ctx: "PCSC", handle: c_long, protocol: int):
        self._ctx = ctx
        self._handle = handle
        self._protocol = protocol
        self._buf = (c_ubyte * 65538)()

    def _raw(self, apdu: bytes) -> tuple[bytes, int]:
        lib = _lib()
        send = (c_ubyte * len(apdu)).from_buffer_copy(apdu)
        rlen = c_ulong(len(self._buf))
        pci = _IoRequest(self._protocol, ctypes.sizeof(_IoRequest))
        rv = lib.SCardTransmit(self._handle, byref(pci), send, len(apdu), None, self._buf, byref(rlen))
        _check("SCardTransmit", rv)
        resp = bytes(self._buf[: rlen.value])
        if len(resp) < 2:
            raise PCSCError("SCardTransmit", SCARD_W_UNRESPONSIVE_CARD)
        return resp[:-2], (resp[-2] << 8) | resp[-1]

    def transmit(self, apdu: bytes) -> tuple[bytes, int]:
        data, sw = self._raw(apdu)
        if (sw >> 8) == 0x6C and len(apdu) >= 5:
            data, sw = self._raw(apdu[:-1] + bytes([sw & 0xFF]))
        out = bytearray(data)
        while (sw >> 8) == 0x61:
            data, sw = self._raw(bytes([0x00, 0xC0, 0x00, 0x00, sw & 0xFF]))
            out += data
        return bytes(out), sw

    @property
    def protocol(self) -> str:
        return {SCARD_PROTOCOL_T0: "T=0", SCARD_PROTOCOL_T1: "T=1"}.get(self._protocol, "?")

    def atr(self) -> bytes:
        """Antwort-auf-Reset der Karte; leer, wenn der Treiber sie nicht liefert."""
        lib = _lib()
        atr = (c_ubyte * 33)()
        alen = c_ulong(len(atr))
        rlen, state, proto = c_ulong(0), c_ulong(0), c_ulong(0)
        rv = lib.SCardStatus(self._handle, None, byref(rlen), byref(state), byref(proto),
                             atr, byref(alen))
        if (rv & 0xFFFFFFFF) != SCARD_S_SUCCESS:
            return b""
        return bytes(atr[: alen.value])

    def begin(self) -> None:
        _check("SCardBeginTransaction", _lib().SCardBeginTransaction(self._handle))

    def end(self) -> None:
        _lib().SCardEndTransaction(self._handle, SCARD_LEAVE_CARD)

    def close(self) -> None:
        if self._handle is not None:
            _lib().SCardDisconnect(self._handle, SCARD_LEAVE_CARD)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PCSC:
    def __init__(self):
        lib = _lib()
        self._ctx = c_long(0)
        _check("SCardEstablishContext", lib.SCardEstablishContext(SCARD_SCOPE_SYSTEM, None, None, byref(self._ctx)))

    def readers(self) -> list[str]:
        lib = _lib()
        size = c_ulong(0)
        rv = lib.SCardListReaders(self._ctx, None, None, byref(size))
        if (rv & 0xFFFFFFFF) == SCARD_E_NO_READERS_AVAILABLE:
            return []
        _check("SCardListReaders", rv)
        buf = ctypes.create_string_buffer(size.value)
        rv = lib.SCardListReaders(self._ctx, None, buf, byref(size))
        if (rv & 0xFFFFFFFF) == SCARD_E_NO_READERS_AVAILABLE:
            return []
        _check("SCardListReaders", rv)
        return [r.decode("utf-8", "replace") for r in buf.raw[: size.value].split(b"\0") if r]

    def connect(self, reader: str) -> Card:
        handle = c_long(0)
        proto = c_ulong(0)
        rv = _lib().SCardConnect(self._ctx, reader.encode(), SCARD_SHARE_SHARED,
                                 SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1, byref(handle), byref(proto))
        _check("SCardConnect", rv)
        return Card(self, handle, proto.value)

    def close(self) -> None:
        if self._ctx is not None:
            _lib().SCardReleaseContext(self._ctx)
            self._ctx = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
