"""Bare libusb/pyusb access to one nt124 USB interface.

This is the "no policy" layer: open/claim/release, raw control transfers,
raw bulk read/write. It knows the wire format's *addresses* (endpoint
numbers, request codes -- from `protocol`) but not what any of it *means*.
Build ergonomics (line-coding objects, status-header parsing, retries,
waiting/polling helpers) on top of this in `board.py`; don't add them here.
"""
from __future__ import annotations

import usb.core
import usb.util

from . import protocol as proto

_CTRL_OUT_VENDOR = (usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR
                     | usb.util.CTRL_RECIPIENT_DEVICE)
_CTRL_IN_VENDOR = (usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR
                    | usb.util.CTRL_RECIPIENT_DEVICE)


def find_device(vid: int = proto.VID, pid: int = proto.PID) -> usb.core.Device:
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise RuntimeError(f"nt124 {vid:04x}:{pid} not found")
    return dev


class RawPort:
    """One nt124 interface, claimed for exclusive userspace access.

    Only the claimed interface is detached from the in-kernel driver -- the
    other three ports keep working normally under it, and this one
    re-attaches on `release()`.
    """

    def __init__(self, device: usb.core.Device, info: proto.PortInfo):
        self.device = device
        self.info = info
        self._detached = False
        self._claimed = False

    def claim(self) -> None:
        # Do NOT call device.set_configuration(): the board is already
        # configured after enumeration, and re-setting it re-runs the
        # firmware's nt124_set_config() -- which re-registers control
        # callbacks and resets every endpoint on all 4 ports, not just
        # this one.
        if self.device.is_kernel_driver_active(self.info.index):
            self.device.detach_kernel_driver(self.info.index)
            self._detached = True
        usb.util.claim_interface(self.device, self.info.index)
        self._claimed = True

    def release(self) -> None:
        if self._claimed:
            try:
                usb.util.release_interface(self.device, self.info.index)
            except usb.core.USBError:
                pass
            self._claimed = False
        if self._detached:
            try:
                self.device.attach_kernel_driver(self.info.index)
            except usb.core.USBError:
                pass
            self._detached = False

    def __enter__(self) -> "RawPort":
        self.claim()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    # -- control transfers ---------------------------------------------
    def ctrl_out(self, request: int, value: int, data: bytes | None = None) -> None:
        self.device.ctrl_transfer(_CTRL_OUT_VENDOR, request, value,
                                   self.info.index, data)

    def ctrl_in(self, request: int, value: int, length: int) -> bytes:
        return bytes(self.device.ctrl_transfer(_CTRL_IN_VENDOR, request, value,
                                                 self.info.index, length))

    def raw_ctrl_transfer(self, bmRequestType: int, bRequest: int, wValue: int = 0,
                           wIndex: int | None = None, data_or_wLength=None):
        """Escape hatch for malformed/edge-case control transfers -- wrong
        wIndex, wrong direction/type, short/long wLength -- that ctrl_out()/
        ctrl_in()'s fixed vendor type and this port's own wIndex can't
        express. Defaults wIndex to this port's own index for convenience;
        pass an explicit one (e.g. out of range, or another port's) to test
        boundary handling. Raises usb.core.USBError on a STALL, same as a
        raw pyusb ctrl_transfer() would."""
        if wIndex is None:
            wIndex = self.info.index
        result = self.device.ctrl_transfer(bmRequestType, bRequest, wValue,
                                            wIndex, data_or_wLength)
        return bytes(result) if bmRequestType & usb.util.CTRL_IN else result

    # -- bulk transfers ---------------------------------------------------
    def bulk_write(self, data: bytes, timeout: int = 2000) -> int:
        return self.device.write(self.info.ep_out, data, timeout=timeout)

    def bulk_read(self, size: int = proto.CDCACM_PACKET_SIZE,
                   timeout: int = 1000) -> bytes:
        return bytes(self.device.read(self.info.ep_in, size, timeout=timeout))
