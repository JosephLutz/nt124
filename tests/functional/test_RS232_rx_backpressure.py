"""Deliberate backpressure fault-injection: writes fully, then waits before
draining the IN endpoint at all -- forcing usbd_ep_write_packet() to fail
inside send_rx(). This formalizes the manual reproduction from this
session's debugging (see ../SEND_RX_LOCKUP_NOTES.md).

The nt124 has only 2 physical RX buffers (rx_buffer[NUM_RX_BUFFERS], see
uart.c). If the USB host doesn't drain the IN endpoint before both buffers
fill/idle-flush, process_rx() overwrites the still-undelivered buffer and
some received data is lost. Two ways to address this were considered (see
SEND_RX_LOCKUP_NOTES.md's "Secondary issue"):

1. Detect and report (done, commit d4a51d3) -- process_rx() flags
   RX_OR_ERROR when it's about to overwrite a still-pending buffer, and
   send_rx() surfaces RX_F_ERROR/RX_P_ERROR/RX_OR_ERROR as
   ACM_CTRL_FRAMING/PARITY/OVERRUN in the status header.
2. Real flow control (RTS back-pressure) -- considered and REJECTED
   2026-09-30: the end devices this board talks to don't honor RTS/CTS at
   all, so firmware toggling RTS autonomously would have no effect on
   them. RTS/CTS stays 100% host-driven (usbuart_set_control_line_state()).

So data loss under sustained backpressure is accepted, permanent behavior
on this firmware, not an open bug to track -- what matters, and what these
tests confirm, is that the loss is always visible to the host (never
silent) and that the port keeps working normally afterward. This file
moved here from stress/ once that decision made the behavior final rather
than pending a fix.

test_data_loss_is_flagged_under_induced_backpressure confirms both halves
of the accepted behavior at once: backpressure was actually induced (some
data really was lost), and that loss shows up as a line-error flag on at
least one packet rather than arriving silently.

test_port_recovers_after_backpressure checks a different property: whatever
data is lost, the port itself should still work normally for a subsequent
transfer afterward, rather than being left permanently stuck.

Requires TX/RX wired between port 0 and its peer, and the transceiver set
to a mode that reaches the external bus.

Run directly:
    python test_RS232_rx_backpressure.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402


def _induce_backpressure_round_trip(port, peer, pattern, settle=0.5):
    """Write `pattern` fully, wait, let the peer echo it, wait again, THEN
    start reading -- deliberately never draining the IN endpoint while
    send_rx() is trying to deliver data, forcing a write failure.

    Returns (received, packets, peer_saw).
    """
    peer.flush_input()
    port.write(pattern, timeout=2000)
    time.sleep(settle)
    peer_saw = peer.read_available()
    peer.write(peer_saw)
    time.sleep(settle)
    received, packets = port.read_payload(len(pattern), timeout=2000)
    return received, packets, peer_saw


class TestRxBackpressure(PeerTestCase):
    """Uses port 0 only -- this is a targeted mechanism test, not a
    per-port survey; test_RS232_loopback_bulk.py covers all 4 ports."""

    def test_data_loss_is_flagged_under_induced_backpressure(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))

        received, packets, peer_saw = _induce_backpressure_round_trip(port, peer, pattern)

        self.assertEqual(peer_saw, pattern,
                          "peer side sanity check failed -- that's not the "
                          "bug this test targets, something else is wrong")
        # Data loss under induced backpressure is accepted, permanent
        # behavior (see the module docstring) -- what this test confirms is
        # that backpressure was actually induced (some data really was
        # lost) and that the loss shows up as a line-error flag on at least
        # one packet, instead of arriving silently.
        self.assertLess(len(received), len(pattern),
                         "expected data loss didn't happen -- backpressure "
                         "wasn't actually induced, so this isn't testing "
                         "what it's supposed to")
        self.assertTrue(any(p.line_error for p in packets),
                         f"data was lost ({len(received)}/{len(pattern)} bytes) "
                         f"but no packet flagged a line error -- statuses: "
                         f"{[p.describe() for p in packets]}")

    def test_port_recovers_after_backpressure(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))

        _induce_backpressure_round_trip(port, peer, pattern)  # induce it; its own result isn't checked here

        recovery_pattern = bytes(range(10))
        recovered = tx_one_way(port, peer, recovery_pattern)
        self.assertEqual(recovered, recovery_pattern,
                          "did not recover after induced backpressure -- "
                          "port may be permanently stuck (reboot required)")


if __name__ == "__main__":
    unittest.main()
