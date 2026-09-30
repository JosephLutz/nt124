"""Malformed/out-of-spec control transfers that should STALL rather than
being accepted or silently misinterpreted.

get_uart_from_index() (usb.c) bounds-checks wIndex against uart_lookup[]'s
4 entries before every one of the 5 vendor control callbacks touches
uarts[] -- an out-of-range wIndex returns USBD_REQ_NOTSUPP, which the
underlying libopencm3 core turns into a STALL on endpoint 0. Similarly,
nt124_set_line_coding_callback() explicitly rejects a data stage shorter
than the 7-byte usb_cdc_line_coding struct, and any control transfer whose
direction/type bits don't match one of the 5 registered vendor callbacks
falls through to libopencm3's standard-request handler, which STALLs it
(vendor-type requests never satisfy that handler's own type check).
SET_INTERFACE(altsetting > 0) stalls too, for an unrelated reason: none of
the 4 interface descriptors populate cur_altsetting, so libopencm3 rejects
anything but altsetting 0.

None of this needs peer wiring -- it's purely control-plane behavior on
port 0 (or all 4 for the wIndex sweep, since the bounds check is identical
per-request but not otherwise port-dependent).

Run directly:
    python test_RS232_control_transfer_edge_cases.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usb.core  # noqa: E402

from nt124usb import LineCoding, protocol as proto  # noqa: E402
from support import Nt124TestCase  # noqa: E402

_VENDOR_OUT = 0x40
_VENDOR_IN = 0xC0
_STANDARD_OUT_INTERFACE = 0x01
_REQ_SET_INTERFACE = 0x0B


class TestControlTransferEdgeCases(Nt124TestCase):

    def test_out_of_range_windex_stalls(self) -> None:
        requests = [
            (proto.REQ_SET_CONTROL_LINE_STATE, _VENDOR_OUT, 0, None),
            (proto.REQ_SET_LINE_CODING, _VENDOR_OUT, 0, LineCoding(115200).to_bytes()),
            (proto.REQ_SET_FLOW_CONTROL, _VENDOR_OUT, 0, None),
            (proto.REQ_SEND_BREAK, _VENDOR_OUT, 0, None),
            (proto.REQ_GET_TXEMPTY, _VENDOR_IN, 0, 1),
        ]
        port = self.board.port(0)
        for bad_index in (4, 0xFFFF):
            for bRequest, bm_request_type, wValue, data_or_len in requests:
                with self.subTest(bRequest=hex(bRequest), wIndex=bad_index):
                    with self.assertRaises(usb.core.USBError):
                        port.raw_ctrl_transfer(bm_request_type, bRequest, wValue,
                                                bad_index, data_or_len)

    def test_set_line_coding_short_wlength_stalls(self) -> None:
        port = self.board.port(0)
        with self.assertRaises(usb.core.USBError):
            port.raw_ctrl_transfer(_VENDOR_OUT, proto.REQ_SET_LINE_CODING, 0,
                                    None, bytes(6))
        # The real 7-byte struct must still be accepted right afterward --
        # confirms the short transfer didn't wedge anything.
        port.set_line_coding(LineCoding(115200))

    def test_wrong_direction_stalls(self) -> None:
        port = self.board.port(0)
        # SET_LINE_CODING's bRequest is only registered for the OUT
        # direction -- the same bRequest sent IN shouldn't match any
        # vendor callback and should fall through to a STALL.
        with self.assertRaises(usb.core.USBError):
            port.raw_ctrl_transfer(_VENDOR_IN, proto.REQ_SET_LINE_CODING, 0, None, 7)
        # GET_TXEMPTY's bRequest is only registered for the IN direction.
        with self.assertRaises(usb.core.USBError):
            port.raw_ctrl_transfer(_VENDOR_OUT, proto.REQ_GET_TXEMPTY, 0, None, None)

    def test_set_interface_altsetting_stalls(self) -> None:
        for index, port in self.each_port():
            with self.subTest(port=index):
                with self.assertRaises(usb.core.USBError):
                    self.board.device.ctrl_transfer(
                        _STANDARD_OUT_INTERFACE, _REQ_SET_INTERFACE, 1, index, 0)


if __name__ == "__main__":
    unittest.main()
