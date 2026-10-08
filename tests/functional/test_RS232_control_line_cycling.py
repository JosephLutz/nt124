"""Repeated-cycle control-plane (modem status line) tests, mirroring the
RX/TX cycling files' pattern. test_RS232_modem_status_lines.py checks each
direction once (assert, deassert; one toggle per line); nothing repeats the
toggle/observe cycle, which is exactly the kind of thing that could expose a
missed EXTI edge, a stuck GPIO write, or a systick-coalescing bug
(schedule_ctrl_update()/disable_systick_if_unused(), uart.c) that a single
pass wouldn't catch.

Two directions, each run _REPEATS times per port:

1. nt124 output -> peer input: toggle DTR/RTS via SET_CONTROL_LINE_STATE,
   confirm the peer's DSR/CTS track it every cycle.
2. peer output -> nt124-reported status: toggle the peer's RTS/DTR,
   confirm the next status-header packet on nt124's IN endpoint reports
   CTS/DSR correctly every cycle (there's no GET_CONTROL_LINE_STATE
   request -- this is the only way to observe nt124's input lines).

DCD/RI aren't included here -- see test_RS232_modem_status_lines.py's module
docstring for why those need a human physically toggling a cable and can't
be automated into a repeated cycle.

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling


class TestControlLineCycling(PeerTestCase):

    def test_dtr_rts_output_cycling_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                try:
                    for cycle in range(_REPEATS):
                        port.set_control_lines(dtr=True, rts=True)
                        time.sleep(0.05)
                        with self.subTest(cycle=cycle, state="asserted"):
                            self.assertTrue(peer.dsr, f"cycle {cycle}: "
                                             f"peer didn't see DSR asserted")
                            self.assertTrue(peer.cts, f"cycle {cycle}: "
                                             f"peer didn't see CTS asserted")

                        port.set_control_lines(dtr=False, rts=False)
                        time.sleep(0.05)
                        with self.subTest(cycle=cycle, state="deasserted"):
                            self.assertFalse(peer.dsr, f"cycle {cycle}: peer "
                                              f"still saw DSR asserted after "
                                              f"deassert")
                            self.assertFalse(peer.cts, f"cycle {cycle}: peer "
                                              f"still saw CTS asserted after "
                                              f"deassert")
                finally:
                    # Peer.open() assumes DTR/RTS asserted (see peer.py).
                    port.set_control_lines(dtr=True, rts=True)

    def test_peer_control_lines_reported_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                drain_port(port)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle, line="cts"):
                            peer.set_rts(False)
                            pkt = port.read_packet(timeout=1000)
                            self.assertFalse(pkt.cts, f"cycle {cycle}: "
                                              f"expected CTS deasserted, "
                                              f"status={pkt.describe()}")

                            peer.set_rts(True)
                            pkt = port.read_packet(timeout=1000)
                            self.assertTrue(pkt.cts, f"cycle {cycle}: "
                                             f"expected CTS asserted, "
                                             f"status={pkt.describe()}")

                        with self.subTest(cycle=cycle, line="dsr"):
                            peer.set_dtr(False)
                            pkt = port.read_packet(timeout=1000)
                            self.assertFalse(pkt.dsr, f"cycle {cycle}: "
                                              f"expected DSR deasserted, "
                                              f"status={pkt.describe()}")

                            peer.set_dtr(True)
                            pkt = port.read_packet(timeout=1000)
                            self.assertTrue(pkt.dsr, f"cycle {cycle}: "
                                             f"expected DSR asserted, "
                                             f"status={pkt.describe()}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)


if __name__ == "__main__":
    unittest.main()
