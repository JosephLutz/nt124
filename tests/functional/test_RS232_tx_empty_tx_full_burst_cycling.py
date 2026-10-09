"""GET_TXEMPTY across a forced TX_FULL burst -- the intersection of
test_RS232_tx_empty_cycling.py and test_RS232_tx_full_burst.py, neither of
which checks this combination. Uses the same mechanism as
test_RS232_tx_full_burst.py, duplicated locally so this file stays
runnable standalone: 3 back-to-back 32-byte packets at 1200 baud (the
slowest supported baud) reliably outrun the wire, forcing the firmware to
park the 3rd packet in the USB OUT FIFO (TX_FULL, usbuart_usb_out_cb()/
uart_TX_DMA_empty(), uart.c) until the first two drain.

Two scenarios, each run _REPEATS times per port:

1. tx_empty() is polled continuously throughout the whole 3-packet burst,
   including the parked-packet handoff -- must read false the entire time,
   only becoming true once all 3 packets have actually drained, and the
   data itself must still arrive intact.
2. Two bursts run back-to-back with no gap between them -- confirms
   tx_empty() correctly flips false again immediately for the second
   burst, with nothing left stuck from the first TX_FULL cycle.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_tx_full_burst_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_PATTERN = bytes(i & 0xFF for i in range(96))  # 3 x 32-byte packets
_CHUNKS = [_PATTERN[i:i + 32] for i in range(0, len(_PATTERN), 32)]


def _start_burst_writer(port):
    """Start writing the 3-chunk burst on a background thread. Returns
    (thread, write_error) -- join the thread and check write_error after."""
    write_error: list[Exception] = []

    def writer() -> None:
        try:
            for chunk in _CHUNKS:
                port.write(chunk, timeout=8000)
        except Exception as e:  # noqa: BLE001 -- surfaced by the caller
            write_error.append(e)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    return t, write_error


class TestTxEmptyTxFullBurstCycling(PeerTestCase):

    def test_tx_empty_tracks_tx_full_burst_correctly_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                time.sleep(0.05)
                peer.flush_input()
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")
                            peer.flush_input()

                            t, write_error = _start_burst_writer(port)
                            time.sleep(0.05)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true right "
                                f"after the burst started")

                            # Poll through the whole expected burst window
                            # (96 bytes at 1200 baud is ~800ms) -- must
                            # never read true until it actually finishes.
                            poll_until = time.monotonic() + 0.6
                            polls = 0
                            while time.monotonic() < poll_until:
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"cycle {cycle}: tx_empty() read true "
                                    f"while the TX_FULL burst should still "
                                    f"be draining (poll {polls})")
                                polls += 1
                                time.sleep(0.02)
                            self.assertGreater(polls, 5,
                                                "sanity: too few polls "
                                                "happened to mean anything")

                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the burst finished")

                            t.join(timeout=8)
                            if write_error:
                                raise write_error[0]
                            received = peer.read_payload(len(_PATTERN), timeout=8.0)
                            self.assertEqual(
                                received, _PATTERN,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(_PATTERN)} bytes -- "
                                f"the burst forcing TX_FULL produced "
                                f"corrupted or incomplete data")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_tx_empty_recovers_for_back_to_back_bursts_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                time.sleep(0.05)
                peer.flush_input()
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")

                            # First burst.
                            t1, err1 = _start_burst_writer(port)
                            t1.join(timeout=8)
                            if err1:
                                raise err1[0]
                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the first burst")
                            first = peer.read_payload(len(_PATTERN), timeout=8.0)
                            self.assertEqual(
                                first, _PATTERN,
                                f"cycle {cycle}: first burst got back "
                                f"{len(first)}/{len(_PATTERN)} bytes")

                            # Second burst, started immediately -- no gap.
                            t2, err2 = _start_burst_writer(port)
                            time.sleep(0.02)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() didn't flip "
                                f"false again for the immediately-following "
                                f"second burst")

                            t2.join(timeout=8)
                            if err2:
                                raise err2[0]
                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the second burst")
                            second = peer.read_payload(len(_PATTERN), timeout=8.0)
                            self.assertEqual(
                                second, _PATTERN,
                                f"cycle {cycle}: second (back-to-back) "
                                f"burst got back {len(second)}/"
                                f"{len(_PATTERN)} bytes")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
