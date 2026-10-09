"""GET_TXEMPTY alongside induced RX backpressure/overrun -- the
intersection of test_RS232_tx_empty_cycling.py and
test_RS232_rx_backpressure.py, neither of which checks this combination.
GET_TXEMPTY is a pure EP0 control transfer reading dev->tx_empty directly
(nt124_get_txempty_callback(), usb.c) -- it has nothing to do with the
bulk IN endpoint that RX backpressure actually congests, so in principle
it should be completely unaffected by RX-side stress. Worth confirming
empirically rather than assuming, especially since nt124 is full-duplex:
a real TX transfer and induced RX backpressure can genuinely be happening
at the same time on the same port, which is exactly how the board gets
used in practice.

Uses port 0 only, matching test_RS232_rx_backpressure.py's own stated
scope ("a targeted mechanism test, not a per-port survey").

Two scenarios, each run _REPEATS times:

1. No TX activity at all: tx_empty() must stay true and remain responsive
   throughout repeated induced RX backpressure/overrun cycles.
2. A real TX transfer and induced RX backpressure happening concurrently
   on the same port: tx_empty() must still correctly read false during the
   TX transfer and true once it finishes, unaffected by the simultaneous
   RX-side stress.

Requires TX/RX wired between port 0 and its peer, and the transceiver set
to a mode that reaches the external bus.

Run directly:
    python test_RS232_tx_empty_rx_backpressure_cycling.py
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


def _induce_overrun(port, peer, pattern, settle=0.5):
    """Write `pattern` fully, wait, let the peer echo it, wait again, THEN
    start reading -- deliberately never draining the IN endpoint while
    send_rx() is trying to deliver data, forcing an induced overrun. Same
    mechanism as test_RS232_rx_backpressure.py's
    _induce_backpressure_round_trip(), duplicated locally so this file
    stays runnable standalone.
    """
    peer.flush_input()
    port.write(pattern, timeout=2000)
    time.sleep(settle)
    peer_saw = peer.read_available()
    peer.write(peer_saw)
    time.sleep(settle)
    return port.read_payload(len(pattern), timeout=2000)


class TestTxEmptyRxBackpressureCycling(PeerTestCase):

    def test_tx_empty_responsive_during_induced_rx_backpressure_repeated(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        pattern = bytes(i & 0xFF for i in range(64))
        for cycle in range(_REPEATS):
            with self.subTest(cycle=cycle):
                self.assertTrue(
                    port.wait_tx_empty(timeout=1.0),
                    f"cycle {cycle}: not idle before this cycle started")
                _induce_overrun(port, peer, pattern)
                self.assertTrue(
                    port.tx_empty(),
                    f"cycle {cycle}: tx_empty() read false after induced "
                    f"RX backpressure with no TX activity at all -- it "
                    f"should be unaffected by RX-side stress")

    def test_tx_empty_tracks_correctly_during_simultaneous_rx_backpressure_repeated(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        port.set_line_coding(LineCoding(1200))
        peer.configure(1200)
        tx_pattern = bytes(i & 0xFF for i in range(64))  # ~530ms to drain at 1200 baud
        rx_pattern = bytes(i & 0xFF for i in range(64))
        try:
            for cycle in range(_REPEATS):
                with self.subTest(cycle=cycle):
                    self.assertTrue(
                        port.wait_tx_empty(timeout=1.0),
                        f"cycle {cycle}: not idle before this cycle started")
                    peer.flush_input()

                    write_error: list[Exception] = []

                    def writer() -> None:
                        try:
                            port.write(tx_pattern, timeout=2000)
                        except Exception as e:  # noqa: BLE001 -- surfaced below
                            write_error.append(e)

                    t = threading.Thread(target=writer, daemon=True)
                    t.start()
                    time.sleep(0.05)  # let TX settle into TX_WORKING
                    self.assertFalse(
                        port.tx_empty(),
                        f"cycle {cycle}: tx_empty() was true immediately "
                        f"after starting a TX transfer")

                    # Concurrently induce RX backpressure on the same port
                    # -- the peer sends while nt124 isn't drained, and the
                    # TX transfer above is also still actively in flight.
                    peer.write(rx_pattern)
                    time.sleep(0.5)  # long enough for TX to finish and RX to pile up undrained

                    self.assertTrue(
                        port.wait_tx_empty(timeout=2.0),
                        f"cycle {cycle}: tx_empty() never became true "
                        f"despite the TX transfer having had plenty of "
                        f"time, concurrent with induced RX backpressure")

                    t.join(timeout=3)
                    if write_error:
                        raise write_error[0]

                    # Drain whatever nt124 received, regardless of how
                    # much survived -- this test only cares about
                    # tx_empty()'s own bookkeeping, not RX data integrity
                    # (see test_RS232_rx_backpressure.py for that).
                    port.read_payload(len(rx_pattern), timeout=2000)
        finally:
            port.set_line_coding(LineCoding(115200))
            peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
