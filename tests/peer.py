"""Thin pyserial wrapper for the external USB-to-serial adapter wired to one
nt124 port -- the "other end of the wire" in a hardware-in-the-loop test.

Mirrors nt124usb.Port's ergonomics (context manager, open/close, write /
read_payload) so test code reads symmetrically regardless of which end of
the link it's talking to.
"""
from __future__ import annotations

import time

import serial

_PARITY = {"n": serial.PARITY_NONE, "o": serial.PARITY_ODD, "e": serial.PARITY_EVEN}
_STOPBITS = {1.0: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
             2.0: serial.STOPBITS_TWO}


class Peer:
    """One external USB-to-serial adapter, wired to one nt124 port."""

    def __init__(self, device_path: str, baud: int = 115200):
        self.device_path = device_path
        self._baud = baud
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        self._ser = serial.Serial(
            port=self.device_path,
            baudrate=self._baud,
            timeout=0.2,
            write_timeout=2.0,
        )
        # Assert RTS/DTR so the nt124 side sees CTS/DSR ready, unless a test
        # is deliberately exercising flow control / modem lines.
        self._ser.rts = True
        self._ser.dtr = True

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self) -> "Peer":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def configure(self, baud: int, databits: int = 8, parity: str = "n",
                  stopbits: float = 1.0) -> None:
        """Change line settings on an already-open port (match the nt124 side)."""
        self._ser.baudrate = baud
        self._ser.bytesize = databits
        self._ser.parity = _PARITY[parity]
        self._ser.stopbits = _STOPBITS[stopbits]

    # -- data plane -----------------------------------------------------
    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def read_available(self) -> bytes:
        """Read whatever is currently buffered, blocking briefly (up to the
        port's read timeout) if nothing is waiting yet -- avoids a tight
        spin loop in an echo thread."""
        n = self._ser.in_waiting or 1
        return self._ser.read(n)

    def flush_input(self) -> None:
        """Discard anything currently buffered, so a subsequent read only
        sees bytes that arrive from here on."""
        self._ser.reset_input_buffer()

    def read_until_quiet(self, quiet: float = 0.3, max_wait: float = 3.0) -> bytes:
        """Accumulate bytes until nothing new arrives for `quiet` seconds, or
        `max_wait` total elapses. For one-way tests where the receiver
        doesn't know the exact byte count up front, just that the sender is
        done."""
        out = bytearray()
        deadline = time.monotonic() + max_wait
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            chunk = self.read_available()
            if chunk:
                out.extend(chunk)
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since > quiet:
                break
        return bytes(out)

    def read_payload(self, nbytes: int, timeout: float = 2.0) -> bytes:
        """Accumulate at least `nbytes`, giving up after `timeout`s of
        silence (the deadline resets whenever data arrives)."""
        out = bytearray()
        deadline = time.monotonic() + timeout
        while len(out) < nbytes and time.monotonic() < deadline:
            chunk = self._ser.read(min(4096, nbytes - len(out)))
            if chunk:
                out.extend(chunk)
                deadline = time.monotonic() + timeout
        return bytes(out)

    # -- modem lines ------------------------------------------------------
    @property
    def cts(self) -> bool: return self._ser.cts

    @property
    def dsr(self) -> bool: return self._ser.dsr

    @property
    def dcd(self) -> bool: return self._ser.cd

    @property
    def ri(self) -> bool: return self._ser.ri

    def set_rts(self, value: bool) -> None: self._ser.rts = value

    def set_dtr(self, value: bool) -> None: self._ser.dtr = value
