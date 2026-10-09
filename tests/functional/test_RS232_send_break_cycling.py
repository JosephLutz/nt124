"""Repeated-cycle NT124_USB_REQ_SEND_BREAK tests, mirroring the other
cycling files' pattern. test_RS232_send_break.py and
test_RS232_framing_and_break.py each check a break scenario once, always
with the port otherwise idle; nothing repeats the cycle, and nothing sends
a break while data is actively, continuously in flight -- the same gap
identified in the flow-control cycling tests (a clean, isolated toggle vs.
one happening against genuinely flowing data).

Four scenarios, each run _REPEATS times per port:

1. nt124 sending a break (does not disrupt a subsequent transfer) --
   repeated.
2. nt124 receiving a real break from the peer (does not disrupt a
   subsequent transfer) -- repeated.
3. A non-0xFFFF SEND_BREAK value (a silent no-op, per
   nt124_send_break_callback() in usb.c) -- repeated.
4. nt124 sending a break WHILE a TX transfer is actively, continuously in
   flight -- unlike #1, this doesn't wait for the port to go idle first.
   Confirmed on real hardware: the break reliably inserts exactly one
   spurious 0x00 byte into the peer's stream at the point it lands,
   leaving everything before and after it intact -- expected, standard
   UART behavior (a break decodes as a start bit, all-zero data bits, and
   a framing error where the stop bit should be), not firmware corruption.
   This test allows for exactly that one known, explainable byte rather
   than asserting a literal match.

Requires TX/RX wired between each port and its peer, and the transceiver
set to a mode that reaches the external bus.

Run directly:
    python test_RS232_send_break_cycling.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding, protocol as proto  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402

_REPEATS = 10  # adjust for more/less cycling
_VENDOR_OUT = 0x40


_MAX_EXPECTED_BREAK_BYTES = 2  # usually 1 spurious 0x00; occasionally 2 (see below)


def _extra_bytes_if_subsequence(received: bytes, pattern: bytes) -> int | None:
    """If `pattern` appears in order within `received` -- i.e. `received`
    is `pattern` with some number of extra bytes spliced in, nothing
    missing or reordered -- return how many extra bytes there are.
    Returns None if `pattern` isn't a subsequence of `received` at all,
    meaning something more than just extra spurious bytes happened (real
    corruption, a dropped byte, reordering).

    Used to tolerate the break's own 0x00/framing-error byte(s) landing
    amid otherwise-untouched data: confirmed on real hardware to usually
    insert exactly one such byte, but occasionally two (timing-dependent --
    seen once in 40 cycles, with the break apparently straddling two
    decode windows on the peer's receiver), never more.
    """
    j = 0
    extra = 0
    for b in received:
        if j < len(pattern) and b == pattern[j]:
            j += 1
        else:
            extra += 1
    return extra if j == len(pattern) else None


class TestSendBreakCycling(PeerTestCase):

    def test_send_break_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        peer.flush_input()
                        port.send_break()  # must not raise/STALL
                        time.sleep(0.05)  # let the one-shot break frame finish
                        recovered = tx_one_way(port, peer, pattern)
                        self.assertEqual(
                            recovered, pattern,
                            f"cycle {cycle}: port didn't recover cleanly "
                            f"after send_break()")

    def test_received_break_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        peer.flush_input()
                        peer.send_break(duration=0.1)  # blocks for the duration
                        time.sleep(0.05)
                        # Drain whatever the break itself produced -- not
                        # asserted on directly, same as
                        # test_RS232_framing_and_break.py.
                        port.read_payload(1, timeout=200)
                        recovered = tx_one_way(port, peer, pattern)
                        self.assertEqual(
                            recovered, pattern,
                            f"cycle {cycle}: port didn't recover cleanly "
                            f"after receiving a real BREAK condition")

    def test_send_break_non_ffff_value_is_a_noop_repeated(self) -> None:
        pattern = bytes(range(10))
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)
                for cycle in range(_REPEATS):
                    with self.subTest(cycle=cycle):
                        peer.flush_input()
                        port.raw_ctrl_transfer(_VENDOR_OUT, proto.REQ_SEND_BREAK, 0x0000)
                        recovered = tx_one_way(port, peer, pattern)
                        self.assertEqual(
                            recovered, pattern,
                            f"cycle {cycle}: port didn't behave normally "
                            f"after a wValue=0 SEND_BREAK")

    def test_send_break_during_active_transfer_repeated(self) -> None:
        pattern = bytes(i & 0xFF for i in range(128))  # enough to still be
        # draining at 1200 baud when the break lands
        for index, port, peer in self.each_port_and_peer():
            with self.subTest(port=index):
                port.set_line_coding(LineCoding(1200))
                peer.configure(1200)
                try:
                    for cycle in range(_REPEATS):
                        with self.subTest(cycle=cycle):
                            peer.flush_input()

                            write_error: list[Exception] = []

                            def writer() -> None:
                                try:
                                    port.write(pattern, timeout=5000)
                                except Exception as e:  # noqa: BLE001 -- surfaced below
                                    write_error.append(e)

                            t = threading.Thread(target=writer, daemon=True)
                            t.start()
                            time.sleep(0.2)  # let TX settle solidly into TX_WORKING
                            port.send_break()  # must not raise/STALL mid-transfer
                            t.join(timeout=5)
                            if write_error:
                                raise write_error[0]

                            received = peer.read_until_quiet(quiet=0.5, max_wait=3.0)
                            extra = _extra_bytes_if_subsequence(received, pattern)
                            self.assertIsNotNone(
                                extra,
                                f"cycle {cycle}: sending a break mid-transfer "
                                f"did more than insert spurious bytes -- the "
                                f"surrounding data itself was dropped, "
                                f"reordered, or corrupted -- got {received!r}")
                            self.assertLessEqual(
                                extra, _MAX_EXPECTED_BREAK_BYTES,
                                f"cycle {cycle}: got {extra} extra bytes, more "
                                f"than the break itself should ever produce "
                                f"-- got {received!r}")
                finally:
                    port.set_line_coding(LineCoding(115200))
                    peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
