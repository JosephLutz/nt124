"""GET_TXEMPTY alongside sustained parity error injection -- the
intersection of test_RS232_tx_empty_cycling.py and
test_RS232_parity_error_injection.py, neither of which checks this
combination. Parity error injection is purely an RX-side condition
(uart_RX()'s error branch, uart.c); tx_empty tracks TX-side state
entirely independently. Worth confirming empirically that one never
disturbs the other, especially since nt124 is full-duplex: a real TX
transfer and a sustained RX parity-error stream can genuinely be
happening at the same time on the same port.

Uses the same mismatched-parity mechanism as
test_RS232_parity_error_injection.py, duplicated locally (smaller pattern
size for repeated-cycle speed) so this file stays runnable standalone.

Two scenarios, each run _REPEATS times per port:

1. No TX activity at all: tx_empty() must stay true and remain responsive
   throughout repeated sustained-parity-error streams.
2. A real TX transfer and a sustained RX parity-error stream happening
   concurrently on the same port: tx_empty() must still correctly read
   false during the TX transfer and true once it finishes, unaffected by
   the simultaneous RX-side error stress.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_parity_error_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, drain_port, read_while_peer_writes  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_PARITY_PATTERN = bytes(i & 0xFF for i in range(1024))


def _stream_with_mismatched_parity(port, peer, timeout=3000):
    port.set_line_coding(LineCoding(115200, databits=8, parity="e"))
    peer.configure(115200, databits=8, parity="o")
    try:
        return read_while_peer_writes(port, peer, _PARITY_PATTERN, timeout=timeout)
    finally:
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        # A genuine reconfigure is allowed one idle-frame glitch byte on
        # the wire -- give it time to arrive, then flush it.
        time.sleep(0.05)
        peer.flush_input()
        drain_port(port)


class TestTxEmptyParityErrorCycling(PeerTestCase):

    def test_tx_empty_responsive_during_sustained_parity_errors_repeated(self) -> None:
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        self.assertTrue(
                            port.wait_tx_empty(timeout=1.0),
                            f"cycle {cycle}: not idle before this cycle "
                            f"started")
                        _stream_with_mismatched_parity(port, peer)
                        self.assertTrue(
                            port.tx_empty(),
                            f"cycle {cycle}: tx_empty() read false after a "
                            f"sustained parity-error stream with no TX "
                            f"activity at all -- it should be unaffected "
                            f"by RX-side errors")

    def test_tx_empty_tracks_correctly_during_simultaneous_parity_errors_repeated(self) -> None:
        tx_pattern = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud
        rx_pattern = bytes(i & 0xFF for i in range(256))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            port.set_line_coding(LineCoding(1200, databits=8, parity="e"))
                            peer.configure(1200, databits=8, parity="o")
                            time.sleep(0.05)
                            self.assertTrue(
                                port.wait_tx_empty(timeout=1.0),
                                f"cycle {cycle}: not idle before this "
                                f"cycle started")
                            peer.flush_input()

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(tx_pattern, timeout=2000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.05)
                            self.assertFalse(
                                port.tx_empty(),
                                f"cycle {cycle}: tx_empty() was true "
                                f"immediately after starting a TX transfer")

                            # Concurrently stream mismatched-parity data
                            # into nt124's RX side -- the TX transfer
                            # above is also still actively in flight.
                            peer.write(rx_pattern)
                            time.sleep(0.5)

                            self.assertTrue(
                                port.wait_tx_empty(timeout=2.0),
                                f"cycle {cycle}: tx_empty() never became "
                                f"true despite the TX transfer having had "
                                f"plenty of time, concurrent with a "
                                f"sustained RX parity-error stream")

                            t.join(timeout=3)
                            if write_error:
                                raise write_error[0]

                            # Drain whatever nt124 received -- not checked
                            # for content here, see
                            # test_RS232_parity_error_injection.py for
                            # that; this test only cares about
                            # tx_empty()'s own bookkeeping.
                            port.read_payload(len(rx_pattern), timeout=2000)
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)
                    time.sleep(0.05)
                    peer.flush_input()
                    drain_port(port)


if __name__ == "__main__":
    unittest.main()
