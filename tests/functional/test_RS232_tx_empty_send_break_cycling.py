"""GET_TXEMPTY around NT124_USB_REQ_SEND_BREAK -- the intersection of
test_RS232_tx_empty_cycling.py and test_RS232_send_break_cycling.py,
neither of which checks this combination.
usbuart_send_break()/usart_send_break() (uart.c) only ever sets
USART_CR1_SBK -- it never touches tx_state/tx_empty or the TX DMA channel;
the break is purely a hardware-level insertion at the next character
boundary, independent of the firmware's TX bookkeeping.

Two scenarios, each run _REPEATS times per port:

1. While otherwise idle: tx_empty() must stay true throughout repeated
   send_break() calls -- a break alone isn't a "data transfer" in the
   firmware's bookkeeping sense, so it should never flip the flag false.
2. With a break landing while a transfer is actively in flight (mirrors
   test_RS232_send_break_cycling.py's mid-transfer scenario): tx_empty()
   must stay false throughout and only become true once the transfer (however
   affected by the break, per that file's confirmed characterization)
   actually completes.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_send_break_cycling.py
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


class TestTxEmptySendBreakCycling(PeerTestCase):

    def test_tx_empty_unaffected_by_send_break_while_idle_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                self.assertTrue(port.wait_tx_empty(timeout=1.0),
                                 "not idle before the test even started")
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        port.send_break()  # must not raise/STALL
                        self.assertTrue(
                            port.tx_empty(),
                            f"cycle {cycle}: tx_empty() read false right "
                            f"after send_break() while otherwise idle -- "
                            f"a break alone shouldn't affect it")
                        time.sleep(0.05)  # let the one-shot break frame finish
                        self.assertTrue(
                            port.tx_empty(),
                            f"cycle {cycle}: tx_empty() read false shortly "
                            f"after send_break() while otherwise idle")

    def test_tx_empty_correct_through_mid_transfer_break_repeated(self) -> None:
        pattern = bytes(i & 0xFF for i in range(128))  # ~1s to drain at 1200 baud
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
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
                            time.sleep(0.2)  # let TX settle solidly into TX_WORKING
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true before "
                                f"the break even happened")

                            port.send_break()  # must not raise/STALL mid-transfer
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() read true "
                                f"immediately after a mid-transfer break")

                            self.assertTrue(
                                port.wait_tx_empty(timeout=3.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true after the transfer finished")

                            t.join(timeout=5)
                            if write_error:
                                raise write_error[0]

                            # Not checked for content -- see
                            # test_RS232_send_break_cycling.py for the
                            # confirmed 1-2 spurious-byte characterization;
                            # this test only cares about tx_empty()'s own
                            # bookkeeping.
                            peer.read_until_quiet(quiet=0.5, max_wait=3.0)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
