"""Shared test infrastructure for the nt124 hardware-in-the-loop suite.

Built on the standard-library `unittest` (no pytest). New functional tests
should subclass `Nt124TestCase` (control-plane only, no peer wiring needed)
or `PeerTestCase` (adds the wired external adapters from bench.toml) rather
than reinventing setup/teardown -- that's the extension point for adding
more test scenarios.
"""
from __future__ import annotations

import pathlib
import threading
import tomllib
import unittest

from nt124usb import NUM_PORTS, Board, Packet, Port

from peer import Peer

BENCH_FILE = pathlib.Path(__file__).parent / "bench.toml"


def load_bench_wiring() -> dict[int, str]:
    """Read tests/bench.toml -> {port_index: peer_device_path}.

    Raises unittest.SkipTest if the file is missing or incomplete, so any
    test that needs it skips cleanly instead of failing with a KeyError.
    """
    if not BENCH_FILE.exists():
        raise unittest.SkipTest(
            f"{BENCH_FILE.name} not found -- copy bench.example.toml to "
            f"bench.toml and fill in your bench's serial device paths")
    data = tomllib.loads(BENCH_FILE.read_text())
    wiring: dict[int, str] = {}
    for i in range(NUM_PORTS):
        entry = data.get("port", {}).get(str(i))
        if not entry or "peer" not in entry:
            raise unittest.SkipTest(f"bench.toml is missing [port.{i}].peer")
        wiring[i] = entry["peer"]
    return wiring


class Nt124TestCase(unittest.TestCase):
    """Base for tests that only need the nt124 board itself -- control-plane
    tests, or anything that doesn't touch the external adapters."""

    board: Board

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.board = Board()
        except RuntimeError as e:
            raise unittest.SkipTest(str(e))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.board.close()

    def each_port(self):
        """Yield (index, port) for all 4 ports. Pair with subTest so each
        port's result is reported independently:

            for index, port in self.each_port():
                with self.subTest(port=index):
                    ...
        """
        for i in range(NUM_PORTS):
            yield i, self.board.port(i)


class PeerTestCase(Nt124TestCase):
    """Base for tests that also need the external USB-to-serial adapters
    wired per bench.toml -- data-plane / loopback tests."""

    peers: dict[int, Peer]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        wiring = load_bench_wiring()
        cls.peers = {i: Peer(path) for i, path in wiring.items()}
        for p in cls.peers.values():
            p.open()

    @classmethod
    def tearDownClass(cls) -> None:
        for p in cls.peers.values():
            p.close()
        super().tearDownClass()

    def each_port_and_peer(self):
        """Yield (index, port, peer) for all 4 ports."""
        for i in range(NUM_PORTS):
            yield i, self.board.port(i), self.peers[i]


def write_while_reading(port: Port, pattern: bytes, timeout: int = 2000,
                         chunk: int = 2048) -> tuple[bytes, list[Packet]]:
    """Write `pattern` out `port` in chunks on a background thread while
    reading the response back on `port` in the foreground.

    The nt124 firmware has almost no RX buffering ahead of the USB IN
    endpoint (a couple of small double-buffers) -- if nothing drains that
    endpoint while a big blocking `port.write()` call is still running, the
    pipe backs up almost immediately and the rest of the data has nowhere
    to go. Writing and reading concurrently avoids mistaking that *host-side*
    backpressure for a device-side drop. Chunking the write also avoids a
    single `write()` call timing out on a payload too large to drain, as a
    whole, within `timeout`.

    Returns (received, packets); see `loopback_via_peer` for how to read them.
    """
    write_error: list[Exception] = []

    def writer() -> None:
        try:
            for i in range(0, len(pattern), chunk):
                port.write(pattern[i:i + chunk], timeout=timeout)
        except Exception as e:  # surfaced below, not swallowed
            write_error.append(e)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        return port.read_payload(len(pattern), timeout=timeout)
    finally:
        t.join(timeout=max(timeout / 1000.0, 1.0) * 2)
        if write_error:
            raise write_error[0]


def read_while_peer_writes(port: Port, peer: Peer, pattern: bytes,
                            timeout: int = 2000
                            ) -> tuple[bytes, list[Packet]]:
    """The peer writes `pattern` on a background thread while nt124 reads it
    back on `port` in the foreground -- the mirror image of
    `write_while_reading`, for the RX direction.

    `peer.write()` blocks for roughly the whole real transmission time at
    the configured baud. nt124's RX side has almost no buffering ahead of
    the USB IN endpoint (only 2 rx_buffer slots, no RTS back-pressure), so
    if nothing drains that endpoint while the peer is still blocked inside
    that single write() call, most of a large transfer is silently
    overwritten before the host ever starts reading -- not a device bug,
    a test-sequencing one. Use `rx_one_way` instead for small (at most
    RX_BUFFER_SIZE) transfers, where this doesn't matter.
    """
    write_error: list[Exception] = []

    def writer() -> None:
        try:
            peer.write(pattern)
        except Exception as e:  # surfaced below, not swallowed
            write_error.append(e)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        return port.read_payload(len(pattern), timeout=timeout)
    finally:
        t.join(timeout=max(timeout / 1000.0, 1.0) * 2)
        if write_error:
            raise write_error[0]


def loopback_via_peer(port: Port, peer: Peer, pattern: bytes,
                       timeout: int = 2000
                       ) -> tuple[bytes, list[Packet], bytes]:
    """Write `pattern` out `port`; a background thread echoes everything the
    peer receives straight back; read the echo back on `port` -- all while
    also writing and reading `port` itself concurrently (see
    `write_while_reading`).

    Exercises the full round trip: nt124 TX -> wire -> peer RX -> peer TX ->
    wire -> nt124 RX. Requires TX/RX (and ground) wired between the two.

    Returns (received, packets, echoed). `received`/`packets` are what came
    back on `port`, same as before -- but a transceiver sitting in an
    internal loopback mode can hand that back correctly without any data
    ever reaching the peer at all, which would silently pass a test that
    only checks `received`. Callers MUST also assert on `echoed` -- what the
    peer itself actually received and relayed -- to confirm this was a real
    external round trip and not an on-board loopback in disguise: short or
    empty `echoed` means the data never left the card.
    """
    echoed = bytearray()
    stop = threading.Event()

    def echo_loop() -> None:
        while not stop.is_set() and len(echoed) < len(pattern):
            chunk = peer.read_available()
            if chunk:
                peer.write(chunk)
                echoed.extend(chunk)

    t = threading.Thread(target=echo_loop, daemon=True)
    t.start()
    try:
        received, packets = write_while_reading(port, pattern, timeout=timeout)
    finally:
        stop.set()
        t.join(timeout=1)
    return received, packets, bytes(echoed)


def tx_one_way(port: Port, peer: Peer, data: bytes) -> bytes:
    """nt124 writes `data` out `port`; return what the peer actually
    received. One-way only -- no echo, no round trip. Isolates the TX path
    (bulk OUT -> usbuart_usb_out_cb -> ping-pong buffers -> DMA -> UART TX ->
    transceiver) from RX/send_rx() entirely.
    """
    peer.flush_input()
    port.write(data)
    return peer.read_until_quiet()


def rx_one_way(port: Port, peer: Peer, data: bytes,
                timeout: int = 2000) -> tuple[bytes, list[Packet]]:
    """The peer writes `data`; nt124 reads it back. One-way only -- isolates
    the RX path (UART RX -> DMA/idle-timer -> send_rx -> bulk IN) from TX.
    """
    peer.write(data)
    return port.read_payload(len(data), timeout=timeout)
