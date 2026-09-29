"""One-way RX smoke test via the DMA buffer-full path: the peer writes
exactly RX_BUFFER_SIZE (29) bytes, filling nt124's RX DMA buffer exactly
once, and nt124 reads it back. Isolates uart_RX_DMA() + process_rx() +
send_rx() on the buffer-full trigger specifically, as opposed to the
idle-gap timer (see test_RS232_rx_idle_flush.py) or TX (see test_RS232_tx_basic.py).

Requires TX/RX wired between each nt124 port and its peer, and the
transceiver set to a mode that reaches the external bus -- see
transceiver.py.

Run directly:
    python test_RS232_rx_buffer_flush.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, rx_one_way  # noqa: E402

RX_BUFFER_SIZE = 29  # CDCACM_PACKET_SIZE(32) - 3, from src/project/platform/platform.h


class TestRxBufferFlush(PeerTestCase):

    def test_exact_buffer_via_dma_full(self) -> None:
        pattern = bytes(i & 0xFF for i in range(RX_BUFFER_SIZE))
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
