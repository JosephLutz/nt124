"""Deliberately mismatched parity between nt124 and its peer, so every
single received byte fails the USART's parity check -- not an occasional
error, a deterministic 100% error rate. Even and odd parity are exact
complements of each other for any given data byte, so configuring the
nt124 for one and the peer for the other guarantees uart_RX()'s error
branch (uart.c) runs on every byte received, for the whole length of a
large transfer.

This exercises two separate things:

1. test_data_not_lost_under_sustained_parity_errors: data integrity under
   a long, continuous run of errors. Originally written with a sequential
   write-then-read (write the whole transfer, then read), which reliably
   lost most of the transfer -- but for two unrelated reasons, not one:
   a real bug (uart_RX()'s error branch never reset the idle-gap timer,
   so a sustained run of errors left it disarmed and the stream's
   trailing partial buffer was never flushed -- fixed in uart.c, which
   now resets it on every received byte, error or not) tangled up with a
   test-sequencing artifact (the sequential read/write meant the host
   wasn't draining the IN endpoint while most of the data arrived, which
   -- combined with the already-accepted, by-design lack of RTS
   back-pressure, only 2 rx_buffer slots; see
   tests/functional/test_RS232_rx_backpressure.py and tests/README.md --
   loses most of a transfer on its own, independent of any error
   handling). Now uses `read_while_peer_writes` (support.py) so the host
   drains packets concurrently with the peer's write, like any real
   client would -- confirmed passing against the fixed firmware across
   repeated fresh-boot trials.

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
   content, so it isn't affected by issue #1's data loss.

This was originally believed to desync a port's RX DMA position
permanently, requiring reboot/reflash before trusting any other test,
and gated behind NT124_DESTRUCTIVE for that reason. That belief was
based on a misdiagnosis (a suspected DMA/CPU race that turned out not to
be the real bug -- see above); confirmed not destructive against the
fixed firmware (a normal test run immediately afterward, no reboot,
passes cleanly), so the gate's been removed.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_parity_error_injection.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, ST_PARITY  # noqa: E402
from support import PeerTestCase, read_while_peer_writes  # noqa: E402

_PATTERN = bytes(i & 0xFF for i in range(8192))


def _stream_with_mismatched_parity(port, peer):
    port.set_line_coding(LineCoding(115200, databits=8, parity="e"))
    peer.configure(115200, databits=8, parity="o")
    try:
        return read_while_peer_writes(port, peer, _PATTERN, timeout=5000)
    finally:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        # A genuine reconfigure is allowed one idle-frame glitch byte on
        # the wire (see test_RS232_line_coding_matrix.py et al.) -- give it
        # time to arrive, then flush it, so it doesn't leak into whichever
        # test happens to run next and use this same peer.
        time.sleep(0.05)
        peer.flush_input()


class TestParityErrorInjection(PeerTestCase):

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
