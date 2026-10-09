"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) alongside
sustained parity error injection -- the intersection of
test_RS232_control_line_cycling.py and
test_RS232_parity_error_injection.py, neither of which checks this
combination. send_rx() (uart.c) packs ACM_CTRL_PARITY into the same
2-byte status header as the live CTS/DSR/DCD/RI bits
(uart_get_control_line_state()) -- the thing worth checking is that a
sustained, 100%-of-bytes parity error condition never corrupts or
staleifies the modem-line bits reported in those same packets, and that
it never disturbs the host-set DTR/RTS output (uart_RX()'s error branch
only touches rx_state, no GPIO pin).

Uses the same mismatched-parity mechanism as
test_RS232_parity_error_injection.py, duplicated locally so this file
stays runnable standalone, with a smaller pattern (2048 vs. 8192 bytes)
to keep _REPEATS x 4 ports practical.

Two scenarios, each run _REPEATS times per port:

1. DTR/RTS output is set to a known state once, then a sustained
   mismatched-parity stream is run repeatedly -- confirms the output is
   never disturbed.
2. The peer's RTS/DTR are set to a known, alternating state before each
   mismatched-parity stream -- confirms the CTS/DSR bits on every data
   packet still correctly reflect that state despite every byte also
   flagging a parity error.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_parity_error_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port, read_while_peer_writes  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_PATTERN = bytes(i & 0xFF for i in range(2048))


def _stream_with_mismatched_parity(port, peer):
    port.set_line_coding(LineCoding(115200, databits=8, parity="e"))
    peer.configure(115200, databits=8, parity="o")
    try:
        return read_while_peer_writes(port, peer, _PATTERN, timeout=5000)
    finally:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        # A genuine reconfigure is allowed one idle-frame glitch byte on
        # the wire -- give it time to arrive, then flush it.
        time.sleep(0.05)
        peer.flush_input()
        drain_port(port)


class TestControlLineParityErrorCycling(PeerTestCase):

    def test_dtr_rts_output_survives_sustained_parity_errors_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for asserted in (True, False):
                        port.set_control_lines(dtr=asserted, rts=asserted)
                        time.sleep(0.05)
                        for cycle in range(_REPEATS):
                            with self.subTest(asserted=asserted, cycle=cycle):
                                _stream_with_mismatched_parity(port, peer)
                                self.assertEqual(
                                    peer.dsr, asserted,
                                    f"cycle {cycle}: DSR changed after a "
                                    f"sustained parity-error stream "
                                    f"(expected it to stay {asserted})")
                                self.assertEqual(
                                    peer.cts, asserted,
                                    f"cycle {cycle}: CTS changed after a "
                                    f"sustained parity-error stream "
                                    f"(expected it to stay {asserted})")
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default

    def test_modem_status_accurate_alongside_parity_flag_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        rts_state = (cycle % 2 == 0)
                        dtr_state = (cycle % 2 == 1)
                        with self.subTest(cycle=cycle):
                            peer.set_rts(rts_state)
                            peer.set_dtr(dtr_state)
                            time.sleep(0.05)

                            received, packets = _stream_with_mismatched_parity(port, peer)

                            data_packets = [p for p in packets if p.payload]
                            unflagged = [p for p in data_packets if not p.line_error]
                            self.assertFalse(
                                unflagged,
                                f"cycle {cycle}: expected every data packet "
                                f"to flag a parity error -- "
                                f"{len(unflagged)}/{len(data_packets)} "
                                f"didn't: "
                                f"{[p.describe() for p in unflagged]}")
                            bad = [p for p in data_packets
                                   if p.cts != rts_state or p.dsr != dtr_state]
                            self.assertFalse(
                                bad,
                                f"cycle {cycle}: expected CTS={rts_state}, "
                                f"DSR={dtr_state} on every data packet, but "
                                f"some disagreed: "
                                f"{[p.describe() for p in bad]}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)


if __name__ == "__main__":
    unittest.main()
