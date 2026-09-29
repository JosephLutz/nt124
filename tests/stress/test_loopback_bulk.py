"""Bulk-volume per-port loopback: nt124 writes, the peer adapter echoes
back, nt124 reads -- at 4096 and 65536 bytes, well past a single packet.
Each port is checked independently via subTest, so one port's failure is
reported on its own without hiding or aborting the rest.

STRESS TEST, not baseline: this pushes real volume through the full round
trip (bulk OUT -> UART TX -> DMA -> transceiver -> UART RX -> DMA ->
send_rx -> bulk IN), which is exactly the load under which send_rx()'s
retry/failure-handling path (see SEND_RX_LOCKUP_NOTES.md) has shown real
issues this session. A failure here doesn't mean the board is broadly
broken -- check tests/functional/ first; if those all pass, a failure here
narrows the problem to this specific load pattern. For the single-packet,
low-volume happy path, see tests/functional/test_loopback_small.py.

Requires TX/RX (and ground) wired between each nt124 port and the peer
device configured for it in bench.toml.

Run directly:
    python test_loopback_bulk.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402


class TestLoopback(PeerTestCase):

    def _check(self, index: int, port, peer, size: int) -> None:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(size))

        received, packets, echoed = loopback_via_peer(port, peer, pattern, timeout=3000)

        # Confirm the data actually reached the peer over the real wire --
        # a transceiver stuck in an internal loopback mode can otherwise
        # hand `received` back correctly without the peer seeing anything,
        # silently passing this test without exercising the external path
        # it's supposed to test.
        self.assertEqual(len(echoed), size,
                          f"port {index}: peer only saw {len(echoed)}/{size} bytes -- "
                          f"data isn't reaching the external wire (transceiver stuck "
                          f"in loopback mode? see transceiver.py)")
        self.assertEqual(echoed, pattern, f"port {index}: peer received corrupted data")

        self.assertEqual(len(received), size,
                          f"port {index}: dropped data, got {len(received)}/{size} bytes back")
        self.assertEqual(received, pattern, f"port {index}: corruption")
        bad = [p for p in packets if p.line_error]
        self.assertFalse(bad, f"port {index}: firmware flagged line errors: "
                               f"{[p.describe() for p in bad]}")

    def test_loopback_pattern_intact(self) -> None:
        for size in (4096, 65536):
            for index, port, peer in self.each_port_and_peer():
                with self.subTest(size=size, port=index):
                    self._check(index, port, peer, size)


if __name__ == "__main__":
    unittest.main()
