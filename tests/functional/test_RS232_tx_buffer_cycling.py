"""TX-side mirror of test_RS232_rx_buffer_cycling.py. CDCACM_PACKET_SIZE
(32) is the TX ping-pong buffer unit (NUM_TX_BUFFERS=2, see
usbuart_usb_out_cb()/uart_TX_DMA_empty() in uart.c), playing the role
RX_BUFFER_SIZE plays on the RX side. test_RS232_tx_full_burst.py checks a
3-packet burst once, at an artificially slow baud chosen to force TX_FULL
reliably; this file instead repeats the send/wait/receive cycle many times
at the suite's normal 115200 baud, where the wire is still far slower than
USB regardless, to catch anything that only shows up after repeated
ping-pong buffer-index wraparounds rather than a single occurrence.

Three scenarios, each run _REPEATS times per port, sending/waiting/
receiving/sending again each time:

1. Exactly 1x CDCACM_PACKET_SIZE per cycle -- one ping-pong buffer, no
   TX_FULL involved.
2. Exactly 2x CDCACM_PACKET_SIZE per cycle -- both ping-pong buffers full
   at once.
3. Exactly 3x CDCACM_PACKET_SIZE per cycle -- a 3rd packet's worth with
   only 2 buffers available is expected to force the TX_FULL state (see
   test_RS232_tx_full_burst.py) every cycle.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_buffer_cycling.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402

CDCACM_PACKET_SIZE = 32
_REPEATS = 10  # adjust for more/less cycling


def _pattern(size: int, salt: int) -> bytes:
    """A size-byte pattern that varies cycle to cycle (via `salt`), so a
    bug that confuses one cycle's leftover data with the next one's would
    actually show up as a mismatch instead of coincidentally matching."""
    return bytes((salt + i) & 0xFF for i in range(size))


class TestTxBufferCycling(PeerTestCase):

    def _run(self, packet_multiple: int) -> None:
        size = packet_multiple * CDCACM_PACKET_SIZE
        for index, port, peer in self.each_port_and_peer():
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)
            for cycle in range(_REPEATS):
                pattern = _pattern(size, cycle)
                with self.subTest(port=index, packets=packet_multiple, cycle=cycle):
                    received = tx_one_way(port, peer, pattern)
                    self.assertEqual(received, pattern,
                                      f"port {index}, cycle {cycle}, "
                                      f"{packet_multiple}x packet: peer got "
                                      f"{len(received)}/{size} bytes")

    def test_one_full_packet_repeated(self) -> None:
        self._run(1)

    def test_two_full_packets_repeated(self) -> None:
        self._run(2)

    def test_three_full_packets_repeated(self) -> None:
        self._run(3)


if __name__ == "__main__":
    unittest.main()
