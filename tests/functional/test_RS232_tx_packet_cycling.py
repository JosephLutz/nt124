"""TX-side mirror of test_RS232_rx_idle_timer_cycling.py. TX has no idle-gap
timer at all (that mechanism is RX-only, see uart_RX_timer() in uart.c) --
TX is purely host-driven ping-pong DMA (NUM_TX_BUFFERS=2 buffers of
CDCACM_PACKET_SIZE=32 bytes each, usbuart_usb_out_cb()/uart_TX_DMA_empty()
in uart.c), so "wait for the timer" has no TX equivalent; what's waited on
here instead is the data actually arriving at the peer over the wire.
CDCACM_PACKET_SIZE is the TX unit that plays the role RX_BUFFER_SIZE plays
on the RX side.

Four scenarios, each run _REPEATS times per port:

1. A single byte, repeated.
2. One single-byte cycle, then CDCACM_PACKET_SIZE-1 bytes (fits in one
   ping-pong buffer) repeated.
3. One single-byte cycle, then CDCACM_PACKET_SIZE+1 bytes -- spills one
   byte into the second ping-pong buffer every cycle -- repeated.
4. One single-byte cycle, then 2*CDCACM_PACKET_SIZE+1 bytes -- with only 2
   ping-pong buffers, this is expected to force the TX_FULL state (see
   test_RS232_tx_full_burst.py) on every cycle -- repeated.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_packet_cycling.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402

CDCACM_PACKET_SIZE = 32
_REPEATS = 10  # adjust for more/less cycling


def _pattern(size: int, salt: int) -> bytes:
    """A size-byte pattern that varies cycle to cycle (via `salt`), so a
    bug that confuses one cycle's leftover data with the next one's would
    actually show up as a mismatch instead of coincidentally matching."""
    return bytes((salt + i) & 0xFF for i in range(size))


class TestTxPacketCycling(PeerTestCase):

    def _run_cycle(self, index, port, peer, size: int, cycle: int) -> None:
        pattern = _pattern(size, cycle)
        with self.subTest(port=index, size=size, cycle=cycle):
            received = tx_one_way(port, peer, pattern)
            self.assertEqual(received, pattern,
                              f"port {index}, cycle {cycle}, size {size}: "
                              f"peer got {len(received)}/{size} bytes")

    def test_single_byte_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, 1, cycle)

    def test_one_byte_then_near_packet_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, CDCACM_PACKET_SIZE - 1, cycle)

    def test_one_byte_then_over_packet_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, CDCACM_PACKET_SIZE + 1, cycle)

    def test_one_byte_then_double_packet_plus_one_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            self._run_cycle(index, port, peer, 1, -1)
            for cycle in range(_REPEATS):
                self._run_cycle(index, port, peer, 2 * CDCACM_PACKET_SIZE + 1, cycle)


if __name__ == "__main__":
    unittest.main()
