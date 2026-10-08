"""Repeated-cycle SET_LINE_CODING tests, mirroring the RX/TX/control-line
cycling files' pattern. Every other line-coding test in this suite checks
a given scenario once; nothing repeats a sequence of reconfigures to see
whether usbuart_set_line_coding()'s "is this actually a change" comparison
(uart.c) -- the thing that decides whether to skip the reconfigure
entirely and avoid the idle-frame glitch -- keeps working correctly across
many transitions, not just the first one.

Three scenarios, each run _REPEATS times per port:

1. Alternating between two different genuine bauds every cycle, with a
   real round-trip data check each time (each genuine reconfigure is
   allowed its one known idle-frame glitch byte -- see
   test_RS232_line_coding_redundant.py -- absorbed before the real
   comparison, same as every other genuine-reconfigure test in this
   suite).
2. Resending the exact same line coding over and over -- the "no
   reconfigure happens at all" path -- confirming it stays glitch-free
   every single time, not just once (test_RS232_line_coding_redundant.py
   only checks this a single time).
3. Alternating a genuine change with a redundant resend of it, repeated --
   the real-world case of a host that resends line coding defensively
   between occasional actual changes. This is the one most likely to
   catch the comparison logic getting confused by a change arriving right
   before a resend, or vice versa.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_cycling.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_BAUD_A = 9600
_BAUD_B = 115200


def _settle_after_genuine_reconfigure(peer) -> None:
    """A genuine reconfigure is allowed one idle-frame glitch byte on the
    wire (set_uart_parameters() disables/re-enables the USART) -- give it
    time to arrive, then flush it, so it doesn't leak into the real
    comparison that follows. See test_RS232_line_coding_redundant.py."""
    time.sleep(0.05)
    peer.flush_input()


class TestLineCodingCycling(PeerTestCase):

    def test_alternating_genuine_baud_change_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        baud = _BAUD_A if cycle % 2 == 0 else _BAUD_B
                        with self.subTest(cycle=cycle, baud=baud):
                            port.set_line_coding(LineCoding(baud))
                            peer.configure(baud)
                            _settle_after_genuine_reconfigure(peer)
                            received = tx_one_way(port, peer, pattern)
                            self.assertEqual(received, pattern,
                                              f"cycle {cycle} @ {baud}: "
                                              f"peer got {received!r}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_redundant_resend_cycling_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                coding = LineCoding(115200)
                try:
                    port.set_line_coding(coding)
                    peer.configure(115200)
                    _settle_after_genuine_reconfigure(peer)
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            port.set_line_coding(coding)  # identical resend every time
                            received = tx_one_way(port, peer, pattern)
                            self.assertEqual(received, pattern,
                                              f"cycle {cycle}: peer saw "
                                              f"{received!r} -- a spurious "
                                              f"glitch byte from a "
                                              f"\"redundant\" resend that "
                                              f"wasn't actually skipped")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_alternating_genuine_and_redundant_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        baud = _BAUD_A if cycle % 2 == 0 else _BAUD_B
                        coding = LineCoding(baud)

                        with self.subTest(cycle=cycle, baud=baud, step="genuine"):
                            port.set_line_coding(coding)
                            peer.configure(baud)
                            _settle_after_genuine_reconfigure(peer)
                            received = tx_one_way(port, peer, pattern)
                            self.assertEqual(received, pattern,
                                              f"cycle {cycle} @ {baud} "
                                              f"(genuine): peer got "
                                              f"{received!r}")

                        with self.subTest(cycle=cycle, baud=baud, step="redundant"):
                            port.set_line_coding(coding)  # identical resend
                            received = tx_one_way(port, peer, pattern)
                            self.assertEqual(received, pattern,
                                              f"cycle {cycle} @ {baud} "
                                              f"(redundant resend right "
                                              f"after a genuine change): "
                                              f"peer got {received!r}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
