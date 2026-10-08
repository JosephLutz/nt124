"""Repeated-cycle hardware flow-control tests, mirroring the other cycling
files' pattern. test_RS232_flow_control.py checks each of its three
scenarios once; nothing repeats the pause/resume cycle, which is exactly
the kind of thing that could expose TX getting stuck paused, or a stale
auto-CTS state surviving into a later transfer, after more than one use.

Three scenarios, each run _REPEATS times:

1. On the hardware-CTS-capable ports (2/3, see test_RS232_flow_control.py's
   module docstring for the port 0/1 vs 2/3 asymmetry): deassert CTS
   mid-write, confirm TX pauses, reassert, confirm the rest arrives --
   repeated.
2. On the non-capable ports (0/1): flow control enabled, CTS held
   deasserted the whole time, confirm a normal transfer is still
   unaffected -- repeated.
3. On all 4 ports with flow control disabled: CTS deasserted, confirm it's
   ignored and the transfer completes normally -- repeated.

Requires TX/RX (and RTS/CTS) wired between each port and its peer, and the
transceiver set to a mode that reaches the external bus.

Run directly:
    python test_RS232_flow_control_cycling.py
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
_HW_CTS_CAPABLE_PORTS = (2, 3)


class TestFlowControlCycling(PeerTestCase):

    def test_pause_resume_cycling_repeated(self) -> None:
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
                                time.sleep(0.2)
                                partial = peer.read_available()
                                self.assertLess(
                                    len(partial), len(pattern),
                                    f"cycle {cycle}: TX wasn't paused by "
                                    f"flow control while CTS was deasserted")

                                peer.set_rts(True)  # reassert -- TX should resume
                                rest = peer.read_payload(
                                    len(pattern) - len(partial), timeout=3.0)
                            finally:
                                t.join(timeout=5)
                                peer.set_rts(True)
                            if write_error:
                                raise write_error[0]

                            received = partial + rest
                            self.assertEqual(
                                received, pattern,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(pattern)} bytes "
                                f"after CTS was reasserted")
                finally:
                    port.set_flow_control(False)

    def test_flow_control_harmless_where_unsupported_repeated(self) -> None:
        pattern = bytes(range(64))
        for index in (0, 1):
            port, peer = self.board.port(index), self.peers[index]
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(True)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            peer.flush_input()
                            peer.set_rts(False)
                            try:
                                port.write(pattern, timeout=2000)
                                received = peer.read_payload(len(pattern), timeout=2.0)
                            finally:
                                peer.set_rts(True)
                            self.assertEqual(
                                received, pattern,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(pattern)} bytes -- "
                                f"enabling flow control on a port without "
                                f"hardware CTS support shouldn't disrupt a "
                                f"normal transfer")
                finally:
                    port.set_flow_control(False)

    def test_flow_control_disabled_ignores_cts_repeated(self) -> None:
        pattern = bytes(range(64))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                port.set_flow_control(False)
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        peer.flush_input()
                        peer.set_rts(False)  # deassert -- should have no effect
                        try:
                            port.write(pattern, timeout=2000)
                            received = peer.read_payload(len(pattern), timeout=2.0)
                        finally:
                            peer.set_rts(True)  # restore Peer.open()'s default
                        self.assertEqual(
                            received, pattern,
                            f"cycle {cycle}: got back "
                            f"{len(received)}/{len(pattern)} bytes -- flow "
                            f"control disabled should ignore CTS entirely")


if __name__ == "__main__":
    unittest.main()
