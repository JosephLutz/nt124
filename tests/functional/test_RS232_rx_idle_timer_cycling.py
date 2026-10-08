"""Repeated-cycle RX tests targeting the idle-gap timer (uart_RX_timer(),
uart.c) specifically -- every payload size here is at or straddling the
RX_BUFFER_SIZE boundary, so each cycle exercises the timer's start/
restart/fire sequence (and, for the larger sizes, its handoff with the
DMA-buffer-full path) fresh, repeatedly, rather than just once.
test_RS232_rx_idle_flush.py and test_RS232_packet_boundaries.py each check
a single one-shot transfer at a given size; nothing before this repeated
the cycle or mixed a single byte with a near/over-buffer-sized payload in
the same sequence.

Four scenarios, each run _REPEATS times per port:

1. A single byte, waiting for the idle timer to flush it, repeated.
2. One single-byte cycle, then RX_BUFFER_SIZE-1 bytes (still only reachable
   via the idle timer -- one byte short of a DMA-buffer-full) repeated.
3. One single-byte cycle, then RX_BUFFER_SIZE+1 bytes -- each cycle now
   produces a DMA-buffer-full flush (first RX_BUFFER_SIZE bytes) followed
   immediately by an idle-timer flush (the 1 leftover byte) -- repeated.
4. One single-byte cycle, then 2*RX_BUFFER_SIZE+1 bytes -- each cycle spans
   both ping-pong rx_buffer[] slots (two DMA-buffer-full flushes) plus a
   trailing idle-timer flush for the last byte -- repeated.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_rx_idle_timer_cycling.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port, rx_one_way  # noqa: E402

RX_BUFFER_SIZE = 29  # CDCACM_PACKET_SIZE(32) - 3, from src/project/platform/platform.h
_REPEATS = 10  # adjust for more/less cycling


def _pattern(size: int, salt: int) -> bytes:
    """A size-byte pattern that varies cycle to cycle (via `salt`), so a
    bug that confuses one cycle's leftover data with the next one's would
    actually show up as a mismatch instead of coincidentally matching."""
    return bytes((salt + i) & 0xFF for i in range(size))


class TestRxIdleTimerCycling(PeerTestCase):

    def _run_cycle(self, index, port, peer, size: int, cycle: int) -> None:
        pattern = _pattern(size, cycle)
        with self.subTest(port=index, size=size, cycle=cycle):
            received, packets = rx_one_way(port, peer, pattern)
            self.assertEqual(received, pattern,
                              f"port {index}, cycle {cycle}, size {size}: "
                              f"got {len(received)}/{size} bytes back")
            bad = [p for p in packets if p.line_error]
            self.assertFalse(bad, f"port {index}, cycle {cycle}, size "
                                   f"{size}: line errors: "
                                   f"{[p.describe() for p in bad]}")

    def test_single_byte_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            drain_port(port)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, 1, cycle)

    def test_one_byte_then_near_buffer_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            drain_port(port)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, RX_BUFFER_SIZE - 1, cycle)

    def test_one_byte_then_over_buffer_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            drain_port(port)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, RX_BUFFER_SIZE + 1, cycle)

    def test_one_byte_then_double_buffer_plus_one_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            drain_port(port)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, 2 * RX_BUFFER_SIZE + 1, cycle)


if __name__ == "__main__":
    unittest.main()
