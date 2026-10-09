"""GET_TXEMPTY under hardware flow control -- the intersection of
test_RS232_tx_empty_cycling.py and test_RS232_flow_control_cycling.py,
neither of which checks this combination. tx_empty() is expected to stay
false for as long as a transfer is genuinely paused by CTS, not just for
the data's own normal drain time: hardware auto-CTS stalls the USART
itself, so uart_TX_DMA_empty()'s transfer-complete interrupt (the only
thing that ever flips tx_empty true, via schedule_ctrl_update(), uart.c)
simply can't fire until CTS allows the last byte to actually finish
shifting out.

Both scenarios run on the hardware-CTS-capable ports only (2/3, see
test_RS232_flow_control.py's module docstring for the port 0/1 vs 2/3
asymmetry):

1. CTS held deasserted from before a write even starts: confirm no data
   gets through, tx_empty() stays false for a window well past a normal
   drain time, and only becomes true once CTS is reasserted and the
   transfer actually completes -- repeated _REPEATS times.
2. One continuous transfer with multiple CTS pause/resume toggles while
   it's actively in flight (mirrors test_RS232_flow_control_cycling.py's
   continuous-transfer scenario): tx_empty() must read false throughout,
   including during every paused window, only becoming true once the
   whole transfer finishes.

Requires TX/RX (and RTS/CTS) wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_flow_control_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402

_HW_CTS_CAPABLE_PORTS = (2, 3)
_REPEATS = 10  # adjust for more/less cycling


class TestTxEmptyFlowControlCycling(PeerTestCase):

    def test_tx_empty_stays_false_while_paused_by_flow_control_repeated(self) -> None:
        pattern = bytes(i & 0xFF for i in range(64))
        for index in _HW_CTS_CAPABLE_PORTS:
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")
                            peer.flush_input()
                            peer.set_rts(False)  # deassert BEFORE writing -- paused from byte 1

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(pattern, timeout=5000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.05)  # let the write reach the firmware

                            self.assertEqual(
                                len(peer.read_available()), 0,
                                f"cycle {cycle}: data arrived despite CTS "
                                f"being held deasserted before the write "
                                f"even started")

                            # Poll well past a normal drain time at this
                            # baud/size -- it should never matter, since
                            # the transfer can't progress while paused.
                            poll_until = time.monotonic() + 0.3
                            polls = 0
                            while time.monotonic() < poll_until:
                                self.assertFalse(
                                    port.tx_empty(),
                                    f"cycle {cycle}: tx_empty() read true "
                                    f"while TX should still be paused by "
                                    f"flow control (poll {polls})")
                                polls += 1
                                time.sleep(0.02)
                            self.assertGreater(polls, 5,
                                                "sanity: too few polls "
                                                "happened to mean anything")

                            peer.set_rts(True)  # release -- transfer can now complete
                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after CTS was reasserted")

                            t.join(timeout=5)
                            if write_error:
                                raise write_error[0]

                            received = peer.read_payload(len(pattern), timeout=2.0)
                            self.assertEqual(
                                received, pattern,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(pattern)} bytes "
                                f"after CTS was reasserted")
                finally:
                    peer.set_rts(True)
                    port.set_flow_control(False)

    def test_tx_empty_during_multiple_toggles_in_continuous_transfer(self) -> None:
        pattern = bytes(i & 0xFF for i in range(8192))
        n_toggles = 5
        for index in _HW_CTS_CAPABLE_PORTS:
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                peer.flush_input()
                peer.set_rts(True)
                self.assertTrue(port.wait_tx_empty(timeout=1.0),
                                 "not idle before starting")

                write_error: list[Exception] = []

                def writer() -> None:
                    try:
                        port.write(pattern, timeout=15000)
                    except Exception as e:  # noqa: BLE001 -- surfaced below
                        write_error.append(e)

                t = threading.Thread(target=writer, daemon=True)
                t.start()
                time.sleep(0.05)
                self.assertFalse(port.tx_empty(),
                                  "tx_empty() was true immediately after "
                                  "the transfer started")

                try:
                    for toggle in range(n_toggles):
                        time.sleep(0.1)  # let some real data flow first
                        peer.set_rts(False)  # pause mid-stream
                        time.sleep(0.05)
                        self.assertFalse(
                            port.tx_empty(),
                            f"toggle {toggle}: tx_empty() read true right "
                            f"after pausing mid-transfer")

                        time.sleep(0.15)  # stay paused
                        self.assertFalse(
                            port.tx_empty(),
                            f"toggle {toggle}: tx_empty() became true "
                            f"while still paused mid-transfer")

                        peer.set_rts(True)  # resume
                finally:
                    t.join(timeout=15)
                    peer.set_rts(True)
                if write_error:
                    raise write_error[0]

                self.assertTrue(
                    port.wait_tx_empty(timeout=5.0),
                    "tx_empty() never became true after the transfer, "
                    "with its multiple pause/resume toggles, finished")

                peer.read_payload(len(pattern), timeout=5.0)
                port.set_flow_control(False)


if __name__ == "__main__":
    unittest.main()
