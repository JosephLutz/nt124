"""Real data-integrity round trips at non-default line codings.

test_RS232_control_plane.py's baud/parity sweeps only check that
SET_LINE_CODING is accepted (doesn't raise/STALL) -- they never verify
data actually moves correctly at those settings. Every data-plane test
elsewhere in this suite hardcodes 8N1 at 115200. This file is the one
place that exercises usbuart_set_line_coding()'s bCharFormat/bParityType/
bDataBits switches (uart.c) with an actual round trip, at each combination,
so a mistake in the frame-length math (10/11/12-bit selection feeding
set_uart_parameters()'s tim_table lookup) or in send_rx()'s "mask out the
parity bit for 8-bit-with-parity frames" logic would show up as corrupted
data, not just an accepted-but-unverified request.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_matrix.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402

# (databits, parity, stopbits) -- representative combinations, not the full
# cross product: every parity value at 8 databits/1 stopbit, every stopbits
# value at 8N, and 7-databit framing (which set_uart_parameters() folds into
# a 9-bit hardware frame whenever parity is enabled) with each parity.
_COMBINATIONS = [
    (8, "n", 1.0),  # baseline -- matches every other data-plane test
    (8, "o", 1.0),
    (8, "e", 1.0),
    (8, "n", 2.0),
    (8, "n", 1.5),
    (7, "o", 1.0),
    (7, "e", 1.0),
]


class TestLineCodingMatrix(PeerTestCase):

    def test_round_trip_at_each_line_coding(self) -> None:
        pattern = bytes(i & 0xFF for i in range(20))
        for databits, parity, stopbits in _COMBINATIONS:
            for index, port, peer in self.each_port_and_peer():
                with self.subTest(databits=databits, parity=parity,
                                   stopbits=stopbits, port=index):
                    port.set_line_coding(LineCoding(115200, databits=databits,
                                                     parity=parity, stopbits=stopbits))
                    peer.configure(115200, databits=databits, parity=parity,
                                   stopbits=stopbits)
                    # Every combo here is a genuine reconfigure (even when
                    # only stopbits/parity/databits change, not baud) --
                    # set_uart_parameters() disables/re-enables the USART
                    # for any of them, which is allowed one idle-frame
                    # glitch byte on the wire (see SEND_RX_LOCKUP_NOTES.md).
                    # Give it time to actually arrive, then flush it away,
                    # rather than flushing too early and racing a delayed
                    # byte into the real comparison below.
                    time.sleep(0.05)
                    peer.flush_input()
                    received, packets, echoed = loopback_via_peer(port, peer, pattern)
                    self.assertEqual(echoed, pattern,
                                      "peer never saw the full pattern -- not "
                                      "reaching the external wire")
                    self.assertEqual(received, pattern,
                                      f"got back {received!r} instead of the "
                                      f"full pattern at {databits}{parity}{stopbits}")
                    self.assertFalse(any(p.line_error for p in packets),
                                      f"line error flagged at {databits}{parity}"
                                      f"{stopbits}: {[p.describe() for p in packets]}")

        # Leave every port back on the suite's standard setting -- see the
        # comment in test_RS232_control_plane.py's baud/parity sweeps for why.
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
