"""One-way TX smoke test: nt124 writes a small pattern out a port; the peer
receives it. No round trip, no RX/send_rx() involvement at all -- isolates
the TX path (bulk OUT -> usbuart_usb_out_cb -> ping-pong buffers -> DMA ->
UART TX -> transceiver) from everything else.

This is baseline: if this fails, don't bother chasing round-trip issues
until this passes cleanly. Requires TX/RX wired between each nt124 port and
its peer, and the transceiver set to a mode that reaches the external bus
(e.g. rs232) -- see transceiver.py.

Run directly:
    python test_RS232_tx_basic.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402


class TestTxBasic(PeerTestCase):

    def test_small_pattern_one_way(self) -> None:
        pattern = bytes(range(16))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                received = tx_one_way(port, peer, pattern)
                self.assertEqual(received, pattern,
                                  f"port {index}: peer got {received!r}")


if __name__ == "__main__":
    unittest.main()
