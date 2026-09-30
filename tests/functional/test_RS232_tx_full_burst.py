"""Forces the TX_FULL state (usbuart_usb_out_cb/uart_TX_DMA_empty, uart.c):
with only NUM_TX_BUFFERS=2 ping-pong buffers, a 3rd max-size OUT packet
arriving before the wire has drained the first two is parked -- its CTR_RX
is cleared directly without usbd_ep_read_packet(), leaving it un-drained in
the USB peripheral's OUT FIFO -- and only read out later, from the TX-DMA-
complete ISR, once a buffer frees up. Every other TX test in this suite
sends payloads small/slow enough (or paced via a single blocking write)
that this path is never exercised. Forcing it here: a low baud rate (1200)
makes the wire drain slowly enough that 3 back-to-back 32-byte packets
reliably outrun it. (Not 300 -- that baud has its own separate,
pre-existing, unresolved data-integrity bug, unrelated to TX_FULL: 1200
baud and up all round-trip correctly, only 300 baud doesn't.)

This checks correctness through that specific path (no corruption or
reordering across the parked-packet handoff and the buffer-index
wraparound in uart_TX_DMA_empty), not the state transitions themselves.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_full_burst.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase  # noqa: E402


class TestTxFullBurst(PeerTestCase):

    def test_tx_full_state_multi_packet_burst(self) -> None:
        pattern = bytes(i & 0xFF for i in range(96))  # 3 x 32-byte packets
        chunks = [pattern[i:i + 32] for i in range(0, len(pattern), 32)]

        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                # A genuine reconfigure is allowed one idle-frame glitch
                # byte on the wire -- give it time to arrive before
                # flushing it away.
                time.sleep(0.05)
                peer.flush_input()

                write_error: list[Exception] = []

                def writer() -> None:
                    try:
                        for chunk in chunks:
                            port.write(chunk, timeout=8000)
                    except Exception as e:  # noqa: BLE001 -- surfaced below
                        write_error.append(e)

                t = threading.Thread(target=writer, daemon=True)
                t.start()
                try:
                    received = peer.read_payload(len(pattern), timeout=8.0)
                finally:
                    t.join(timeout=8)
                if write_error:
                    raise write_error[0]

                self.assertEqual(received, pattern,
                                  f"got back {len(received)}/{len(pattern)} "
                                  f"bytes -- a 3-packet burst forcing TX_FULL "
                                  f"produced corrupted or incomplete data")

        # Leave every port back on the suite's standard setting.
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
