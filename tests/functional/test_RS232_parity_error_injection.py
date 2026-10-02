"""Deliberately mismatched parity between nt124 and its peer, so every
single received byte fails the USART's parity check -- not an occasional
error, a deterministic 100% error rate. Even and odd parity are exact
complements of each other for any given data byte, so configuring the
nt124 for one and the peer for the other guarantees uart_RX()'s error
branch (uart.c) runs on every byte received, for the whole length of a
large transfer.

This exercises two separate things:

1. test_data_not_lost_under_sustained_parity_errors: data integrity under
   a long, continuous run of errors. Confirmed broken on hardware --
   a large transfer reproducibly loses most of its data, breaking down
   right at the first RX DMA buffer boundary (every RX_BUFFER_SIZE
   bytes), consistent with the known, tracked
   rxne-dma-byte-stealing-race-on-error.md issue: a real USART error's
   manual usart_recv() read can race DMA's own handling of that byte,
   shifting DMA's buffer position out of alignment with the real stream.
   Marked @unittest.expectedFailure until that's fixed.

2. test_every_packet_flags_parity: regression coverage for a *different*,
   already-fixed bug -- an unguarded `dev->rx_state |= RX_P_ERROR` in
   uart_RX()'s error branch that uart_RX_DMA()/uart_RX_timer() (both
   higher priority, both read-modify-write the same rx_state via
   process_rx()) could preempt and silently clobber. That race window is
   a handful of instructions wide, too narrow to hit on demand, so this
   takes a volume/statistics approach: a large transfer crosses the RX
   DMA buffer-full boundary hundreds of times while errors fire on every
   byte, giving the race many chances to show up if it's still there.
   This check only looks at each packet's status flag, not its payload
   content, so it isn't affected by issue #1's data loss/misalignment.

DESTRUCTIVE: triggering the byte-stealing race appears to desync that
port's RX DMA position permanently, not just for the duration of this
stream -- nothing reachable over USB re-initializes the DMA channel's
internal address/count pointers (that only happens once, at boot, in
setup_uart_device()), so once a port is corrupted it stays corrupted for
every test that runs after this one, until the board is rebooted/
reflashed. Skipped unless NT124_DESTRUCTIVE=1 is set, so a normal
`unittest discover` run doesn't silently break the rest of the suite.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly (reboot/reflash the board afterward before trusting any
other test):
    NT124_DESTRUCTIVE=1 python test_RS232_parity_error_injection.py
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, ST_PARITY  # noqa: E402
from support import PeerTestCase  # noqa: E402

_DESTRUCTIVE = os.environ.get("NT124_DESTRUCTIVE") == "1"
_PATTERN = bytes(i & 0xFF for i in range(8192))


def _stream_with_mismatched_parity(port, peer):
    port.set_line_coding(LineCoding(115200, databits=8, parity="e"))
    peer.configure(115200, databits=8, parity="o")
    try:
        peer.write(_PATTERN)
        return port.read_payload(len(_PATTERN), timeout=5000)
    finally:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)


@unittest.skipUnless(_DESTRUCTIVE, "set NT124_DESTRUCTIVE=1 to run this -- it "
                                    "leaves ports 1-3 corrupted until reboot/reflash")
class TestParityErrorInjection(PeerTestCase):

    @unittest.expectedFailure
    def test_data_not_lost_under_sustained_parity_errors(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                received, packets = _stream_with_mismatched_parity(port, peer)
                self.assertEqual(received, _PATTERN,
                                  f"got back {len(received)}/{len(_PATTERN)} "
                                  f"bytes -- mismatched parity shouldn't "
                                  f"corrupt or drop the underlying data, "
                                  f"only flag it")

    def test_every_packet_flags_parity(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                received, packets = _stream_with_mismatched_parity(port, peer)
                data_packets = [p for p in packets if p.payload]
                unflagged = [p for p in data_packets if not (p.status & ST_PARITY)]
                self.assertFalse(unflagged,
                                  f"{len(unflagged)}/{len(data_packets)} data "
                                  f"packets had no parity error flagged "
                                  f"despite every byte in this stream having "
                                  f"mismatched parity -- statuses: "
                                  f"{[p.describe() for p in unflagged]}")


if __name__ == "__main__":
    unittest.main()
