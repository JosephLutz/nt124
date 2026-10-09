"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) around
NT124_USB_REQ_SEND_BREAK -- the intersection of
test_RS232_control_line_cycling.py and test_RS232_send_break_cycling.py,
neither of which checks this combination.

Two scenarios, each run _REPEATS times per port:

1. usbuart_send_break()/usart_send_break() (uart.c) only ever sets
   USART_CR1_SBK -- no GPIO pin is touched, unlike set_uart_parameters(),
   which is why this is a narrower check than
   test_RS232_control_line_line_coding_cycling.py's equivalent: confirms a
   host-set DTR/RTS state is never disturbed by repeated send_break()
   calls in between.
2. Unlike a line coding change, send_break() never proactively triggers
   schedule_ctrl_update() -- there's nothing here that pushes a fresh
   status update the way set_uart_parameters() does. So the question is
   the opposite: does calling send_break() interleaved with a real control
   line change interfere with that change still being reported correctly,
   rather than whether send_break() itself produces a report.

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_send_break_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling


class TestControlLineSendBreakCycling(PeerTestCase):

    def test_dtr_rts_output_survives_send_break_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                try:
                    for asserted in (True, False):
                        port.set_control_lines(dtr=asserted, rts=asserted)
                        time.sleep(0.05)
                        for cycle in range(_REPEATS):
                            with self.subTest(asserted=asserted, cycle=cycle):
                                port.send_break()  # must not raise/STALL
                                time.sleep(0.05)  # let the one-shot break frame finish
                                self.assertEqual(
                                    peer.dsr, asserted,
                                    f"cycle {cycle}: DSR changed after "
                                    f"send_break() (expected it to stay "
                                    f"{asserted})")
                                self.assertEqual(
                                    peer.cts, asserted,
                                    f"cycle {cycle}: CTS changed after "
                                    f"send_break() (expected it to stay "
                                    f"{asserted})")
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default

    def test_cts_dsr_status_accurate_around_send_break_repeated(self) -> None:
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
                            port.send_break()  # interleaved -- must not
                            # disrupt the pending status notification

                            pkt = port.read_packet(timeout=1000)
                            self.assertEqual(
                                pkt.cts, rts_state,
                                f"cycle {cycle}: status reported CTS="
                                f"{pkt.cts}, expected {rts_state} -- "
                                f"status={pkt.describe()}")
                            self.assertEqual(
                                pkt.dsr, dtr_state,
                                f"cycle {cycle}: status reported DSR="
                                f"{pkt.dsr}, expected {dtr_state} -- "
                                f"status={pkt.describe()}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)


if __name__ == "__main__":
    unittest.main()
