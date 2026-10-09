"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) alongside
GET_TXEMPTY tracking during an active transfer -- the intersection of
test_RS232_control_line_cycling.py and test_RS232_tx_empty_cycling.py,
neither of which checks this combination.

usb_in_tx_state (uart.c) -- the flag send_ctrl_update() checks before
writing an unsolicited status update -- only ever reflects RX delivery
activity (set inside send_rx()), never TX activity (tx_state/tx_empty);
the two are completely independent paths in source. Worth confirming
empirically rather than assuming:

1. A CTS/DSR-triggered status update still arrives promptly and correctly
   while a TX transfer is actively draining (tx_empty() reading false) --
   confirms TX activity never blocks or delays control-line status
   reporting.
2. Repeatedly toggling the host-controlled DTR/RTS output while a TX
   transfer is draining never disturbs tx_empty()'s own false-during/
   true-after tracking -- confirms the reverse direction holds too.

Both at a slow baud (1200), same reasoning as test_RS232_tx_empty_cycling.py:
wide enough a gap between "USB write done" and "wire actually drained" to
reliably observe.

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_tx_empty_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_BAUD = 1200
_PATTERN = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud
_REPEATS = 10  # adjust for more/less cycling


class TestControlLineTxEmptyCycling(PeerTestCase):

    def test_cts_dsr_status_arrives_promptly_during_active_tx_transfer_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(_BAUD))
                peer.configure(_BAUD)
                try:
                    for cycle in range(_REPEATS):
                        rts_state = (cycle % 2 == 0)
                        dtr_state = (cycle % 2 == 1)
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")
                            drain_port(port, timeout=100)

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(_PATTERN, timeout=2000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.05)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true right "
                                f"after starting the TX transfer")

                            peer.set_rts(rts_state)
                            peer.set_dtr(dtr_state)
                            pkt = port.read_packet(timeout=1000)
                            self.assertEqual(
                                pkt.cts, rts_state,
                                f"cycle {cycle}: status reported CTS="
                                f"{pkt.cts}, expected {rts_state} while a "
                                f"TX transfer was actively draining -- "
                                f"status={pkt.describe()}")
                            self.assertEqual(
                                pkt.dsr, dtr_state,
                                f"cycle {cycle}: status reported DSR="
                                f"{pkt.dsr}, expected {dtr_state} while a "
                                f"TX transfer was actively draining -- "
                                f"status={pkt.describe()}")

                            t.join(timeout=3)
                            if write_error:
                                raise write_error[0]
                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the transfer finished")
                            peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_dtr_rts_toggling_does_not_disturb_tx_empty_tracking_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(_BAUD))
                peer.configure(_BAUD)
                try:
                    for cycle in range(_REPEATS):
                        asserted = (cycle % 2 == 0)
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
                            time.sleep(0.05)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true right "
                                f"after starting the TX transfer")

                            port.set_control_lines(dtr=asserted, rts=asserted)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() read true "
                                f"immediately after toggling DTR/RTS "
                                f"output mid-transfer")

                            t.join(timeout=3)
                            if write_error:
                                raise write_error[0]
                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the transfer finished")
                            peer.read_payload(len(_PATTERN), timeout=2.0)
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
