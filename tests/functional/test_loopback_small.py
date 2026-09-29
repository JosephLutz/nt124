"""Small, single-packet full round trip: nt124 writes, the peer echoes
back, nt124 reads -- the same mechanism as tests/stress/test_loopback_bulk.py,
but with a payload small enough (well under RX_BUFFER_SIZE) to stay on the
simple, single-packet happy path. This is the baseline round-trip check;
volume/backpressure testing lives in tests/stress/.

Requires TX/RX wired between each nt124 port and its peer, and the
transceiver set to a mode that reaches the external bus -- see
transceiver.py.

Run directly:
    python test_loopback_small.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402


class TestLoopbackSmall(PeerTestCase):

    def test_small_round_trip(self) -> None:
        pattern = bytes(range(16))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                received, packets, echoed = loopback_via_peer(
                    port, peer, pattern, timeout=2000)

                self.assertEqual(echoed, pattern,
                                  f"port {index}: peer only saw {echoed!r}")
                self.assertEqual(received, pattern,
                                  f"port {index}: nt124 got back {received!r}")
                bad = [p for p in packets if p.line_error]
                self.assertFalse(bad, f"port {index}: line errors: "
                                       f"{[p.describe() for p in bad]}")


if __name__ == "__main__":
    unittest.main()
