"""usbuart_set_flow_control() (uart.c) -- never exercised anywhere else in
this suite. Two states: USART_FLOWCONTROL_CTS or NONE, applied via
libopencm3's usart_set_flow_control() (hardware auto-flow: the USART
pauses TX mid-transmission whenever its CTS input is deasserted, entirely
in silicon, invisible to firmware code once enabled).

The bench's null-modem crossover means the peer's own RTS output drives the
nt124 port's CTS input (see peer.py's Peer.open() comment) -- so
peer.set_rts(False) is how these tests deassert the nt124's CTS.

Hardware auto-CTS only actually works on ports 2 and 3 (UART3/UART2) --
confirmed while building this test, see SEND_RX_LOCKUP_NOTES.md's "Newly
discovered issues". Port 1 (UART4) has no CTS/RTS pins in silicon at all
(a simplified UART, not a full USART), and port 0 (UART1)'s CTS pin is
wired to a plain GPIO rather than USART1's actual hardware CTS pin.
Neither is fixed yet, so this file tests the capable ports (2/3) for the
real pausing behavior and the other two (0/1) only for "enabling flow
control doesn't break anything", not for an effect it can't have.

Requires TX/RX (and RTS/CTS) wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_flow_control.py
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


class TestFlowControl(PeerTestCase):

    def test_flow_control_pauses_tx_when_cts_deasserted(self) -> None:
        pattern = bytes(i & 0xFF for i in range(512))
        for index in _HW_CTS_CAPABLE_PORTS:
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                peer.flush_input()
                peer.set_rts(False)  # deassert -- crosses to nt124's CTS input

                write_error: list[Exception] = []

                def writer() -> None:
                    try:
                        port.write(pattern, timeout=5000)
                    except Exception as e:  # noqa: BLE001 -- surfaced below
                        write_error.append(e)

                t = threading.Thread(target=writer, daemon=True)
                t.start()
                try:
                    time.sleep(0.3)
                    partial = peer.read_available()
                    self.assertLess(len(partial), len(pattern),
                                     "TX wasn't paused by flow control while "
                                     "CTS was deasserted")

                    peer.set_rts(True)  # reassert -- TX should resume
                    rest = peer.read_payload(len(pattern) - len(partial), timeout=3.0)
                finally:
                    t.join(timeout=5)
                    peer.set_rts(True)
                    port.set_flow_control(False)
                if write_error:
                    raise write_error[0]

                received = partial + rest
                self.assertEqual(received, pattern,
                                  f"got back {len(received)}/{len(pattern)} bytes "
                                  f"after CTS was reasserted -- TX should have "
                                  f"resumed and completed")

    def test_flow_control_enabled_harmless_where_hw_cts_unsupported(self) -> None:
        """Ports 0/1 can't physically pause on CTS (see module docstring) --
        confirm enabling flow control there is at least harmless: a normal
        transfer with CTS held deasserted the whole time still arrives
        complete and unpaused, rather than erroring or hanging."""
        pattern = bytes(range(64))
        for index in (0, 1):
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                peer.flush_input()
                peer.set_rts(False)
                try:
                    port.write(pattern, timeout=2000)
                    received = peer.read_payload(len(pattern), timeout=2.0)
                finally:
                    peer.set_rts(True)
                    port.set_flow_control(False)

                self.assertEqual(received, pattern,
                                  f"got back {len(received)}/{len(pattern)} "
                                  f"bytes -- enabling flow control on a port "
                                  f"without hardware CTS support shouldn't "
                                  f"disrupt a normal transfer")

    def test_flow_control_disabled_ignores_cts(self) -> None:
        pattern = bytes(range(64))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(False)
                peer.flush_input()
                peer.set_rts(False)  # deassert -- should have no effect now
                try:
                    port.write(pattern, timeout=2000)
                    received = peer.read_payload(len(pattern), timeout=2.0)
                finally:
                    peer.set_rts(True)  # restore Peer.open()'s default

                self.assertEqual(received, pattern,
                                  f"got back {len(received)}/{len(pattern)} bytes "
                                  f"-- flow control disabled should ignore CTS "
                                  f"entirely")


if __name__ == "__main__":
    unittest.main()
