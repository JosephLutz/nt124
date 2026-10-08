"""Packet-size boundary cases not covered elsewhere.

test_RS232_rx_buffer_flush.py checks RX at exactly RX_BUFFER_SIZE (29, the
DMA-buffer-full trigger); this file adds its immediate neighbors (28 -- one
short, must flush via the idle-gap timer instead -- and 30, which must span
a DMA-buffer-full flush plus one more byte flushed by the idle timer) so an
off-by-one at that boundary would actually show up. Similarly for TX at
CDCACM_PACKET_SIZE (32) and its neighbors, and a zero-length write, neither
of which anything else in this suite exercises directly.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_packet_boundaries.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port, rx_one_way, tx_one_way  # noqa: E402

RX_BUFFER_SIZE = 29  # CDCACM_PACKET_SIZE(32) - 3, from src/project/platform/platform.h
CDCACM_PACKET_SIZE = 32


class TestPacketBoundaries(PeerTestCase):

    def test_zero_length_write_does_not_disrupt(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.write(b"")  # must not raise/STALL
                recovered = tx_one_way(port, peer, pattern)
                self.assertEqual(recovered, pattern,
                                  f"port {index}: did not behave normally "
                                  f"after a zero-length write")

    def test_tx_at_packet_size_boundary(self) -> None:
        for size in (CDCACM_PACKET_SIZE - 1, CDCACM_PACKET_SIZE, CDCACM_PACKET_SIZE + 1):
            pattern = bytes(i & 0xFF for i in range(size))
            for index, port, peer in self.each_port_and_peer():
                with self.subTest(size=size, port=index):
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)
                    received = tx_one_way(port, peer, pattern)
                    self.assertEqual(received, pattern,
                                      f"port {index}: {size}-byte TX got "
                                      f"{len(received)} bytes back at the peer")

    def test_rx_at_buffer_size_boundary(self) -> None:
        for size in (RX_BUFFER_SIZE - 1, RX_BUFFER_SIZE + 1):
            pattern = bytes(i & 0xFF for i in range(size))
            for index, port, peer in self.each_port_and_peer():
                with self.subTest(size=size, port=index):
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)
                    # Defensive: a prior test's leftover, undelivered packet
                    # would otherwise show up as unexpected extra bytes
                    # prepended to this read (see drain_port()'s docstring).
                    drain_port(port)
                    received, packets = rx_one_way(port, peer, pattern)
                    self.assertEqual(received, pattern,
                                      f"port {index}: {size}-byte RX got "
                                      f"{len(received)} bytes back")
                    bad = [p for p in packets if p.line_error]
                    self.assertFalse(bad, f"port {index}: line errors: "
                                           f"{[p.describe() for p in bad]}")


if __name__ == "__main__":
    unittest.main()
