"""Deliberate backpressure fault-injection: writes fully, then waits before
draining the IN endpoint at all -- forcing usbd_ep_write_packet() to fail
inside send_rx(). This formalizes the manual reproduction from this
session's debugging (see ../../SEND_RX_LOCKUP_NOTES.md).

test_data_loss_under_induced_backpressure is a KNOWN, currently-unresolved
issue -- process_rx() overwrites num_read/rx_dma_index if another
buffer-full/idle-gap event fires before a previously-failed send is
retried, dropping whatever hadn't been delivered yet. It's marked
@unittest.expectedFailure so a normal stress-suite run doesn't read this as
a fresh regression. The fix for the data loss itself is real flow control
(RTS back-pressure) -- not yet implemented; see SEND_RX_LOCKUP_NOTES.md.
Once it is, unittest will report this as an UNEXPECTED SUCCESS -- that's
your signal to remove the decorator.

test_overrun_flagged_under_induced_backpressure checks a narrower, already
-fixed property: even though data still gets lost, the loss is no longer
*silent* -- process_rx() flags RX_OR_ERROR when it's about to overwrite a
still-pending buffer, and send_rx() now surfaces that as ACM_CTRL_OVERRUN
in the status header (see SEND_RX_LOCKUP_NOTES.md's "Secondary issue").
This one is NOT expected to fail.

test_port_recovers_after_backpressure checks a different property: whatever
data is lost, the port itself should still work normally for a subsequent
transfer afterward, rather than being left permanently stuck. This is NOT
expected to fail on firmware built from master (68337af's interrupt
re-enable keeps the port alive); it IS expected to fail on the reverted
(pre-68337af) version, which leaves that port's RX interrupts disabled
until reboot on the very first failure.

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

    @unittest.expectedFailure
    def test_data_loss_under_induced_backpressure(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))

        received, packets, peer_saw = _induce_backpressure_round_trip(port, peer, pattern)

        self.assertEqual(peer_saw, pattern,
                          "peer side sanity check failed -- that's not the "
                          "bug this test targets, something else is wrong")
        self.assertEqual(received, pattern,
                          f"got back {received!r} instead of the full pattern -- "
                          f"data lost under induced backpressure")

    def test_overrun_flagged_under_induced_backpressure(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))

        received, packets, peer_saw = _induce_backpressure_round_trip(port, peer, pattern)

        # Induced backpressure is expected to cause data loss here (that's
        # the separate, still-open issue above) -- what this test checks is
        # that the loss shows up as ACM_CTRL_OVERRUN on at least one packet,
        # instead of arriving silently.
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
