"""Modem status lines (DTR/RTS output, CTS/DSR/DCD/RI input) -- the
Packet.cts/.dsr/.dcd/.ri and Peer.cts/.dsr/.dcd/.ri properties exist but
were never asserted on anywhere else in this suite.

There's no GET_CONTROL_LINE_STATE request, so the only way to observe the
nt124's *input* lines is via the 2-byte status header on the next RX/IN
packet -- either real data, or an unsolicited push scheduled by
schedule_ctrl_update() (uart.c) when an EXTI-watched line changes.

CTS and DSR are automated here (the bench's null-modem crossover lets
peer.set_rts()/set_dtr() drive the nt124's CTS/DSR inputs directly, per
peer.py's Peer.open() comment). DCD and RI are a harder case: standard
USB-serial adapters (including this bench's peers) only drive RTS/DTR --
DCD and RI are input-only on both ends of a normal RS-232 link, so nothing
in this rig can toggle them in software. The one class of interactive test
here confirms the exti9_5_isr() DCD-routing fix (uart.c) by physically
unplugging/reconnecting a peer's cable -- a real, if manual, signal change
-- and checking which port the resulting update arrives on, not what value
it carries (the nt124's DCD/DSR/CTS/RI inputs are floating, GPIO_CNF_INPUT_
FLOAT with no pull resistor, so the resting level after a disconnect isn't
guaranteed -- but the EXTI is edge-triggered, so *a* transition firing on
the right port, and not on the wrong one, is a clean, deterministic check
regardless of polarity).

Requires TX/RX/RTS/DTR wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus. The interactive
test additionally needs a human at the bench and is skipped unless
NT124_INTERACTIVE=1 is set, so an unattended `unittest discover` run
doesn't hang waiting for input().

Run directly:
    python test_RS232_modem_status_lines.py
    NT124_INTERACTIVE=1 python test_RS232_modem_status_lines.py
"""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usb.core  # noqa: E402

from support import PeerTestCase  # noqa: E402

_INTERACTIVE = os.environ.get("NT124_INTERACTIVE") == "1"


def _drain(port, timeout=50) -> None:
    """Discard any stale pending status packet before a test toggles a
    line, so the next read is really the one triggered by that toggle."""
    try:
        while True:
            port.read_packet(timeout=timeout)
    except usb.core.USBError:
        pass


class TestModemStatusLines(PeerTestCase):

    def test_dtr_rts_output_reaches_peer_dsr_cts(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    port.set_control_lines(dtr=True, rts=True)
                    time.sleep(0.05)
                    self.assertTrue(peer.dsr, "peer didn't see DSR asserted")
                    self.assertTrue(peer.cts, "peer didn't see CTS asserted")

                    port.set_control_lines(dtr=False, rts=False)
                    time.sleep(0.05)
                    self.assertFalse(peer.dsr, "peer still saw DSR asserted "
                                                "after deassert")
                    self.assertFalse(peer.cts, "peer still saw CTS asserted "
                                                "after deassert")
                finally:
                    # Peer.open() assumes DTR/RTS asserted (see peer.py).
                    port.set_control_lines(dtr=True, rts=True)

    def test_peer_control_lines_reported_as_nt124_status(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                _drain(port)
                try:
                    peer.set_rts(False)
                    pkt = port.read_packet(timeout=1000)
                    self.assertFalse(pkt.cts, f"expected CTS deasserted, "
                                               f"status={pkt.describe()}")

                    peer.set_rts(True)
                    pkt = port.read_packet(timeout=1000)
                    self.assertTrue(pkt.cts, f"expected CTS asserted, "
                                              f"status={pkt.describe()}")

                    peer.set_dtr(False)
                    pkt = port.read_packet(timeout=1000)
                    self.assertFalse(pkt.dsr, f"expected DSR deasserted, "
                                               f"status={pkt.describe()}")

                    peer.set_dtr(True)
                    pkt = port.read_packet(timeout=1000)
                    self.assertTrue(pkt.dsr, f"expected DSR asserted, "
                                              f"status={pkt.describe()}")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)


@unittest.skipUnless(_INTERACTIVE, "set NT124_INTERACTIVE=1 to run interactive "
                                    "tests that need manual cable action")
class TestModemStatusLinesInteractive(PeerTestCase):
    """Regression test for the exti9_5_isr() DCD-routing bug (uart.c):
    UART4's DCD (ACM port 1, board silkscreen "Port 2") used to schedule its
    status update on uarts[1]/UART2 (ACM port 3, "Port 4") instead of its
    own port."""

    def test_dcd_change_reported_on_its_own_port_not_a_neighbor(self) -> None:
        port2, port4 = self.board.port(1), self.board.port(3)
        _drain(port2)
        _drain(port4)

        input("\nUnplug (or reconnect) the serial cable at Port 2's peer "
              "adapter now, then press Enter: ")

        try:
            port2.read_packet(timeout=2000)
        except usb.core.USBError:
            self.fail("Port 2 got no status update at all after its own "
                      "DCD line changed")

        with self.assertRaises(usb.core.USBError,
                                msg="Port 4 received a spurious status update "
                                    "from Port 2's DCD change -- the EXTI9 "
                                    "misrouting bug has regressed"):
            port4.read_packet(timeout=500)


if __name__ == "__main__":
    unittest.main()
