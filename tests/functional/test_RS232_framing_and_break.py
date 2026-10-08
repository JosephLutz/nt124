"""Two RX-side edge cases not covered elsewhere:

1. A sustained framing/timing mismatch between nt124 and its peer. An
   earlier version of this test tried to trigger USART_SR_FE specifically
   via a stop-bits mismatch (nt124 expecting more stop bits than the peer
   actually sends, back-to-back) -- confirmed on real hardware to be an
   unreliable way to do this: a stop-bits mismatch desyncs byte
   *boundaries* (bit slip) rather than cleanly flagging each byte while
   leaving the data intact, and how much corruption/flagging resulted
   varied run to run and port to port (one run produced zero flagged
   packets at all on one port despite clearly mismatched settings). A baud
   mismatch is the reliable mechanism already proven in
   test_RS232_line_coding_edge_cases.py's test_baud_mismatch_flagged_and_
   recovers; this file reuses it at a different ratio so the two tests are
   independent, and -- like that one -- only claims what's actually true of
   a frame-timing mismatch: errors get flagged and the port recovers, not
   that data survives perfectly intact (that stronger guarantee only holds
   for a *parity* mismatch, see test_RS232_parity_error_injection.py, which
   doesn't touch bit timing at all).

2. nt124 actually RECEIVING a real BREAK condition. test_RS232_send_break.py
   only exercises nt124 SENDING a break (NT124_USB_REQ_SEND_BREAK) --
   nothing checks what happens when a break arrives on the wire. The STM32
   USART reports a break as data=0x00 with a framing error (there's no
   separate break-detect event wired up in this firmware -- ACM_CTRL_BRK is
   defined but never set); what matters here is that it doesn't disrupt the
   port, mirroring test_RS232_send_break.py's own "does not disrupt"
   framing for the opposite direction.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_framing_and_break.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, ST_LINE_ERRORS  # noqa: E402
from support import PeerTestCase, drain_port, read_while_peer_writes, tx_one_way  # noqa: E402

_PATTERN = bytes(i & 0xFF for i in range(4096))


def _stream_with_framing_mismatch(port, peer):
    port.set_line_coding(LineCoding(115200))
    peer.configure(230400)  # exactly double -- reliably misframes a continuous stream
    try:
        return read_while_peer_writes(port, peer, _PATTERN, timeout=5000)
    finally:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        # A genuine reconfigure is allowed one idle-frame glitch byte on
        # the wire -- give it time to arrive, then flush it, so it doesn't
        # leak into whichever test happens to run next and use this same
        # peer/port.
        time.sleep(0.05)
        peer.flush_input()
        drain_port(port)


class TestFramingErrorInjection(PeerTestCase):

    def test_sustained_mismatch_is_flagged_and_recovers(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                received, packets = _stream_with_framing_mismatch(port, peer)
                self.assertTrue(
                    any(p.status & ST_LINE_ERRORS for p in packets),
                    f"port {index}: a sustained baud/framing mismatch "
                    f"produced no line-error flag at all -- statuses: "
                    f"{[p.describe() for p in packets]}")

                recovery_pattern = bytes(range(10))
                recovered = tx_one_way(port, peer, recovery_pattern)
                self.assertEqual(recovered, recovery_pattern,
                                  f"port {index}: did not recover cleanly "
                                  f"after a sustained framing mismatch")


class TestReceivedBreak(PeerTestCase):

    def test_received_break_does_not_disrupt_port(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                peer.flush_input()
                drain_port(port)

                peer.send_break(duration=0.1)  # blocks for the duration
                time.sleep(0.05)

                # Drain whatever the break itself produced (typically one
                # 0x00 byte with a framing error, possibly nothing at all
                # depending on exact timing) before checking recovery --
                # not asserted on directly, since the exact framing-error
                # outcome of a break isn't this test's concern.
                drain_port(port)

                recovered = tx_one_way(port, peer, pattern)
                self.assertEqual(recovered, pattern,
                                  f"port {index}: did not recover cleanly "
                                  f"after receiving a real BREAK condition")


if __name__ == "__main__":
    unittest.main()
