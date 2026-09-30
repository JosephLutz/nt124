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
still allowed to emit one idle-frame glitch byte on the wire (see
SEND_RX_LOCKUP_NOTES.md and the SET_LINE_CODING fix in uart.c -- only a
*redundant* resend is glitch-free, see test_RS232_line_coding_redundant.py)
so a small throwaway transfer absorbs that before the real comparison.

set_uart_parameters()'s baud-lookup loop used to be able to exit with its
index left at -1 for any requested baud below the slowest table entry
(300), which was then used to index ctrl_delay[]/tx_empty_delay[] out of
bounds (fixed: baud below 300 now floors to the 300 entry, same as an
in-between value floors to its next-lower neighbor). This is the
regression test for that fix's control-plane-safety half -- request a few
sub-300 bauds and confirm the device stays responsive throughout.
Concretely confirming the *flooring* behavior with real data at 300 baud
isn't done here: 300 baud has a separate, pre-existing data-integrity bug
of its own (see SEND_RX_LOCKUP_NOTES.md's "Newly discovered issues"),
unrelated to this fix, not yet resolved.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_boundary.py
"""
import struct
import sys
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

    def test_sub_300_baud_stays_responsive(self) -> None:
        for index, port in self.each_port():
            with self.subTest(port=index):
                try:
                    for baud in (0, 1, 100, 299):
                        port.set_line_coding_raw(_raw_line_coding(baud, 0, 0, 8))
                        # Control plane must stay responsive -- this is the
                        # regression check for the fixed out-of-bounds
                        # ctrl_delay[]/tx_empty_delay[] read that used to
                        # be reachable here.
                        self.assertIsInstance(port.tx_empty(), bool)
                finally:
                    port.set_line_coding(LineCoding(115200))


if __name__ == "__main__":
    unittest.main()
