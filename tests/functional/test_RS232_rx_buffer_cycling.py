"""Repeated-cycle RX tests targeting the DMA-buffer-full path (uart_RX_DMA()
/ process_rx(), uart.c) specifically -- every payload size here is an exact
multiple of RX_BUFFER_SIZE, so the idle-gap timer never gets involved (see
test_RS232_rx_idle_timer_cycling.py for the timer-boundary cases); only the
DMA-complete interrupt and the rx_buffer[] ping-pong swap drive each flush.
test_RS232_rx_buffer_flush.py checks exactly this at 1x RX_BUFFER_SIZE, but
only once; nothing before this repeated the send/wait/receive cycle or
pushed it across more than one buffer per cycle.

Three scenarios, each run _REPEATS times per port, sending/waiting/
receiving/sending again each time:

1. Exactly 1x RX_BUFFER_SIZE per cycle -- one DMA-buffer-full flush.
2. Exactly 2x RX_BUFFER_SIZE per cycle -- two consecutive DMA-buffer-full
   flushes per cycle, exercising both ping-pong rx_buffer[] slots back to
   back.
3. Exactly 3x RX_BUFFER_SIZE per cycle -- three consecutive flushes per
   cycle, so the ping-pong index wraps at least once within a single cycle.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_rx_buffer_cycling.py
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


class TestRxBufferCycling(PeerTestCase):

    def _run(self, buffer_multiple: int) -> None:
        size = buffer_multiple * RX_BUFFER_SIZE
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            drain_port(port)
            for cycle in range(_REPEATS):
                pattern = _pattern(size, cycle)
                with self.subTest(port=index, buffers=buffer_multiple, cycle=cycle):
                    received, packets = rx_one_way(port, peer, pattern)
                    self.assertEqual(received, pattern,
                                      f"port {index}, cycle {cycle}, "
                                      f"{buffer_multiple}x buffer: got "
                                      f"{len(received)}/{size} bytes back")
                    bad = [p for p in packets if p.line_error]
                    self.assertFalse(bad, f"port {index}, cycle {cycle}, "
                                           f"{buffer_multiple}x buffer: line "
                                           f"errors: "
                                           f"{[p.describe() for p in bad]}")

    def test_one_full_buffer_repeated(self) -> None:
        self._run(1)

    def test_two_full_buffers_repeated(self) -> None:
        self._run(2)

    def test_three_full_buffers_repeated(self) -> None:
        self._run(3)


if __name__ == "__main__":
    unittest.main()
