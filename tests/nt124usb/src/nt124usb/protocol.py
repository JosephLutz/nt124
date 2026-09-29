"""Wire-format facts for the NovaTech nt124 USB-to-serial board.

Single source of truth for anything that must stay in sync with the
firmware. If the firmware's port<->endpoint mapping, request codes, or
status bits change, update it here -- nowhere else in this package should
hard-code these values.

Mirrors:
    src/project/usb/usb.h   (ACMn_* macros, NT124_USB_REQ_* request codes)
    src/project/usb/usb.c   (VID/PID, endpoint descriptors, uart_lookup[])
    src/project/uart/uart.h (ACM_CTRL_* status bits)
"""
from __future__ import annotations

from dataclasses import dataclass

VID = 0x2AEB
PID = 124

NUM_PORTS = 4  # fixed by the hardware -- this board will only ever have 4

# -- control requests ---------------------------------------------------
# SET_LINE_CODING / SET_CONTROL_LINE_STATE are standard USB CDC requests,
# reused as-is by the firmware. SEND_BREAK / SET_FLOW_CONTROL / GET_TXEMPTY
# are nt124-specific (usb/usb.h).
REQ_SET_LINE_CODING = 0x20
REQ_SET_CONTROL_LINE_STATE = 0x22
REQ_SEND_BREAK = 0x23           # NT124_USB_REQ_SEND_BREAK
REQ_SET_FLOW_CONTROL = 0x90     # NT124_USB_REQ_SET_FLOW_CONTROL
REQ_GET_TXEMPTY = 0x91          # NT124_USB_REQ_GET_TXEMPTY

# SET_CONTROL_LINE_STATE wValue bits
CTRL_DTR = 0x01
CTRL_RTS = 0x02

# Status-header bits (first 2 bytes of every RX/IN packet), from
# uart_get_control_line_state() and the ACM_CTRL_* defines in uart.h.
ST_DCD = 0x0001
ST_DSR = 0x0002
ST_BRK = 0x0004
ST_RI = 0x0008
ST_FRAMING = 0x0010
ST_PARITY = 0x0020
ST_OVERRUN = 0x0040
ST_TXEMPTY = 0x0080
ST_CTS = 0x0100

ST_LINE_ERRORS = ST_FRAMING | ST_PARITY | ST_OVERRUN | ST_BRK

CDCACM_PACKET_SIZE = 32
RX_PAYLOAD_MAX = CDCACM_PACKET_SIZE - 3  # 29: RX_BUFFER_SIZE in the firmware


@dataclass(frozen=True)
class PortInfo:
    index: int          # 0..3: the ACM index == USB interface number == wIndex
    ep_out: int
    ep_in: int
    physical_uart: str  # informational only -- matches the uarts[] comment in uart.c


# Port order is NOT the same as physical UART order (see uart_lookup[] in
# usb.c and the ACMn_UART_INDEX macros in usb.h) -- ports 2 and 4 are
# swapped relative to their physical UART. That mapping only matters inside
# the firmware; from here it's just documentation on PortInfo.physical_uart.
PORTS: tuple[PortInfo, ...] = (
    PortInfo(0, ep_out=0x01, ep_in=0x81, physical_uart="UART1"),
    PortInfo(1, ep_out=0x03, ep_in=0x83, physical_uart="UART4"),
    PortInfo(2, ep_out=0x05, ep_in=0x85, physical_uart="UART3"),
    PortInfo(3, ep_out=0x07, ep_in=0x87, physical_uart="UART2"),
)

assert len(PORTS) == NUM_PORTS
assert all(p.index == i for i, p in enumerate(PORTS))
