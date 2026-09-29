# nt124usb

Userspace (pyusb/libusb) access to the NovaTech **nt124** board, bypassing the
in-kernel driver. Two layers:

- **`nt124usb.low`** — `RawPort`: bare libusb. Claim/release one interface,
  raw control transfers, raw bulk read/write. No parsing, no policy. Only the
  claimed interface is detached from the kernel driver; the other 3 ports
  keep working normally.
- **`nt124usb.board`** — `Board` / `Port`: the layer everything else should
  actually use. `LineCoding` / `Packet` dataclasses, status-header decoding,
  `wait_tx_empty()`, context managers.

This package only knows how to talk to the board — it has no test-framework
dependency and no opinion about test scenarios. It's meant to be reusable
from the functional test suite in `tests/`, ad-hoc bench scripts, or anything
else that needs to drive an nt124.

## Install

```sh
pip install -e tests/nt124usb
```

(Editable install: `import nt124usb` then works from anywhere, not just
inside `tests/`.)

## Port mapping (non-obvious)

USB port order is not physical-UART order — see `uart_lookup[]` in
`src/project/usb/usb.c`. `PortInfo.physical_uart` in `protocol.py` documents
it; nothing in this package needs you to know it.

| port index | wIndex | EP out/in | physical UART |
|---|---|---|---|
| 0 | 0 | 0x01 / 0x81 | UART1 |
| 1 | 1 | 0x03 / 0x83 | UART4 |
| 2 | 2 | 0x05 / 0x85 | UART3 |
| 3 | 3 | 0x07 / 0x87 | UART2 |

## Example

```python
from nt124usb import Board, LineCoding

with Board() as board:
    port = board.port(1)
    port.set_line_coding(LineCoding(115200))
    port.write(b"hello")
    payload, packets = port.read_payload(5, timeout=1000)
```
