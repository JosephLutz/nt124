"""Confirms a fault/perturbation on one port doesn't disrupt a concurrent
transfer on another. Every uarts[] entry is logically independent, but a
few mechanisms are genuinely shared across all 4 ports: the single
usb_task()/usbd_poll() loop, the systick-driven ctrl-update/tx-empty
scheduler (schedule_ctrl_update()/disable_systick_if_unused(), which scans
all 4 ports' countdowns before deciding whether to turn systick off), and
the single USB control endpoint used for every SET_LINE_CODING/SET_
CONTROL_LINE_STATE request regardless of which port it targets. A bug in
any of that shared bookkeeping could show up as cross-port interference
that per-port-sequential tests (which never run two ports' state changes
at the same instant) would never catch.

This runs a large, steady loopback transfer on port 0 while concurrently
hammering port 1 with line-coding changes and an induced RX overrun, then
checks port 0's transfer came through byte-for-byte with no line errors.

Requires TX/RX wired between ports 0 and 1 and their peers, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_port_isolation.py
"""
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402


def _perturb_port(port, peer) -> None:
    """Line-coding churn plus an induced RX overrun -- deliberately noisy,
    to give any cross-port leakage the best chance of showing up on the
    port being watched instead."""
    for baud in (9600, 230400, 115200):
        port.set_line_coding(LineCoding(baud))
        time.sleep(0.05)

    peer.flush_input()
    pattern = bytes(range(64))
    port.write(pattern, timeout=2000)
    time.sleep(0.5)  # don't drain -- forces a failed send_rx() delivery
    peer.read_available()
    peer.write(peer.read_available())
    port.read_payload(len(pattern), timeout=2000)


class TestPortIsolation(PeerTestCase):

    def test_port0_unaffected_by_port1_perturbation(self) -> None:
        port0, peer0 = self.board.port(0), self.peers[0]
        port1, peer1 = self.board.port(1), self.peers[1]

        port0.set_line_coding(LineCoding(115200))
        peer0.configure(115200)
        port1.set_line_coding(LineCoding(115200))
        peer1.configure(115200)

        pattern = bytes(i & 0xFF for i in range(8192))

        with ThreadPoolExecutor(max_workers=2) as ex:
            watched = ex.submit(loopback_via_peer, port0, peer0, pattern, 8000)
            noisy = ex.submit(_perturb_port, port1, peer1)
            received, packets, echoed = watched.result()
            noisy.result()

        self.assertEqual(echoed, pattern,
                          "port 0: peer never saw the full pattern")
        self.assertEqual(received, pattern,
                          f"port 0: got back {len(received)}/{len(pattern)} "
                          f"bytes while port 1 was being perturbed")
        self.assertFalse(any(p.line_error for p in packets),
                          f"port 0: unexpected line error while port 1 was "
                          f"being perturbed: {[p.describe() for p in packets]}")

        # Leave port 1 back on the suite's standard setting.
        port1.set_line_coding(LineCoding(115200))
        peer1.configure(115200)


if __name__ == "__main__":
    unittest.main()
