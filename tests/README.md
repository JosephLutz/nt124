# nt124 functional test suite

Hardware-in-the-loop tests for the nt124 firmware, over raw USB (bypassing
the in-kernel driver). Built on the standard-library `unittest` -- no pytest.

- **`functional/`** -- tests we trust: they pass reliably.
- **`stress/`** -- tests for firmware behavior we know is currently broken
  or unresolved (see `../SEND_RX_LOCKUP_NOTES.md`). Once a fix lands and a
  test there passes reliably, move it into `functional/`.

`test_RS232_loopback_bulk.py` and `test_RS232_concurrent_ports.py` moved
here from `stress/` once the SET_LINE_CODING idle-frame bug that made them
flaky on port 2 was fixed (see `../SEND_RX_LOCKUP_NOTES.md` and the fix in
uart.c) -- only `test_RS232_rx_backpressure.py` remains in `stress/` now,
covering a separate, still-open issue.

## Layout

```
tests/
  nt124usb/            the reusable board driver (see nt124usb/README.md)
  peer.py              pyserial wrapper for the external USB-to-serial
                        adapters wired to the physical UART ports
  transceiver.py        BusPirate-driven transceiver mode control -- see
                        "Transceiver mode control" below
  support.py           shared unittest base classes and scenario helpers
  bench.example.toml   copy to bench.toml and fill in your bench's wiring
  bench.toml           (not committed) your bench's actual config
  .vEnv/               (not committed) virtualenv -- see One-time setup
  functional/           tests we trust
  stress/               known-broken/unresolved firmware behavior
```

## One-time setup

```sh
cd tests
python3 -m venv .vEnv
.vEnv/bin/pip install -e nt124usb
.vEnv/bin/pip install -r requirements.txt   # needs system libusb-1.0 installed
cp bench.example.toml bench.toml            # then edit it -- see the comments inside
```

`.vEnv/` is this bench's convention for the virtualenv. The examples below
assume `.vEnv/bin/python3`; if you've activated the venv, plain `python`
works too.

Detaching/claiming a USB interface needs privilege: run as root (`sudo -E`,
see below), or grant your own user access with a udev rule so you never need
`sudo` at all.

### USB permissions without sudo (udev rule)

The nt124's USB vendor/product ID is `2aeb:007c` (`124` decimal = `0x7c`).
Create a rule file granting any member of the `plugdev` group read/write
access to it:

```sh
sudo tee /etc/udev/rules.d/99-nt124.rules >/dev/null <<'EOF'
# NovaTech nt124 (VID 2aeb, PID 124 = 0x7c) -- let plugdev claim/detach
# interfaces without root, for tests/nt124usb.
SUBSYSTEM=="usb", ATTR{idVendor}=="2aeb", ATTR{idProduct}=="007c", MODE="0660", GROUP="plugdev"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then make sure your user is in `plugdev` (create the group first if your
distro doesn't have it), and unplug/replug the board -- group membership
changes don't apply to a session you're already logged into:

```sh
sudo usermod -aG plugdev "$USER"
# log out and back in (or `newgrp plugdev` in the current shell) for the
# new group membership to take effect
```

If `plugdev` doesn't exist or your distro doesn't use it (e.g. some
minimal/server installs), either create it (`sudo groupadd plugdev`) or
swap `GROUP="plugdev"` above for `MODE="0666"` instead, which grants access
to every local user and needs no group at all -- simpler for a
single-user test bench, less isolated on a shared machine.

Verify it worked (no `sudo` needed) with the board plugged in:

```sh
python -c "import usb.core; print(usb.core.find(idVendor=0x2aeb, idProduct=124))"
```

If that raises a permissions error, double-check the rule matched
(`udevadm info -a -n /dev/bus/usb/<bus>/<dev>` from `lsusb`'s bus/device
numbers) and that you actually re-logged-in after the group change.

The 4 external USB-to-serial adapters are separate devices with their own
permissions -- on most distros `/dev/ttyUSB*` is owned by the `dialout`
group, so `sudo usermod -aG dialout "$USER"` (and re-login) covers those the
same way.

`bench.toml` is not committed (bench-specific hardware wiring, not portable)
-- see `.gitignore`.

## Transceiver mode control (BusPirate)

The bench's transceiver card is an **SP339E** (RS-232/RS-485/RS-422
transceiver with internal termination). Each port has 4 mode-control pins
(Mode0, Mode1, Slew, Term), driven not by the STM32 firmware but by a
16-bit **XRA1203** I2C GPIO expander on the bench (4 pins x 4 ports = 16),
reached over I2C through a **BusPirate** sitting at its text-mode I2C
prompt on its own serial port. `transceiver.py` automates exactly what
you'd type into that prompt by hand.

### Why this exists

Some tests need the transceiver actually driving the external bus
(`rs232`/`rs422`/`rs485`) so data really goes out over the wire to the peer
adapters; `test_self_loopback.py` instead needs the chip's own internal
`loopback` mode. The board's default/idle state on every power-up is
`loopback` -- the XRA1203 doesn't retain its I2C configuration across a
power cycle, so **the mode has to be reapplied after every board reset or
firmware flash**, not just once per bench session.

### bench.toml schema

```toml
[bus_pirate]
port = "/dev/serial/by-id/usb-...-buspirate"   # the BusPirate's own serial port
baud = 115200
setup = ["m", "4", "2", "P"]                    # mode menu -> I2C -> speed -> pull-ups

