"""Control-plane sanity checks -- no peer wiring required.

Run directly:
    python test_RS232_control_plane.py

Or as part of the whole suite, from tests/:
    python -m unittest discover -s functional -p "test_*.py"
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import Nt124TestCase  # noqa: E402


class TestControlPlane(Nt124TestCase):

    def test_tx_empty_when_idle(self) -> None:
        for index, port in self.each_port():
            with self.subTest(port=index):
                self.assertTrue(port.wait_tx_empty(timeout=1.0))

    def test_set_line_coding_baud_accepted(self) -> None:
        # End on 115200 -- the baud every other functional/stress test uses.
        # Leaving a port on a different baud here means the next test's
        # SET_LINE_CODING(115200) is a genuine change rather than a no-op
        # repeat, which still costs one idle-frame byte on the wire (see
        # SEND_RX_LOCKUP_NOTES.md / the SET_LINE_CODING fix in uart.c).
        for baud in (1200, 9600, 19200, 115200, 230400, 115200):
            for index, port in self.each_port():
                with self.subTest(baud=baud, port=index):
                    port.set_line_coding(LineCoding(baud))  # must not raise / STALL

    def test_set_line_coding_parity_accepted(self) -> None:
        # End on "n" -- LineCoding's default, matching every other test.
        # See the comment in test_set_line_coding_baud_accepted above.
        for parity in ("n", "o", "e", "n"):
            for index, port in self.each_port():
                with self.subTest(parity=parity, port=index):
                    port.set_line_coding(LineCoding(115200, parity=parity))

    def test_control_lines_toggle(self) -> None:
        for index, port in self.each_port():
            with self.subTest(port=index):
                port.set_control_lines(dtr=True, rts=True)
                port.set_control_lines(dtr=False, rts=False)

    def test_repeated_control_requests_no_stall(self) -> None:
        # Regression coverage for -EPIPE failures seen on control transfers
        # under load: hammer the endpoint.
        for index, port in self.each_port():
            with self.subTest(port=index):
                for _ in range(200):
                    port.set_control_lines(dtr=True, rts=True)
                    port.tx_empty()


if __name__ == "__main__":
    unittest.main()
