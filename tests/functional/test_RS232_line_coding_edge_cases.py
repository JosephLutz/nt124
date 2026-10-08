"""Two line-coding edge cases not covered by test_RS232_line_coding_matrix.py
or test_RS232_line_coding_boundary.py:

1. 7 data bits + NO parity. usbuart_set_line_coding()'s bDataBits switch
   (uart.c) is:

       switch(coding->bDataBits) {
       case 7:
           new_bits = 8;
           break;
       case 8:
       default:
           if (new_parity == USART_PARITY_NONE)
               new_bits = 8;
           else
               new_bits = 9;
           break;
       }

   `case 7` forces an 8-bit hardware frame *unconditionally* -- unlike
   `case 8`, it doesn't look at parity at all. send_rx()'s "mask out the
   parity bit" step only runs `if (dev->bits == 8 && dev->parity !=
   USART_PARITY_NONE)`, so a 7N1 request (7 data bits, no parity) ends up
   with an 8-bit hardware frame and no masking -- the 8th bit a real 7-bit
   sender never transmits is left to whatever the hardware samples there.
   This test exists to observe what actually happens on real hardware;
   found during code review, never previously exercised anywhere in this
   suite (test_RS232_line_coding_matrix.py only tries 7 databits combined
   with odd/even parity, where `case 8`'s branch logic doesn't apply).

2. A real baud-rate mismatch (not a parity/format mismatch) between nt124
   and its peer -- never directly tested; test_RS232_parity_error_injection.py
   covers mismatched parity specifically. Mirrors that file's "accepted
   degradation must be flagged, not silent, and the port must recover"
   pattern.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_edge_cases.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, ST_LINE_ERRORS  # noqa: E402
from support import PeerTestCase, drain_port, read_while_peer_writes, tx_one_way  # noqa: E402

_PATTERN = bytes(i & 0xFF for i in range(8192))


class TestLineCodingEdgeCases(PeerTestCase):

    def test_7_databits_no_parity_round_trip(self) -> None:
        """Characterization test, not an assumed-correct regression check --
        see module docstring for why this combination looked suspicious
        during code review. Masks bit 7 out of both sides before comparing:
        a true 7-bit link can't carry that bit meaningfully either way, so
        the only thing worth asserting is that the low 7 bits of each byte
        survive. If the firmware's 8-bit fallback corrupts even those, this
        is expected to fail and that failure is real, useful information."""
        pattern = bytes(range(32))  # exercises every low-7-bit value twice
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_line_coding(LineCoding(115200, databits=7, parity="n"))
                    peer.configure(115200, databits=7, parity="n")
                    time.sleep(0.05)  # genuine reconfigure -- let any idle-frame glitch arrive
                    peer.flush_input()

                    received = tx_one_way(port, peer, pattern)
                    masked_expected = bytes(b & 0x7F for b in pattern)
                    masked_received = bytes(b & 0x7F for b in received)
                    self.assertEqual(
                        len(received), len(pattern),
                        f"port {index}: got {len(received)}/{len(pattern)} bytes back")
                    self.assertEqual(
                        masked_received, masked_expected,
                        f"port {index}: low 7 bits corrupted under 7N1 -- "
                        f"got {received!r}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_baud_mismatch_flagged_and_recovers(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(57600)  # exactly half -- reliably misframes every byte
                    received, packets = read_while_peer_writes(
                        port, peer, _PATTERN, timeout=5000)

                    self.assertTrue(
                        any(p.status & ST_LINE_ERRORS for p in packets),
                        f"port {index}: baud mismatch produced no line-error "
                        f"flag at all -- statuses: "
                        f"{[p.describe() for p in packets]}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)
                    time.sleep(0.05)
                    peer.flush_input()
                    # A mismatch this sustained can leave nt124-side data
                    # still pending delivery when the timeout above hits --
                    # drain it so it doesn't show up as a stale leading byte
                    # prepended to the recovery check below, or to whichever
                    # test happens to run next on this same port (see
                    # drain_port()'s docstring).
                    drain_port(port)

                # Port must work normally again once baud is corrected.
                recovery_pattern = bytes(range(10))
                recovered = tx_one_way(port, peer, recovery_pattern)
                self.assertEqual(recovered, recovery_pattern,
                                  f"port {index}: did not recover cleanly "
                                  f"after a baud mismatch")


if __name__ == "__main__":
    unittest.main()