[bus_pirate.modes]
rs232    = ["[0x40 0x02 0x11]", "[0x40 0x03 0x11]", "[0x40 0x06 0x00]", "[0x40 0x07 0x00]"]
rs422    = ["[0x40 0x02 0x33]", "[0x40 0x03 0x33]", "[0x40 0x06 0x00]", "[0x40 0x07 0x00]"]
rs485    = ["[0x40 0x02 0x22]", "[0x40 0x03 0x22]", "[0x40 0x06 0x00]", "[0x40 0x07 0x00]"]
loopback = ["[0x40 0x02 0x00]", "[0x40 0x03 0x00]", "[0x40 0x06 0x00]", "[0x40 0x07 0x00]"]
```

Every value here is raw text replayed verbatim to the BusPirate --
`transceiver.py` has **no built-in knowledge of the XRA1203, the SP339E, or
what any register means**. If a future card uses a different I2C chip or
register layout, this is a `bench.toml` change, not a code change. Figure
out `setup` and each mode's command list by hand once, with a terminal
connected directly to the BusPirate (e.g. `screen <port> <baud>`): walk it
from its boot prompt to the I2C prompt for `setup`, then work out the
bracket I2C commands for each mode.

### The command format, decoded

`[0x40 0x02 0x11]` is BusPirate I2C syntax: `[` = start condition, then each
hex byte is written in turn (device address+W, register, value), `]` = stop
condition. `0x40` is the XRA1203's I2C address (write). Registers `0x02`/
`0x03` are its Output Control registers (OCR1/OCR2, covering pins P0-P7 and
P8-P15); `0x06`/`0x07` are its GPIO Configuration registers (GCR1/GCR2,
direction -- `0x00` sets all 16 pins as outputs). The same value is written
to both halves of a register pair because all 4 ports share the same mode
at once on this card.

Within one byte, each port gets a nibble: bit0=Mode0, bit1=Mode1, bit2=Slew,
bit3=Term. The Mode0/Mode1 combination matches the SP339E datasheet's own
mode-select truth table (MaxLinear SP339E datasheet, Figures 1-4, "Block
Diagram by Mode"):

| Mode0 | Mode1 | SP339E mode | nibble | example byte |
|---|---|---|---|---|
| 0 | 0 | Loopback | `0000` | `0x00` |
| 1 | 0 | RS-232 | `0001` | `0x11` |
| 0 | 1 | RS-485 Half Duplex | `0010` | `0x22` |
| 1 | 1 | RS-485/422 Full Duplex | `0011` | `0x33` |

### CLI

```sh
.vEnv/bin/python3 transceiver.py --list      # show configured mode names
.vEnv/bin/python3 transceiver.py rs232       # apply a mode, print each
                                              # command's raw BusPirate
                                              # response (watch for NACK)
```

Import it the same way from a script: `from transceiver import Transceivers`.

## Running tests

Every test except `test_self_loopback.py` needs the transceiver driving the
external bus (an external-bus mode, e.g. `rs232`) and the 4 peer adapters
wired per `bench.toml`; `test_self_loopback.py` needs the opposite --
`loopback` mode and no peer wiring at all. Since a single `unittest
discover` run can only have one transceiver mode active, the naming
convention keeps the two from getting mixed into the same run:
**`test_RS232_*.py`** is everything needing an external-bus mode;
`test_self_loopback.py` (deliberately not matching that pattern) is the
one exception.

```sh
cd tests
.vEnv/bin/python3 transceiver.py rs232       # once per board reset/flash
.vEnv/bin/python3 -m unittest discover -s functional -p "test_RS232_*.py" -v
```

Run one file directly (no arguments needed once `bench.toml` exists):

```sh
.vEnv/bin/python3 functional/test_RS232_control_plane.py
```

`stress/` runs the same way (`-s stress -p "test_RS232_*.py"`, since every
current stress test also needs an external-bus mode).
`stress/test_RS232_rx_backpressure.py` marks its data-loss test
`@unittest.expectedFailure` since it documents a known bug -- a normal run
shows it as an expected failure (`x`), not a red `FAIL`. **Unexpected
success** there means the underlying bug got fixed; remove the decorator
and consider moving that test into `functional/`.

If you skipped the udev rule above, prefix any of these with `sudo -E`
instead (the `-E` keeps root on your `PATH`/venv for the interface-claiming
calls).

## Adding a new test scenario

`functional/` if it's expected to always pass; `stress/` if it's chasing a
known-broken or unresolved firmware behavior (mark the specific method
`@unittest.expectedFailure` in that case). Name it `test_RS232_*.py` if it
needs an external-bus transceiver mode and peer wiring (true for nearly
everything); leave it as plain `test_*.py` only if, like
`test_self_loopback.py`, it specifically needs `loopback` mode instead --
see "Running tests" above for why the naming matters.

Subclass `support.Nt124TestCase` (board only) or `support.PeerTestCase`
(board + wired peers), copy the 3-line `sys.path` header from an existing
test, and end the file with:

```python
if __name__ == "__main__":
    unittest.main()
```

Use `self.each_port()` / `self.each_port_and_peer()` with `self.subTest(...)`
for independent per-port checks, or `self.board.ports()` / `self.peers`
together for scenarios needing all 4 at once.

`support.py` has reusable helpers -- `tx_one_way`, `rx_one_way`,
`write_while_reading`, `loopback_via_peer` -- read their docstrings before
reimplementing something similar. One thing worth knowing:
`loopback_via_peer` returns `(received, packets, echoed)`, and `echoed` (what
the peer itself received) is worth checking, not just `received` -- see the
comment in `functional/test_RS232_loopback_small.py` for why.
