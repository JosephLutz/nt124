"""BusPirate-driven control of the nt124 bench's transceiver mode.

The bench's transceiver card (currently an XRA1203 I2C GPIO expander) is
configured by writing mode/slew/termination bits over I2C, reached through
a BusPirate sitting at its text-mode I2C prompt on its own serial port.

Everything chip- and command-specific lives in bench.toml, not here: this
module only knows how to open the BusPirate's serial port, replay a list of
raw lines, and flag a response containing "NACK". If a future card uses a
different I2C chip or register layout, update bench.toml -- this module
doesn't need to change.

Figure out `setup` and each mode's command list by hand once, with a
terminal program connected directly to the BusPirate, e.g.:

    screen /dev/serial/by-id/usb-...-buspirate 115200

Walk it from its boot/reset prompt to the I2C mode prompt, noting exactly
what you type for `setup`; then note the bracket I2C commands for each
mode. Everything this module sends is exactly what you'd type there
yourself -- that's deliberate, so the bench.toml config doubles as a record
of how to drive the BusPirate by hand.

CLI:
    python transceiver.py rs232
    python transceiver.py --list
"""
from __future__ import annotations

import time

import serial


class TransceiverError(RuntimeError):
    """A BusPirate command sequence didn't do what it was supposed to
    (e.g. the response contained a NACK), or an unknown mode was requested."""


class Transceivers:
    """Bench-wide transceiver mode control via a BusPirate."""

    def __init__(self, port_path: str, baud: int = 115200,
                 setup: list[str] | None = None,
                 modes: dict[str, list[str]] | None = None,
                 settle: float = 0.3):
        self.port_path = port_path
        self._baud = baud
        self._setup = setup or []
        self._modes = modes or {}
        self._settle = settle
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        self._ser = serial.Serial(self.port_path, baudrate=self._baud, timeout=0.2)
        for line in self._setup:
            self._send(line)

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self) -> "Transceivers":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def available_modes(self) -> list[str]:
        return sorted(self._modes)

    def set_mode(self, name: str) -> list[str]:
        """Replay bench.toml's command list for mode `name`.

        Returns the raw response text for each command (useful for logging
        or manual troubleshooting). Raises TransceiverError on an unknown
        mode name or a response containing "NACK".
        """
        try:
            commands = self._modes[name]
        except KeyError:
            raise TransceiverError(
                f"unknown transceiver mode {name!r}; "
                f"available: {self.available_modes}") from None

        responses = []
        for line in commands:
            response = self._send(line)
            responses.append(response)
            if "NACK" in response.upper():
                raise TransceiverError(
                    f"mode {name!r}: {line!r} got a NACK: {response!r}")
        return responses

    def _send(self, line: str) -> str:
        assert self._ser is not None, "Transceivers.open() not called"
        self._ser.reset_input_buffer()
        self._ser.write((line + "\n").encode())
        time.sleep(self._settle)
        return self._ser.read(self._ser.in_waiting or 1).decode(errors="replace")


def _load_from_bench_toml():
    import pathlib
    import tomllib

    bench_file = pathlib.Path(__file__).parent / "bench.toml"
    data = tomllib.loads(bench_file.read_text())
    bp = data.get("bus_pirate")
    if not bp or "port" not in bp:
        raise TransceiverError(
            f"{bench_file.name} has no [bus_pirate] section with a `port` -- "
            f"see bench.example.toml")
    return Transceivers(
        port_path=bp["port"],
        baud=bp.get("baud", 115200),
        setup=bp.get("setup"),
        modes=bp.get("modes"),
    )


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", help="mode name from bench.toml's [bus_pirate.modes]")
    ap.add_argument("--list", action="store_true", help="list available modes and exit")
    args = ap.parse_args()

    try:
        tc = _load_from_bench_toml()
    except (TransceiverError, FileNotFoundError) as e:
        print(f"RESULT: CONFIG-FAIL -- {e}")
        return 2

    with tc:
        if args.list or not args.mode:
            print("available modes:", ", ".join(tc.available_modes) or "(none configured)")
            return 0 if args.list else 2

        try:
            responses = tc.set_mode(args.mode)
        except TransceiverError as e:
            print(f"RESULT: FAIL -- {e}")
            return 1

    for line, response in zip(tc._modes[args.mode], responses):
        print(f"{line} -> {response.strip()!r}")
    print(f"RESULT: OK -- mode {args.mode!r} applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
