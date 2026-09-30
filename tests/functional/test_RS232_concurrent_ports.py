"""All 4 ports driven simultaneously, at volume (8192 bytes/port) -- checks
the shared USB poll loop (usb_task -> usbd_poll) holds up under concurrent
load, not just one port at a time. Production always runs all 4 ports at
once; testing them only sequentially would miss contention on that shared
poll loop.

Combines bulk volume (see test_RS232_loopback_bulk.py) with 4-way
concurrency. Was in tests/stress/ while the SET_LINE_CODING idle-frame bug
(see SEND_RX_LOCKUP_NOTES.md and the fix in uart.c) made it flaky on port 2;
moved here once that fix made it reliably pass. A failure here on top of
test_RS232_loopback_bulk.py passing narrows the problem to cross-port
contention specifically.

Requires all 4 ports wired to their configured peers in bench.toml.

Run directly:
    python test_RS232_concurrent_ports.py
"""
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402


def _check_one(index, port, peer, size: int) -> str | None:
    port.set_line_coding(LineCoding(115200))
    peer.configure(115200)
    pattern = bytes(i & 0xFF for i in range(size))
    received, packets, echoed = loopback_via_peer(port, peer, pattern, timeout=4000)
    # Confirm the data actually reached the peer over the real wire -- see
    # the comment in test_loopback.py: an internal transceiver loopback can
    # otherwise hand `received` back correctly with the peer seeing nothing.
    if echoed != pattern:
        return (f"port {index}: FAIL peer only saw {len(echoed)}/{size} bytes -- "
                f"data isn't reaching the external wire")
    if received != pattern:
        return f"port {index}: FAIL got {len(received)}/{size} bytes back"
    if any(p.line_error for p in packets):
        return f"port {index}: FAIL firmware flagged line errors"
    return None


class TestConcurrentPorts(PeerTestCase):

    def test_all_ports_simultaneous_loopback(self) -> None:
        size = 8192
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_check_one, i, port, peer, size)
                       for i, port, peer in self.each_port_and_peer()]
            results = [f.result() for f in as_completed(futures)]
        failures = [r for r in results if r is not None]
        self.assertFalse(failures, "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
