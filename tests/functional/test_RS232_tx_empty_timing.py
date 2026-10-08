"""GET_TXEMPTY semantics under an actual in-progress transfer.

test_RS232_control_plane.py's test_tx_empty_when_idle only ever checks
tx_empty() before any transfer has happened -- trivially true, since it's
also dev->tx_empty's static initial value (uart.c). Nothing in this suite
checks that it goes *false* while a transfer is genuinely in flight and
comes back *true* once the wire has actually drained, which is the whole
reason this field and its delayed-notification machinery
(tx_empty_count_down / tx_empty_delay[], uart.c / sys_tick_handler())
exist: a USB bulk write completes (and port.write() returns) as soon as the
device's endpoint buffer accepts the data, which is much faster than the
UART actually finishing shifting it out over the wire at a real baud rate.

Uses a slow baud (1200) so that gap is wide enough to reliably observe:
port.write() for a few packets returns in well under a millisecond
regardless of baud, while actually draining them over the wire at 1200
baud takes several hundred milliseconds.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_timing.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_BAUD = 1200
_PATTERN = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud


class TestTxEmptyTiming(PeerTestCase):

    def test_tx_empty_false_during_transfer_true_after(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_line_coding(LineCoding(_BAUD))
                    peer.configure(_BAUD)
                    self.assertTrue(port.wait_tx_empty(timeout=1.0),
                                     f"port {index}: not idle before the test even started")

                    port.write(_PATTERN, timeout=2000)
                    self.assertFalse(
                        port.tx_empty(),
                        f"port {index}: tx_empty() was true immediately after "
                        f"writing {len(_PATTERN)} bytes at {_BAUD} baud -- "
                        f"the wire can't possibly have drained yet")

                    self.assertTrue(
                        port.wait_tx_empty(timeout=2.0),
                        f"port {index}: tx_empty() never became true after "
                        f"the transfer had time to fully drain")

                    # Drain whatever the peer actually received so it
                    # doesn't bleed into whichever test runs next.
                    peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
