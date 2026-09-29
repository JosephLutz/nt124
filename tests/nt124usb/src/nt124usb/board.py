"""Ergonomic, high-level access to an nt124 board.

Built on `low.RawPort`. This is the layer tests -- and any other script
that wants to talk to the board -- should actually import.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass

import usb.core

from . import protocol as proto
from .low import RawPort, find_device

_PARITY_CODE = {"n": 0, "o": 1, "e": 2}
_CHAR_FORMAT = {1.0: 0, 1.5: 1, 2.0: 2}
_STATUS_NAMES = (
    (proto.ST_CTS, "CTS"), (proto.ST_DSR, "DSR"), (proto.ST_DCD, "DCD"),
    (proto.ST_RI, "RI"), (proto.ST_TXEMPTY, "TXEMPTY"),
    (proto.ST_FRAMING, "FRAMING"), (proto.ST_PARITY, "PARITY"),
    (proto.ST_OVERRUN, "OVERRUN"), (proto.ST_BRK, "BRK"),
)


@dataclass(frozen=True)
class LineCoding:
    baud: int
    databits: int = 8
    parity: str = "n"      # "n" | "o" | "e"
    stopbits: float = 1.0  # 1 | 1.5 | 2

    def to_bytes(self) -> bytes:
        return struct.pack("<IBBB", self.baud, _CHAR_FORMAT[self.stopbits],
                            _PARITY_CODE[self.parity], self.databits)


@dataclass(frozen=True)
class Packet:
    """One decoded RX (IN) packet: the 2-byte status header plus payload."""
    status: int
    payload: bytes

    @property
    def cts(self) -> bool: return bool(self.status & proto.ST_CTS)

    @property
    def dsr(self) -> bool: return bool(self.status & proto.ST_DSR)

    @property
    def dcd(self) -> bool: return bool(self.status & proto.ST_DCD)

    @property
    def ri(self) -> bool: return bool(self.status & proto.ST_RI)

    @property
    def tx_empty(self) -> bool: return bool(self.status & proto.ST_TXEMPTY)

    @property
    def line_error(self) -> bool: return bool(self.status & proto.ST_LINE_ERRORS)

    def describe(self) -> str:
        names = [name for bit, name in _STATUS_NAMES if self.status & bit]
        return " ".join(names) or "-"


class Port:
    """One nt124 port (0..3). Context manager; safe to use standalone or
    opened together via a `Board`."""

    def __init__(self, raw: RawPort):
        self._raw = raw

    @property
    def index(self) -> int:
        return self._raw.info.index

    @classmethod
    def open(cls, index: int, device: usb.core.Device | None = None) -> "Port":
        if not 0 <= index < proto.NUM_PORTS:
            raise ValueError(f"port index must be 0..{proto.NUM_PORTS - 1}")
        device = device or find_device()
        raw = RawPort(device, proto.PORTS[index])
        raw.claim()
        return cls(raw)

    def close(self) -> None:
        self._raw.release()

    def __enter__(self) -> "Port":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- control plane ------------------------------------------------
    def set_line_coding(self, coding: LineCoding) -> None:
        self._raw.ctrl_out(proto.REQ_SET_LINE_CODING, 0, coding.to_bytes())

    def set_control_lines(self, dtr: bool = True, rts: bool = True) -> None:
        value = (proto.CTRL_DTR if dtr else 0) | (proto.CTRL_RTS if rts else 0)
        self._raw.ctrl_out(proto.REQ_SET_CONTROL_LINE_STATE, value)

    def set_flow_control(self, enabled: bool) -> None:
        self._raw.ctrl_out(proto.REQ_SET_FLOW_CONTROL, 1 if enabled else 0)

    def send_break(self) -> None:
        self._raw.ctrl_out(proto.REQ_SEND_BREAK, 0xFFFF)

    def tx_empty(self) -> bool:
        reply = self._raw.ctrl_in(proto.REQ_GET_TXEMPTY, 0, 1)
        return bool(reply[0]) if reply else False

    def wait_tx_empty(self, timeout: float = 2.0, poll_interval: float = 0.02) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.tx_empty():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_interval)

    # -- data plane -----------------------------------------------------
    def write(self, data: bytes, timeout: int = 2000) -> int:
        return self._raw.bulk_write(data, timeout=timeout)

    def read_packet(self, timeout: int = 1000) -> Packet:
        """Read and decode one IN packet.

        Raises usb.core.USBError (errno ETIMEDOUT) if nothing arrives in time.
        """
        raw = self._raw.bulk_read(timeout=timeout)
        if len(raw) < 2:
            return Packet(status=0, payload=raw)
        return Packet(status=raw[0] | (raw[1] << 8), payload=raw[2:])

    def read_payload(self, nbytes: int, timeout: int = 1000
                      ) -> tuple[bytes, list[Packet]]:
        """Accumulate at least `nbytes` of payload. Stops early on a read
        timeout -- callers can tell "dropped" (short return) from
        "corrupted" (right length, wrong bytes) by comparing against what
        they expected."""
        out = bytearray()
        packets: list[Packet] = []
        while len(out) < nbytes:
            try:
                pkt = self.read_packet(timeout=timeout)
            except usb.core.USBError:
                break
            packets.append(pkt)
            out += pkt.payload
        return bytes(out), packets


class Board:
    """All 4 ports of one nt124 device, for callers that need them together
    (concurrent-port scenarios) or just want one `with` block."""

    def __init__(self, device: usb.core.Device | None = None):
        self.device = device or find_device()
        self._ports: dict[int, Port] = {}

    def port(self, index: int) -> Port:
        if index not in self._ports:
            self._ports[index] = Port.open(index, device=self.device)
        return self._ports[index]

    def ports(self) -> list[Port]:
        return [self.port(i) for i in range(proto.NUM_PORTS)]

    def close(self) -> None:
        for p in self._ports.values():
            p.close()
        self._ports.clear()

    def __enter__(self) -> "Board":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
