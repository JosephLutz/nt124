"""Regression trigger for known_issues/line-coding-change-corrupts-in-flight-
dma.md: set_uart_parameters() (uart.c) disables/reconfigures/re-enables the
USART with no regard for an in-flight TX DMA transfer. The TX DMA channel
itself is never touched, so a transfer that's actively mid-flight when a
genuine SET_LINE_CODING change lands keeps running on the same DMA
registers -- its remaining, not-yet-transmitted bytes go out at the *new*
baud rate instead of the one the peer is still listening at.

Deliberately marked @unittest.expectedFailure, per tests/README.md's
convention for a known-broken, not-yet-fixed behavior: this isn't
confirming a fix, it's pinning a concrete, runnable hardware check to the
known_issue so there's something to flip back to a normal assertion (remove
the decorator) once that issue is actually addressed -- expected to happen
alongside the planned work to generalize line-coding handling (see the
known_issue for the candidate approach).

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_line_coding_mid_transfer.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_OLD_BAUD = 1200   # slow enough that a 240-byte write is still draining
_NEW_BAUD = 9600   # genuinely different -- a real reconfigure, not a no-op
_PATTERN = bytes(i & 0xFF for i in range(240))  # ~2s to drain at 1200 baud


class TestLineCodingMidTransfer(PeerTestCase):

    @unittest.expectedFailure
    def test_line_coding_change_mid_tx_corrupts_in_flight_transfer(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_line_coding(LineCoding(_OLD_BAUD))
                    peer.configure(_OLD_BAUD)
                    time.sleep(0.05)  # let any idle-frame glitch byte arrive
                    peer.flush_input()

                    write_error: list[Exception] = []

                    def writer() -> None:
                        try:
                            port.write(_PATTERN, timeout=8000)
                        except Exception as e:  # noqa: BLE001 -- surfaced below
                            write_error.append(e)

                    t = threading.Thread(target=writer, daemon=True)
                    t.start()
                    time.sleep(0.2)  # let TX settle solidly into TX_WORKING
                    # The peer is never reconfigured -- it stays listening at
                    # _OLD_BAUD for the whole test, so anything the port
                    # sends after this point at the new effective baud will
                    # look wrong to it.
                    port.set_line_coding(LineCoding(_NEW_BAUD))
                    t.join(timeout=8)
                    if write_error:
                        raise write_error[0]

                    received = peer.read_until_quiet(quiet=0.5, max_wait=3.0)
                    self.assertEqual(
                        received, _PATTERN,
                        f"port {index}: mid-transfer SET_LINE_CODING "
                        f"corrupted the in-flight TX -- see known_issues/"
                        f"line-coding-change-corrupts-in-flight-dma.md")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
