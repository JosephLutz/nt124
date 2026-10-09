"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) across
SET_LINE_CODING changes -- the intersection of
test_RS232_control_line_cycling.py and test_RS232_line_coding_cycling.py,
neither of which checks this combination.

Two scenarios, each run _REPEATS times per port:

1. set_uart_parameters() (uart.c) never touches the DTR/RTS output pins --
   only usbuart_set_control_line_state() does. Confirms a host-set DTR/RTS
   state is never disturbed by a line coding change in between, across
   many alternating reconfigure cycles, in both the asserted and
   deasserted state.
2. set_uart_parameters() deliberately calls schedule_ctrl_update(dev,
   false) at the end of every genuine reconfigure, to push a fresh status
   update to the host. Confirms that update actually arrives and reports
   the CURRENT CTS/DSR state correctly -- not a stale value from before
   the reconfigure -- with the peer's RTS/DTR toggled to a known state
   right beforehand each cycle.

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_line_coding_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_BAUD_A = 9600
_BAUD_B = 115200


class TestControlLineLineCodingCycling(PeerTestCase):

    def test_dtr_rts_output_survives_line_coding_changes_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for asserted in (True, False):
                        port.set_control_lines(dtr=asserted, rts=asserted)
                        time.sleep(0.05)
                        for cycle in range(_REPEATS):
                            baud = _BAUD_A if cycle % 2 == 0 else _BAUD_B
                            with self.subTest(asserted=asserted, cycle=cycle, baud=baud):
                                port.set_line_coding(LineCoding(baud))
                                time.sleep(0.05)
                                self.assertEqual(
                                    peer.dsr, asserted,
                                    f"cycle {cycle} @ {baud}: DSR changed "
                                    f"after a line coding change (expected "
                                    f"it to stay {asserted})")
                                self.assertEqual(
                                    peer.cts, asserted,
                                    f"cycle {cycle} @ {baud}: CTS changed "
                                    f"after a line coding change (expected "
                                    f"it to stay {asserted})")
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default
                    port.set_line_coding(LineCoding(115200))

    def test_cts_dsr_status_accurate_after_line_coding_change_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                try:
                    for cycle in range(_REPEATS):
                        rts_state = (cycle % 2 == 0)
                        dtr_state = (cycle % 2 == 1)
                        with self.subTest(cycle=cycle):
                            drain_port(port, timeout=100)
                            peer.set_rts(rts_state)
                            peer.set_dtr(dtr_state)
                            time.sleep(0.05)
                            # Discard whatever the toggle itself triggered
                            # so the next read is unambiguously the line
                            # coding change's own update.
                            drain_port(port, timeout=100)

                            baud = _BAUD_A if cycle % 2 == 0 else _BAUD_B
                            port.set_line_coding(LineCoding(baud))  # triggers schedule_ctrl_update(dev, false)

                            pkt = port.read_packet(timeout=1000)
                            self.assertEqual(
                                pkt.cts, rts_state,
                                f"cycle {cycle}: status after the line "
                                f"coding change reported CTS={pkt.cts}, "
                                f"expected {rts_state} -- "
                                f"status={pkt.describe()}")
                            self.assertEqual(
                                pkt.dsr, dtr_state,
                                f"cycle {cycle}: status after the line "
                                f"coding change reported DSR={pkt.dsr}, "
                                f"expected {dtr_state} -- "
                                f"status={pkt.describe()}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)
                    port.set_line_coding(LineCoding(115200))


if __name__ == "__main__":
    unittest.main()
