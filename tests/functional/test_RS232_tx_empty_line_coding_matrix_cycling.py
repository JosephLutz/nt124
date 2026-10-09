"""GET_TXEMPTY across the full line-coding format matrix (databits/parity/
stopbits combinations) -- the intersection of test_RS232_tx_empty_cycling.py
and test_RS232_line_coding_matrix.py, neither of which checks this
combination. test_RS232_tx_empty_line_coding_cycling.py already covers
baud-only changes; this file instead cycles through genuine FRAME FORMAT
changes, which exercise more of set_uart_parameters()'s reconfigure path
(parity hardware registers, new_bits/9-bit-mode computation, tim_table
frame-length lookup) than a baud-only change does.

Uses the same representative combination list as
test_RS232_line_coding_matrix.py, duplicated locally so this file stays
runnable standalone.

Two scenarios, each run _REPEATS times per port, at a slow baud (1200) so
the gap between "USB write done" and "wire actually drained" is wide
enough to reliably observe:

1. The safe case: cycle through every combination in the matrix *between*
   transfers (not concurrently with one) -- tx_empty() must still
   correctly report false during and true after each transfer, across
   every format in the matrix.
2. Related to but distinct from
   known_issues/line-coding-change-corrupts-in-flight-dma.md and its
   regression trigger test_RS232_line_coding_mid_transfer.py (which checks
   the *data* getting corrupted): does tx_empty()'s own bookkeeping stay
   self-consistent when a genuine FRAME FORMAT change (not just baud)
   lands mid-transfer -- never reporting empty too early, and eventually
   reporting true once the transfer (however corrupted) actually
   completes.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_line_coding_matrix_cycling.py
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
_BAUD = 1200
_PATTERN = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud

# Same representative combinations as test_RS232_line_coding_matrix.py:
# every parity value at 8 databits/1 stopbit, every stopbits value at 8N,
# and 7-databit framing (folded into a 9-bit hardware frame whenever
# parity is enabled) with each parity.
_COMBINATIONS = [
    (8, "n", 1.0),
    (8, "o", 1.0),
    (8, "e", 1.0),
    (8, "n", 2.0),
    (8, "n", 1.5),
    (7, "o", 1.0),
    (7, "e", 1.0),
]


class TestTxEmptyLineCodingMatrixCycling(PeerTestCase):

    def test_tx_empty_correct_across_matrix_cycling_between_transfers(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for pass_ in range(_REPEATS):
                        for databits, parity, stopbits in _COMBINATIONS:
                            with self.subTest(pass_=pass_, databits=databits,
                                               parity=parity, stopbits=stopbits):
                                port.set_line_coding(LineCoding(
                                    _BAUD, databits=databits, parity=parity,
                                    stopbits=stopbits))
                                peer.configure(_BAUD, databits=databits,
                                               parity=parity, stopbits=stopbits)
                                self.assertTrue(
                                    port.wait_tx_empty(timeout=1.0),
                                    f"pass {pass_} @ {databits}{parity}"
                                    f"{stopbits}: not idle before this "
                                    f"combination started")

                                port.write(_PATTERN, timeout=2000)
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"pass {pass_} @ {databits}{parity}"
                                    f"{stopbits}: tx_empty() was true "
                                    f"immediately after writing")

                                self.assertTrue(
                                    port.wait_tx_empty(timeout=2.0),
                                    f"pass {pass_} @ {databits}{parity}"
                                    f"{stopbits}: tx_empty() never became "
                                    f"true again")

                                peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_tx_empty_stays_consistent_through_mid_transfer_matrix_change(self) -> None:
        pattern = bytes(i & 0xFF for i in range(128))  # ~1s to drain at 1200 baud
        combo_a = (8, "n", 1.0)
        combo_b = (7, "e", 1.0)
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            port.set_line_coding(LineCoding(
                                _BAUD, databits=combo_a[0], parity=combo_a[1],
                                stopbits=combo_a[2]))
                            peer.configure(_BAUD, databits=combo_a[0],
                                           parity=combo_a[1], stopbits=combo_a[2])
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
                                f"the format change even happened")

                            # Genuine FRAME FORMAT change, mid-transfer --
                            # not just baud this time.
                            port.set_line_coding(LineCoding(
                                _BAUD, databits=combo_b[0], parity=combo_b[1],
                                stopbits=combo_b[2]))

                            for poll in range(5):
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"cycle {cycle}: tx_empty() read true "
                                    f"too soon after the mid-transfer "
                                    f"format change (poll {poll})")
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
