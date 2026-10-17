"""DDD-Datei (Fahrerkarten-Download) nach Anhang IC, Anlage 7.

Jeder Eintrag: FID (2 Byte) | Anhang (1 Byte) | Länge (2 Byte) | Daten
Anhang: 0x00 Daten Gen1, 0x01 Signatur Gen1, 0x02 Daten Gen2, 0x03 Signatur Gen2
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# (FID, signiert, optional)
MF_FILES = [(0x0002, False, False), (0x0005, False, False)]

G1_FILES = [
    (0x0501, True, False),   # Application_Identification
    (0xC100, False, False),  # Card_Certificate
    (0xC108, False, False),  # CA_Certificate
    (0x0520, True, False),   # Identification
    (0x050E, True, False),   # Card_Download
    (0x0521, True, True),    # Driving_Licence_Info
    (0x0502, True, False),   # Events_Data
    (0x0503, True, False),   # Faults_Data
    (0x0504, True, False),   # Driver_Activity_Data
    (0x0505, True, False),   # Vehicles_Used
    (0x0506, True, False),   # Places
    (0x0507, True, True),    # Current_Usage
    (0x0508, True, True),    # Control_Activity_Data
    (0x0522, True, True),    # Specific_Conditions
]

G2_FILES = [
    (0x0501, True, False),
    (0xC100, False, False),  # CardMA_Certificate
    (0xC101, False, True),   # CardSignCertificate
    (0xC108, False, False),  # CA_Certificate
    (0xC109, False, True),   # Link_Certificate
    (0x0520, True, False),
    (0x050E, True, False),
    (0x0521, True, True),
    (0x0502, True, False),
    (0x0503, True, False),
    (0x0504, True, False),
    (0x0505, True, False),
    (0x0506, True, False),
    (0x0507, True, True),
    (0x0508, True, True),
    (0x0522, True, True),
    (0x0523, True, True),    # VehicleUnits_Used
    (0x0524, True, True),    # GNSS_Places
    # Gen2 Version 2 (Smart Tachograph 2) – optional
    (0x0525, True, True),
    (0x0526, True, True),
    (0x0527, True, True),
    (0x0528, True, True),
    (0x0529, True, True),
    # 0x0540 (EF_VU_Configuration, Gen 2 V2) bewusst nicht: die Datei enthält
    # Einstellungen für den Fahrtenschreiber, gehört nicht zum Download-Datensatz
    # nach Anlage 7 und ist nur in einer authentisierten Sitzung mit einem
    # Fahrzeuggerät lesbar – Karten antworten sonst mit 6982.
]


class DddError(ValueError):
    pass


@dataclass
class DddFile:
    entries: list[tuple[int, int, bytes]] = field(default_factory=list)

    def add(self, fid: int, appendix: int, data: bytes) -> None:
        self.entries.append((fid, appendix, bytes(data)))

    def get(self, fid: int, appendix: int) -> bytes | None:
        for f, a, d in self.entries:
            if f == fid and a == appendix:
                return d
        return None

    @property
    def generation(self) -> int:
        return 2 if any(a in (2, 3) for _, a, _ in self.entries) else 1

    def to_bytes(self) -> bytes:
        out = bytearray()
        for fid, app, data in self.entries:
            if len(data) > 0xFFFF:
                raise DddError(f"Datei {fid:04X} zu groß")
            out += struct.pack(">HBH", fid, app, len(data)) + data
        return bytes(out)

    @classmethod
    def parse(cls, raw: bytes) -> "DddFile":
        if not raw:
            raise DddError("empty")
        if raw[0] == 0x76:
            raise DddError("vu_file")
        f = cls()
        pos = 0
        while pos + 5 <= len(raw):
            fid, app, ln = struct.unpack_from(">HBH", raw, pos)
            pos += 5
            if app > 3 or pos + ln > len(raw):
                raise DddError(f"invalid entry at offset {pos - 5}")
            f.add(fid, app, raw[pos:pos + ln])
            pos += ln
        if f.get(0x0520, 0) is None and f.get(0x0520, 2) is None:
            raise DddError("no driver card identification")
        return f
