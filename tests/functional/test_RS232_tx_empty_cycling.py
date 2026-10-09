"""Repeated-cycle GET_TXEMPTY tests, mirroring the other cycling files'
pattern. test_RS232_tx_empty_timing.py checks the false-during/true-after
transition once per port; nothing repeats it, and nothing actually polls
tx_empty() continuously *during* an active transfer to confirm it stays
false the whole time rather than just checking it once right after
write() returns -- the same gap identified in the flow-control cycling
tests (CTS toggled once around a clean write vs. toggled repeatedly
against data that's continuously flowing): a single post-write check could
miss a race where tx_empty_count_down/schedule_ctrl_update() (uart.c)
flips the flag true prematurely partway through a still-draining transfer.

Two scenarios, each run _REPEATS times per port, at a slow baud (1200) so
the gap between "USB write done" and "wire actually drained" is wide
enough to reliably observe (same reasoning as
test_RS232_tx_empty_timing.py):

1. tx_empty() reads false immediately after write(), then becomes true
   once the transfer has had time to fully drain -- repeated.
2. tx_empty() is polled continuously throughout the transfer's expected
   drain window and must read false on every single poll, not just once --
   repeated.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_BAUD = 1200
_PATTERN = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud
_REPEATS = 10  # adjust for more/less cycling


class TestTxEmptyCycling(PeerTestCase):

    def test_tx_empty_false_during_transfer_true_after_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(_BAUD))
                peer.configure(_BAUD)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")

                            port.write(_PATTERN, timeout=2000)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true "
                                f"immediately after writing -- the wire "
                                f"can't possibly have drained yet")

                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the transfer had time to "
                                f"fully drain")

                            # Drain what the peer actually received so it
                            # doesn't bleed into the next cycle.
                            peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_tx_empty_stays_false_throughout_transfer_repeated(self) -> None:
        poll_interval = 0.02
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(_BAUD))
                peer.configure(_BAUD)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(_PATTERN, timeout=2000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()

                            # Poll for most of the expected drain window --
                            # 64 bytes at 1200 baud is ~530ms; stop polling
                            # a bit early to leave margin against timing
                            # jitter rather than racing the real completion.
                            poll_until = time.monotonic() + 0.4
                            polls = 0
                            while time.monotonic() < poll_until:
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"cycle {cycle}: tx_empty() read true "
                                    f"while the transfer should still have "
                                    f"been actively draining (poll {polls})")
                                polls += 1
                                time.sleep(poll_interval)
                            self.assertGreater(polls, 5,
                                                "sanity: too few polls happened "
                                                "to mean anything")

                            t.join(timeout=3)
                            if write_error:
                                raise write_error[0]

                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the transfer finished")
                            peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
