"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) across the
full line-coding format matrix (databits/parity/stopbits combinations) --
the intersection of test_RS232_control_line_cycling.py and
test_RS232_line_coding_matrix.py, neither of which checks this
combination. test_RS232_control_line_line_coding_cycling.py already
covers baud-only changes; this file instead cycles through genuine FRAME
FORMAT changes (7/8 databits, n/o/e parity, 1/1.5/2 stopbits), which
exercise more of set_uart_parameters()'s reconfigure path -- the parity
hardware registers, the new_bits/9-bit-mode computation, and the
tim_table frame-length lookup -- than a baud-only change does.

Uses the same representative combination list as
test_RS232_line_coding_matrix.py, duplicated locally so this file stays
runnable standalone.

Two scenarios, each run _REPEATS full passes through the matrix, per port:

1. DTR/RTS output is set to a known state once, then the firmware is
   cycled through every combination in the matrix repeatedly -- confirms
   the output is never disturbed by any of these format changes.
2. The peer's RTS/DTR are set to a known, alternating state before each
   combination change -- confirms the unsolicited status update
   set_uart_parameters() triggers after every genuine reconfigure
   (schedule_ctrl_update(dev, false)) reports the current, live CTS/DSR
   state correctly after every format change in the matrix, not just a
   baud change.

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_line_coding_matrix_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_REPEATS = 10  # full passes through the matrix; adjust for more/less cycling

# Same representative combinations as test_RS232_line_coding_matrix.py:
# every parity value at 8 databits/1 stopbit, every stopbits value at 8N,
# and 7-databit framing (folded into a 9-bit hardware frame whenever
# parity is enabled) with each parity.
_COMBINATIONS = [
    (8, "n", 1.0),
    (8, "o", 1.0),
    (8, "e", 1.0),
    (8, "n", 2.0),
    (8, "n", 1.5),
    (7, "o", 1.0),
    (7, "e", 1.0),
]


class TestControlLineLineCodingMatrixCycling(PeerTestCase):

    def test_dtr_rts_output_survives_matrix_cycling_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for asserted in (True, False):
                        port.set_control_lines(dtr=asserted, rts=asserted)
                        time.sleep(0.05)
                        for pass_ in range(_REPEATS):
                            for databits, parity, stopbits in _COMBINATIONS:
                                with self.subTest(asserted=asserted, pass_=pass_,
                                                   databits=databits, parity=parity,
                                                   stopbits=stopbits):
                                    port.set_line_coding(LineCoding(
                                        115200, databits=databits,
                                        parity=parity, stopbits=stopbits))
                                    time.sleep(0.05)
                                    self.assertEqual(
                                        peer.dsr, asserted,
                                        f"pass {pass_} @ {databits}{parity}"
                                        f"{stopbits}: DSR changed after a "
                                        f"line coding change (expected it "
                                        f"to stay {asserted})")
                                    self.assertEqual(
                                        peer.cts, asserted,
                                        f"pass {pass_} @ {databits}{parity}"
                                        f"{stopbits}: CTS changed after a "
                                        f"line coding change (expected it "
                                        f"to stay {asserted})")
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default
                    port.set_line_coding(LineCoding(115200))

    def test_modem_status_accurate_after_each_matrix_combination_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                # Deliberately a different baud than any _COMBINATIONS
                # entry (all at 115200) -- a matching baseline would make
                # the very first transition into the matrix a no-op
                # redundant resend (usbuart_set_line_coding()'s intended
                # optimization), which never calls schedule_ctrl_update()
                # and would leave the first read_packet() waiting for an
                # update that never comes.
                port.set_line_coding(LineCoding(9600))
                try:
                    for pass_ in range(_REPEATS):
                        for i, (databits, parity, stopbits) in enumerate(_COMBINATIONS):
                            rts_state = (i % 2 == 0)
                            dtr_state = (i % 2 == 1)
                            with self.subTest(pass_=pass_, databits=databits,
                                               parity=parity, stopbits=stopbits):
                                drain_port(port, timeout=100)
                                peer.set_rts(rts_state)
                                peer.set_dtr(dtr_state)
                                time.sleep(0.05)
                                # Discard whatever the toggle itself
                                # triggered so the next read is
                                # unambiguously the line coding change's
                                # own update.
                                drain_port(port, timeout=100)

                                port.set_line_coding(LineCoding(
                                    115200, databits=databits, parity=parity,
                                    stopbits=stopbits))  # triggers schedule_ctrl_update(dev, false)

                                pkt = port.read_packet(timeout=1000)
                                self.assertEqual(
                                    pkt.cts, rts_state,
                                    f"pass {pass_} @ {databits}{parity}"
                                    f"{stopbits}: status reported CTS="
                                    f"{pkt.cts}, expected {rts_state} -- "
                                    f"status={pkt.describe()}")
                                self.assertEqual(
                                    pkt.dsr, dtr_state,
                                    f"pass {pass_} @ {databits}{parity}"
                                    f"{stopbits}: status reported DSR="
                                    f"{pkt.dsr}, expected {dtr_state} -- "
                                    f"status={pkt.describe()}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)
                    port.set_line_coding(LineCoding(115200))


if __name__ == "__main__":
    unittest.main()
