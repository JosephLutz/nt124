"""On-board self-loopback: nt124 writes a small pattern out a port and reads
it back on that SAME port, with no external peer adapter involved at all.
Baseline check; volume testing isn't in scope here -- see tests/stress/.

This only produces useful data while the port's transceiver is set to the
"loopback" mode in bench.toml's [bus_pirate.modes] (TX shorted back to RX
inside the chip) -- the board's default/idle state until transceiver.py
sets it to rs232/rs422/rs485 for real external-wire testing.

Use this to validate the firmware/USB data path (bulk OUT -> UART TX ->
DMA -> transceiver -> UART RX -> bulk IN, and the packet/status-header
framing) independently of external wiring or peer adapters being ready.
Unlike the peer-based tests, it needs no bench.toml and no external
adapters at all.

Once the transceivers are set to rs232/rs422/rs485, this test is *expected*
to start failing -- there's no longer anything shorting TX back to RX
internally, so nothing comes back on the same port. That's not a
regression; at that point the peer-based tests are the relevant ones.

Run directly:
    python test_self_loopback.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import Nt124TestCase, write_while_reading  # noqa: E402


class TestSelfLoopback(Nt124TestCase):

    def _check(self, index: int, port, size: int) -> None:
        port.set_line_coding(LineCoding(115200))
        pattern = bytes(i & 0xFF for i in range(size))

        received, packets = write_while_reading(port, pattern, timeout=2000)

        self.assertEqual(
            len(received), size,
            f"port {index}: got {len(received)}/{size} bytes back on the "
            f"same port -- if the transceiver was just taken out of "
            f"loopback mode, this is expected (see the module docstring)")
        self.assertEqual(received, pattern, f"port {index}: corruption")
        bad = [p for p in packets if p.line_error]
        self.assertFalse(bad, f"port {index}: firmware flagged line errors: "
                               f"{[p.describe() for p in bad]}")

    def test_self_loopback_pattern_intact(self) -> None:
        # Small sizes only: one under RX_BUFFER_SIZE (idle-timer flush) and
        # one exactly at it (DMA buffer-full flush). Volume/backpressure
        # testing is out of scope here -- see tests/stress/.
        for size in (16, 29):
            for index, port in self.each_port():
                with self.subTest(size=size, port=index):
                    self._check(index, port, size)


if __name__ == "__main__":
    unittest.main()
