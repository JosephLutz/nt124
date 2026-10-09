"""Modem status (CTS) reporting under hardware flow control -- the
intersection of test_RS232_control_line_cycling.py and
test_RS232_flow_control_cycling.py, neither of which checks this
combination. The same physical CTS pin drives two independent
consumers: the USART's own hardware auto-CTS (silicon-level TX pause,
see usbuart_set_flow_control(), uart.c) and the EXTI-triggered status
reporting (schedule_ctrl_update() -> uart_get_control_line_state(),
same file) that tells the host what CTS currently reads via the 2-byte
status header on every IN packet. These are independent paths reacting
to the same edge; this file confirms they stay consistent with each
other rather than one interfering with or lagging the other.

Both scenarios run on the hardware-CTS-capable ports only (2/3, see
test_RS232_flow_control.py's module docstring for the port 0/1 vs 2/3
asymmetry), with flow control enabled throughout:

1. Deassert CTS, confirm a status packet reports it deasserted AND TX is
   actually paused; reassert, confirm a status packet reports it
   reasserted AND the paused data completes -- repeated _REPEATS times.
2. One continuous transfer with multiple CTS pause/resume toggles while
   it's actively in flight (mirrors test_RS232_flow_control_cycling.py's
   continuous-transfer scenario): a status packet read right after each
   toggle must report the CTS state that was just set, not a stale or
   delayed value.

Requires TX/RX (and RTS/CTS) wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_flow_control_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_HW_CTS_CAPABLE_PORTS = (2, 3)
_REPEATS = 10  # adjust for more/less cycling


class TestControlLineFlowControlCycling(PeerTestCase):

    def test_cts_status_and_pause_consistent_repeated(self) -> None:
        pattern = bytes(i & 0xFF for i in range(256))
        for index in _HW_CTS_CAPABLE_PORTS:
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            drain_port(port)
                            peer.flush_input()
                            peer.set_rts(False)  # deassert -- pause TX, should report CTS low

                            pkt = port.read_packet(timeout=1000)
                            self.assertFalse(
                                pkt.cts,
                                f"cycle {cycle}: status packet didn't "
                                f"report CTS deasserted, "
                                f"status={pkt.describe()}")

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(pattern, timeout=5000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.2)
                            partial = peer.read_available()
                            self.assertLess(
                                len(partial), len(pattern),
                                f"cycle {cycle}: TX wasn't paused by flow "
                                f"control while CTS was deasserted")

                            peer.set_rts(True)  # reassert -- should report CTS high, TX resumes
                            pkt = port.read_packet(timeout=1000)
                            self.assertTrue(
                                pkt.cts,
                                f"cycle {cycle}: status packet didn't "
                                f"report CTS reasserted, "
                                f"status={pkt.describe()}")

                            rest = peer.read_payload(
                                len(pattern) - len(partial), timeout=3.0)
                            t.join(timeout=5)
                            if write_error:
                                raise write_error[0]

                            received = partial + rest
                            self.assertEqual(
                                received, pattern,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(pattern)} bytes "
                                f"after CTS was reasserted")
                finally:
                    peer.set_rts(True)
                    port.set_flow_control(False)

    def test_cts_status_tracks_multiple_toggles_in_continuous_transfer(self) -> None:
        pattern = bytes(i & 0xFF for i in range(8192))
        n_toggles = 5
        for index in _HW_CTS_CAPABLE_PORTS:
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                drain_port(port)
                peer.flush_input()
                peer.set_rts(True)

                write_error: list[Exception] = []

                def writer() -> None:
                    try:
                        port.write(pattern, timeout=15000)
                    except Exception as e:  # noqa: BLE001 -- surfaced below
                        write_error.append(e)

                t = threading.Thread(target=writer, daemon=True)
                t.start()
                try:
                    for toggle in range(n_toggles):
                        time.sleep(0.1)  # let some real data flow first
                        peer.set_rts(False)  # pause mid-stream

                        pkt = port.read_packet(timeout=1000)
                        self.assertFalse(
                            pkt.cts,
                            f"toggle {toggle}: status packet didn't report "
                            f"CTS deasserted mid-transfer, "
                            f"status={pkt.describe()}")

                        time.sleep(0.15)  # stay paused
                        peer.set_rts(True)  # resume

                        pkt = port.read_packet(timeout=1000)
                        self.assertTrue(
                            pkt.cts,
                            f"toggle {toggle}: status packet didn't report "
                            f"CTS reasserted mid-transfer, "
                            f"status={pkt.describe()}")
                finally:
                    t.join(timeout=15)
                    peer.set_rts(True)
                if write_error:
                    raise write_error[0]

                peer.read_payload(len(pattern), timeout=5.0)
                port.set_flow_control(False)


if __name__ == "__main__":
    unittest.main()
