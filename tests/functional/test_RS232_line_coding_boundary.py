"""Boundary/out-of-spec SET_LINE_CODING payloads.

usbuart_set_line_coding() (uart.c): bCharFormat/bParityType have no
`default` case in their switches, and bDataBits only recognizes 7 and 8 --
any other value silently leaves that field at its *previous* setting
rather than erroring. There's no GET_LINE_CODING request to read the
result back directly, so this is verified indirectly: establish a
distinctive known coding, send a change with only the baud altered and
every other field set to an invalid value, then round-trip at the new baud
using the *previous* stopbits/parity/databits -- if the firmware had
instead corrupted or defaulted them, the peer's mismatched framing would
show up as garbled data or a line-error flag. A genuine baud change is
still allowed to emit one idle-frame glitch byte on the wire (only a
*redundant* resend is glitch-free, see usbuart_set_line_coding() in
uart.c and test_RS232_line_coding_redundant.py) so a small throwaway
transfer absorbs that before the real comparison.

set_uart_parameters()'s baud-lookup loop used to be able to exit with its
index left at -1 for any requested baud below the slowest table entry,
which was then used to index ctrl_delay[]/tx_empty_delay[] out of bounds
(fixed: baud below the slowest entry now floors to it, same as an
in-between value floors to its next-lower neighbor). 300 baud itself was
also removed from the table entirely: it's below the minimum baud the
STM32 USART's 16-bit BRR divisor register can represent on this board's
clock setup, so requesting it used to silently produce a completely wrong
actual bit rate (confirmed ~1659 baud on USART1 instead of 300) rather
than an error. The slowest baud now offered is 1200, which this file
confirms both ways: the device stays responsive to a range of sub-1200
requests, and a sub-1200 request concretely floors to a working 1200
baud, not silently to something else.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_boundary.py
"""
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer, tx_one_way  # noqa: E402


def _raw_line_coding(baud: int, bCharFormat: int, bParityType: int, bDataBits: int) -> bytes:
    return struct.pack("<IBBB", baud, bCharFormat, bParityType, bDataBits)


class TestLineCodingBoundary(PeerTestCase):

    def test_invalid_enum_fields_leave_previous_value(self) -> None:
        pattern = bytes(range(12))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    # Distinctive known-good coding: 8 databits + even
                    # parity folds to a 9-bit hardware frame (uart.c's
                    # bDataBits switch), at a baud nothing else in this
                    # suite uses.
                    port.set_line_coding(LineCoding(9600, databits=8, parity="e", stopbits=2.0))
                    peer.configure(9600, databits=8, parity="e", stopbits=2.0)

                    # Change only the baud; bCharFormat=3 and bParityType=3
                    # are out of spec (valid range is 0-2) and bDataBits=8
                    # recomputes to the same 9-bit frame as before since
                    # parity is unchanged -- nothing except baud should
                    # actually change. This is a genuine baud change, so
                    # it's allowed one idle-frame glitch byte (see module
                    # docstring) -- a throwaway transfer absorbs it before
                    # the real comparison below.
                    port.set_line_coding_raw(_raw_line_coding(115200, 3, 3, 8))
                    peer.configure(115200, databits=8, parity="e", stopbits=2.0)
                    tx_one_way(port, peer, bytes([0xAA]))

                    received, packets, echoed = loopback_via_peer(port, peer, pattern)
                    self.assertEqual(echoed, pattern,
                                      "peer never saw the full pattern")
                    self.assertEqual(received, pattern,
                                      f"got back {received!r} -- the invalid "
                                      f"bCharFormat/bParityType fields changed "
                                      f"the actual framing instead of leaving "
                                      f"it at the previous setting")
                    self.assertFalse(any(p.line_error for p in packets),
                                      f"line error flagged: "
                                      f"{[p.describe() for p in packets]}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_sub_1200_baud_stays_responsive(self) -> None:
        for index, port in self.each_port():
            with self.subTest(port=index):
                try:
                    for baud in (0, 1, 100, 300, 1199):
                        port.set_line_coding_raw(_raw_line_coding(baud, 0, 0, 8))
                        # Control plane must stay responsive -- this is the
                        # regression check for the fixed out-of-bounds
                        # ctrl_delay[]/tx_empty_delay[] read that used to
                        # be reachable here.
                        self.assertIsInstance(port.tx_empty(), bool)
                finally:
                    port.set_line_coding(LineCoding(115200))

    def test_sub_1200_baud_floors_to_1200(self) -> None:
        pattern = bytes(range(8))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_line_coding_raw(_raw_line_coding(300, 0, 0, 8))
                    peer.configure(1200)
                    # A genuine reconfigure is allowed one idle-frame
                    # glitch byte on the wire -- give it time to arrive
                    # before flushing it away (see module docstring).
                    time.sleep(0.05)
                    peer.flush_input()
                    received, packets, echoed = loopback_via_peer(port, peer, pattern)
                    self.assertEqual(echoed, pattern,
                                      "peer never saw the full pattern")
                    self.assertEqual(received, pattern,
                                      f"got back {received!r} -- a sub-1200 "
                                      f"baud request should floor to a "
                                      f"working 1200 baud, not leave the "
                                      f"port at some other effective rate")
                    self.assertFalse(any(p.line_error for p in packets),
                                      f"line error flagged: "
                                      f"{[p.describe() for p in packets]}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
