"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) alongside
induced RX backpressure/overrun -- the intersection of
test_RS232_control_line_cycling.py and test_RS232_rx_backpressure.py,
neither of which checks this combination. send_rx() (uart.c) packs
ACM_CTRL_OVERRUN into the *same* 2-byte status header as the live
CTS/DSR/DCD/RI bits (uart_get_control_line_state()) -- the thing worth
checking is that an overrun condition never corrupts or staleifies the
modem-line bits reported in that same packet, and that inducing repeated
overruns never disturbs the host-set DTR/RTS output (process_rx()/
send_rx() don't touch those pins at all, but it's never been tested).

Uses port 0 only, matching test_RS232_rx_backpressure.py's own stated
scope ("a targeted mechanism test, not a per-port survey" --
test_RS232_loopback_bulk.py already covers all 4 ports for general
data-plane testing).

Two scenarios, each run _REPEATS times:

1. DTR/RTS output is set to a known state once, then overrun is induced
   repeatedly -- confirms the output is never disturbed by the RX-side
   overrun handling.
2. The peer's RTS/DTR are set to a known, alternating state before each
   induced overrun -- confirms the CTS/DSR bits in the eventual
   overrun-flagged packet(s) still correctly reflect that state rather
   than a stale or corrupted value.

Requires TX/RX/RTS/DTR wired between port 0 and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_rx_backpressure_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling


def _induce_overrun(port, peer, pattern, settle=0.5):
    """Write `pattern` fully, wait, let the peer echo it, wait again, THEN
    start reading -- deliberately never draining the IN endpoint while
    send_rx() is trying to deliver data, forcing an induced overrun. Same
    mechanism as test_RS232_rx_backpressure.py's
    _induce_backpressure_round_trip(), duplicated locally so this file
    stays runnable standalone.

    Returns (received, packets).
    """
    peer.flush_input()
    port.write(pattern, timeout=2000)
    time.sleep(settle)
    peer_saw = peer.read_available()
    peer.write(peer_saw)
    time.sleep(settle)
    return port.read_payload(len(pattern), timeout=2000)


class TestControlLineRxBackpressureCycling(PeerTestCase):

    def test_dtr_rts_output_survives_induced_overrun_repeated(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))
        try:
            for asserted in (True, False):
                port.set_control_lines(dtr=asserted, rts=asserted)
                time.sleep(0.05)
                for cycle in range(_REPEATS):
                    with self.subTest(asserted=asserted, cycle=cycle):
                        _induce_overrun(port, peer, pattern)
                        self.assertEqual(
                            peer.dsr, asserted,
                            f"cycle {cycle}: DSR changed after an induced "
                            f"overrun (expected it to stay {asserted})")
                        self.assertEqual(
                            peer.cts, asserted,
                            f"cycle {cycle}: CTS changed after an induced "
                            f"overrun (expected it to stay {asserted})")
        finally:
            port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default

    def test_modem_status_accurate_alongside_overrun_flag_repeated(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))
        try:
            for cycle in range(_REPEATS):
                rts_state = (cycle % 2 == 0)
                dtr_state = (cycle % 2 == 1)
                with self.subTest(cycle=cycle):
                    peer.set_rts(rts_state)
                    peer.set_dtr(dtr_state)
                    time.sleep(0.05)

                    received, packets = _induce_overrun(port, peer, pattern)

                    overrun_packets = [p for p in packets if p.line_error]
                    self.assertTrue(
                        overrun_packets,
                        f"cycle {cycle}: expected data loss didn't happen "
                        f"-- backpressure wasn't actually induced, so this "
                        f"isn't testing what it's supposed to")
                    bad = [p for p in packets
                           if p.cts != rts_state or p.dsr != dtr_state]
                    self.assertFalse(
                        bad,
                        f"cycle {cycle}: expected CTS={rts_state}, "
                        f"DSR={dtr_state} on every packet, but some "
                        f"disagreed: {[p.describe() for p in bad]}")
        finally:
            peer.set_rts(True)
            peer.set_dtr(True)


if __name__ == "__main__":
    unittest.main()
