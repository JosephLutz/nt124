"""Variant of test_RS232_concurrent_ports.py with each of the 4 ports
running a DIFFERENT baud rate simultaneously, instead of all 4 at the same
115200. set_uart_parameters() (uart.c) indexes per-port baud_index into
shared, read-only tables (tim_table[], ctrl_delay[], tx_empty_delay[]) and
drives a per-port timer (TIM2..TIM5) off it -- every other concurrency test
in this suite runs all 4 ports at the same baud, which could never catch a
mistake that only shows up when different ports are simultaneously
indexing different rows of those tables (e.g. a stale/shared index, or a
timer misconfigured for the wrong port).

Requires all 4 ports wired to their configured peers in bench.toml.

Run directly:
    python test_RS232_concurrent_ports_mixed_baud.py
"""
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, loopback_via_peer  # noqa: E402

# One port at each extreme of the supported range, two in between -- chosen
# so no two ports share a baud_index row in uart.c's delay tables. Payload
# size is scaled down for the slower bauds -- a fixed size across all 4
# would either make the fast ports pointlessly trivial or (as first written,
# before this was caught by actually running it) blow the shared timeout at
# 1200 baud, where 2048 bytes alone takes ~17s to drain one-way.
_CASES = {0: (1200, 256), 1: (19200, 1024), 2: (115200, 4096), 3: (230400, 4096)}
_TIMEOUT = 10000


def _check_one(index, port, peer, baud: int, size: int) -> str | None:
    port.set_line_coding(LineCoding(baud))
    peer.configure(baud)
    pattern = bytes(i & 0xFF for i in range(size))
    received, packets, echoed = loopback_via_peer(port, peer, pattern, timeout=_TIMEOUT)
    if echoed != pattern:
        return (f"port {index} @ {baud}: FAIL peer only saw "
                f"{len(echoed)}/{size} bytes")
    if received != pattern:
        return f"port {index} @ {baud}: FAIL got {len(received)}/{size} bytes back"
    if any(p.line_error for p in packets):
        return f"port {index} @ {baud}: FAIL firmware flagged line errors"
    return None


class TestConcurrentPortsMixedBaud(PeerTestCase):

    def test_all_ports_simultaneous_loopback_different_bauds(self) -> None:
        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [ex.submit(_check_one, i, port, peer, *_CASES[i])
                           for i, port, peer in self.each_port_and_peer()]
                results = [f.result() for f in as_completed(futures)]
            failures = [r for r in results if r is not None]
            self.assertFalse(failures, "\n" + "\n".join(failures))
        finally:
            for index, port, peer in self.each_port_and_peer():
                port.set_line_coding(LineCoding(115200))
                peer.configure(115200)


if __name__ == "__main__":
    unittest.main()
