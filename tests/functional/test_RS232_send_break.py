"""NT124_USB_REQ_SEND_BREAK -- never exercised anywhere else in this suite.

usbuart_send_break() (uart.c) sets USART_CR1_SBK, which the STM32 USART
hardware auto-clears once the one-shot break frame has been sent -- there's
no explicit "stop break" and no ack/readback of "a break was sent" over
USB, so this can't be verified end-to-end without a scope/logic analyzer or
a receiver that reliably surfaces break detection (not something pyserial
exposes portably across adapter chips). What IS reliably testable: the
request doesn't disrupt the port, and nt124_send_break_callback() (usb.c)
only actually asserts the break when wValue == 0xFFFF -- any other value
(including the CDC-spec "stop break" convention of 0x0000) is a silent
no-op with no code path implemented for it.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_send_break.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, protocol as proto  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402

_VENDOR_OUT = 0x40


class TestSendBreak(PeerTestCase):

    def test_send_break_does_not_disrupt_subsequent_transfer(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                peer.flush_input()
                port.send_break()  # must not raise/STALL
                time.sleep(0.05)  # let the one-shot break frame finish
                recovered = tx_one_way(port, peer, pattern)
                self.assertEqual(recovered, pattern,
                                  "port didn't recover cleanly after send_break()")

    def test_send_break_non_ffff_value_is_a_noop(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.raw_ctrl_transfer(_VENDOR_OUT, proto.REQ_SEND_BREAK, 0x0000)
                recovered = tx_one_way(port, peer, pattern)
                self.assertEqual(recovered, pattern,
                                  "port didn't behave normally after a "
                                  "wValue=0 SEND_BREAK")


if __name__ == "__main__":
    unittest.main()
