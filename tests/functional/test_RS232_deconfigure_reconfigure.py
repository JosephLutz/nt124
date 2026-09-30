"""Regression test for send_rx()'s unconfigured-device fix (uart.c):
data that arrives on the wire while the USB device is deconfigured
(SET_CONFIGURATION(0)) used to be silently discarded -- send_rx() only
attempted delivery `if (nt124_get_config())`, but `serviced` stayed at its
initial `true` when that was false, so the unconditional cleanup at the end
still cleared RX_NEED_SERVICE and every error flag as if the data had been
delivered. It's now treated the same as a failed usbd_ep_write_packet():
the data stays pending, waiting for the next real delivery attempt.

That means it doesn't just vanish -- but nothing proactively flushes it on
reconfigure either, so if a second burst arrives before the host resumes
reading, process_rx()'s existing overwrite-detection (the same mechanism
behind the accepted RX-backpressure behavior, see
test_RS232_rx_backpressure.py) will flag it as an overrun when the second
burst's buffer overwrites the still-pending first one. That flagged
overrun -- instead of a second burst arriving with no trace of the first
one at all -- is exactly what distinguishes the fixed behavior from the
original bug, and is what this test checks for.

Calling usb.core.Device.set_configuration() resets every endpoint on all 4
ports at once (see RawPort.claim()'s own comment), so this test must
release every claimed interface first and reclaim them afterward --
Board.release_all()/reclaim_all() exist specifically for this.

Requires TX/RX wired between port 0 and its peer, and the transceiver set
to a mode that reaches the external bus.

Run directly:
    python test_RS232_deconfigure_reconfigure.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nt124usb import LineCoding  # noqa: E402
from support import PeerTestCase, tx_one_way  # noqa: E402


class TestDeconfigureReconfigure(PeerTestCase):

    def test_pending_rx_survives_deconfigure_as_flagged_overrun(self) -> None:
        port, peer = self.board.port(0), self.peers[0]
        device = self.board.device
        config_value = device.get_active_configuration().bConfigurationValue

        port.set_line_coding(LineCoding(115200))
        peer.configure(115200)
        peer.flush_input()

        first = bytes(range(10))
        second = bytes(range(10, 20))

        self.board.release_all()
        try:
            device.set_configuration(0)
            peer.write(first)
            time.sleep(0.3)  # let the idle timer flush it while unconfigured

            device.set_configuration(config_value)
        finally:
            self.board.reclaim_all()

        # A second burst overwrites the still-pending first one -- this is
        # what should surface the earlier data as a flagged overrun rather
        # than it having already vanished with no trace.
        peer.write(second)
        received, packets = port.read_payload(len(second), timeout=2000)

        self.assertTrue(any(p.line_error for p in packets),
                         f"expected the first burst (sent while unconfigured) "
                         f"to surface as an overrun once the second burst "
                         f"overwrote it -- no packet flagged a line error: "
                         f"{[p.describe() for p in packets]}")

        # Port must still work normally afterward.
        recovery_pattern = bytes(range(5))
        recovered = tx_one_way(port, peer, recovery_pattern)
        self.assertEqual(recovered, recovery_pattern,
                          "port did not recover cleanly after the "
                          "deconfigure/reconfigure cycle")


if __name__ == "__main__":
    unittest.main()
