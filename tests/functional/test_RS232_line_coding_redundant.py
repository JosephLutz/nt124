"""Regression test for the redundant-SET_LINE_CODING no-glitch optimization
(commit 6e3a531): set_uart_parameters() disables then re-enables the USART
(UE 0->1) with TE already set, which per the STM32 reference manual sends an
idle frame as the first thing back out -- a receiver can read that idle
frame as a spurious 0xFF byte prepended to the next real transmission.
usbuart_set_line_coding() (uart.c) now returns early, skipping the whole
reconfigure, when the host resends the exact line coding already in effect.

This directly targets that early-return path with a real data check: resend
an identical line coding, then confirm the very next transmission arrives
at the peer with no spurious leading byte. (Deliberately not also asserting
that a *genuine* change still glitches once -- that side was already
verified via multi-trial hardware testing during the original fix and isn't
a deterministic, single-shot assertion suitable for a suite that's meant to
pass reliably.)

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_redundant.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402


class TestLineCodingRedundant(PeerTestCase):

    def test_redundant_line_coding_no_glitch(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                coding = LineCoding(115200)
                port.set_line_coding(coding)
                peer.configure(115200)

                port.set_line_coding(coding)  # identical resend -- should be a no-op

                pattern = bytes(range(10))
                received = tx_one_way(port, peer, pattern)
                self.assertEqual(received, pattern,
                                  f"peer saw {received!r} instead of the exact "
                                  f"pattern -- a spurious byte from an "
                                  f"idle-frame glitch on the redundant "
                                  f"SET_LINE_CODING would show up here")


if __name__ == "__main__":
    unittest.main()
