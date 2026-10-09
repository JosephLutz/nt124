"""Modem status lines (DTR/RTS output, CTS/DSR input reporting) around a
forced TX_FULL burst -- the intersection of
test_RS232_control_line_cycling.py and test_RS232_tx_full_burst.py,
neither of which checks this combination. TX_FULL congestion is purely an
OUT-endpoint (host -> device) phenomenon (usbuart_usb_out_cb()/
uart_TX_DMA_empty(), uart.c); modem status updates go out the separate IN
endpoint -- but both are dispatched from the same shared usb_task()/
usbd_poll() loop, so it's worth confirming OUT-direction congestion never
starves or delays IN-direction status reporting, and that forcing TX_FULL
never disturbs the DTR/RTS output pins (never touched by that code path,
but never tested either).

Uses the same mechanism as test_RS232_tx_full_burst.py, duplicated locally
so this file stays runnable standalone: 3 back-to-back 32-byte packets at
1200 baud (the slowest supported baud) reliably outrun the wire and force
TX_FULL.

Two scenarios, each run _REPEATS times per port:

1. DTR/RTS output is set to a known state once, then a TX_FULL burst is
   forced repeatedly -- confirms the output is never disturbed.
2. The peer's RTS/DTR are toggled to a known, alternating state while a
   TX_FULL burst is actively in flight -- confirms a status update still
   arrives promptly and correctly, and the burst itself still completes
   intact.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_control_line_tx_full_burst_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_PATTERN = bytes(i & 0xFF for i in range(96))  # 3 x 32-byte packets
_CHUNKS = [_PATTERN[i:i + 32] for i in range(0, len(_PATTERN), 32)]


class TestControlLineTxFullBurstCycling(PeerTestCase):

    def test_dtr_rts_output_survives_tx_full_burst_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                time.sleep(0.05)
                peer.flush_input()
                try:
                    for asserted in (True, False):
                        port.set_control_lines(dtr=asserted, rts=asserted)
                        time.sleep(0.05)
                        for cycle in range(_REPEATS):
                            with self.subTest(asserted=asserted, cycle=cycle):
                                peer.flush_input()
                                for chunk in _CHUNKS:
                                    port.write(chunk, timeout=8000)
                                peer.read_payload(len(_PATTERN), timeout=8.0)
                                self.assertEqual(
                                    peer.dsr, asserted,
                                    f"cycle {cycle}: DSR changed after a "
                                    f"TX_FULL burst (expected it to stay "
                                    f"{asserted})")
                                self.assertEqual(
                                    peer.cts, asserted,
                                    f"cycle {cycle}: CTS changed after a "
                                    f"TX_FULL burst (expected it to stay "
                                    f"{asserted})")
                finally:
                    port.set_control_lines(dtr=True, rts=True)  # Peer.open()'s assumed default
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)

    def test_modem_status_responsive_during_tx_full_burst_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                time.sleep(0.05)
                peer.flush_input()
                try:
                    for cycle in range(_REPEATS):
                        rts_state = (cycle % 2 == 0)
                        dtr_state = (cycle % 2 == 1)
                        with self.subTest(cycle=cycle):
                            drain_port(port, timeout=100)
                            peer.flush_input()

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    for chunk in _CHUNKS:
                                        port.write(chunk, timeout=8000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.05)  # let the burst get going / force TX_FULL
                            peer.set_rts(rts_state)
                            peer.set_dtr(dtr_state)

                            pkt = port.read_packet(timeout=1000)
                            self.assertEqual(
                                pkt.cts, rts_state,
                                f"cycle {cycle}: status reported CTS="
                                f"{pkt.cts}, expected {rts_state} during a "
                                f"TX_FULL burst -- status={pkt.describe()}")
                            self.assertEqual(
                                pkt.dsr, dtr_state,
                                f"cycle {cycle}: status reported DSR="
                                f"{pkt.dsr}, expected {dtr_state} during a "
                                f"TX_FULL burst -- status={pkt.describe()}")

                            received = peer.read_payload(len(_PATTERN), timeout=8.0)
                            t.join(timeout=8)
                            if write_error:
                                raise write_error[0]
                            self.assertEqual(
                                received, _PATTERN,
                                f"cycle {cycle}: got back "
                                f"{len(received)}/{len(_PATTERN)} bytes -- "
                                f"the burst forcing TX_FULL produced "
                                f"corrupted or incomplete data")
                finally:
                    peer.set_rts(True)
                    peer.set_dtr(True)
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
