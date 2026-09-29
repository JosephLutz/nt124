"""One-way RX smoke test via the idle-gap timer path: the peer writes a
small pattern (fewer bytes than RX_BUFFER_SIZE=29, so the DMA buffer never
fills) and nt124 reads it back after the idle-gap timer flushes it.
Isolates uart_RX() + uart_RX_timer() + send_rx() from the DMA-buffer-full
path and from TX entirely.

Requires TX/RX wired between each nt124 port and its peer, and the
transceiver set to a mode that reaches the external bus -- see
transceiver.py.

Run directly:
    python test_rx_idle_flush.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, rx_one_way  # noqa: E402


class TestRxIdleFlush(PeerTestCase):

    def test_small_pattern_via_idle_timer(self) -> None:
        # Fewer bytes than RX_BUFFER_SIZE (29) -- this can only be flushed
        # by the idle-gap timer, never by the DMA buffer filling.
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                received, packets = rx_one_way(port, peer, pattern)
                self.assertEqual(received, pattern,
                                  f"port {index}: nt124 got {received!r}")
                bad = [p for p in packets if p.line_error]
                self.assertFalse(bad, f"port {index}: line errors: "
                                       f"{[p.describe() for p in bad]}")


if __name__ == "__main__":
    unittest.main()
