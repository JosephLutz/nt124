"""GET_TXEMPTY across SET_LINE_CODING changes -- the intersection of
test_RS232_tx_empty_cycling.py and test_RS232_line_coding_cycling.py,
neither of which checks this combination.

Two scenarios:

1. The safe case: alternate genuine line coding changes *between*
   transfers (not concurrently with one), confirming tx_empty() still
   correctly reports false during and true after each transfer across
   many reconfigure/transfer cycles -- repeated _REPEATS times.
2. The characterization case, related to but distinct from
   known_issues/line-coding-change-corrupts-in-flight-dma.md and its
   regression trigger test_RS232_line_coding_mid_transfer.py: that known
   issue is about the *data* getting corrupted when a reconfigure lands
   mid-transfer, since set_uart_parameters() (uart.c) never touches the
   TX DMA channel or tx_state/tx_empty. This checks the *status* side
   instead -- does tx_empty()'s own bookkeeping stay self-consistent
   (never reports empty before the DMA transfer has actually completed,
   and eventually reports true once it does) when a genuine reconfigure
   lands mid-transfer, even though the data itself is known to come out
   corrupted -- repeated _REPEATS times.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_line_coding_cycling.py
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
_BAUD_A = 9600
_BAUD_B = 1200


class TestTxEmptyLineCodingCycling(PeerTestCase):

    def test_tx_empty_correct_across_alternating_reconfigures_between_transfers(self) -> None:
        pattern = bytes(i & 0xFF for i in range(64))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        baud = _BAUD_A if cycle % 2 == 0 else _BAUD_B
                        with self.subTest(cycle=cycle, baud=baud):
                            port.set_line_coding(LineCoding(baud))
                            peer.configure(baud)
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle} @ {baud}: not idle before "
                                f"this cycle started")

                            port.write(pattern, timeout=2000)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle} @ {baud}: tx_empty() was "
                                f"true immediately after writing")

                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle} @ {baud}: tx_empty() never "
                                f"became true again")

                            peer.read_payload(len(pattern), timeout=2.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_tx_empty_stays_consistent_through_mid_transfer_reconfigure(self) -> None:
        pattern = bytes(i & 0xFF for i in range(128))  # ~133ms to drain at 9600 baud
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            port.set_line_coding(LineCoding(_BAUD_A))
                            peer.configure(_BAUD_A)
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")
                            peer.flush_input()

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(pattern, timeout=5000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.05)  # partway into the transfer
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true before "
                                f"the reconfigure even happened")

                            # Genuine reconfigure, mid-transfer -- the
                            # known_issue's trigger, slowing down rather
                            # than speeding up so there's a wide window
                            # left to observe.
                            port.set_line_coding(LineCoding(_BAUD_B))

                            # Must not flip true prematurely right after
                            # the reconfigure -- the DMA transfer is still
                            # genuinely in flight (see the known_issue:
                            # set_uart_parameters() never touches it).
                            for poll in range(5):
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"cycle {cycle}: tx_empty() read true "
                                    f"too soon after the mid-transfer "
                                    f"reconfigure (poll {poll})")
                                time.sleep(0.02)

                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the reconfigured transfer "
                                f"finished")

                            t.join(timeout=5)
                            if write_error:
                                raise write_error[0]

                            # Whatever arrived is expected to be corrupted
                            # (see known_issues/line-coding-change-
                            # corrupts-in-flight-dma.md) -- drain it
                            # without checking content, this test only
                            # cares about tx_empty()'s own bookkeeping.
                            peer.read_until_quiet(quiet=0.5, max_wait=3.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
