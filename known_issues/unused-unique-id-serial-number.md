# Chip-unique-ID serial number is computed but never used

**Severity:** Trivial (wastes a few boot cycles; misleading to a reader).

**Confidence:** Confirmed by reading the code.

**File:** `src/project/usb/usb.c` (`serial_no[9]`, `get_dev_unique_id()`,
`usb_init()`).

## The issue

`usb_init()` calls `get_dev_unique_id(serial_no)` at boot, which fills
`serial_no[9]` from the STM32's unique-ID registers. `serial_no` is
never referenced anywhere else -- not passed to `usbd_init()`, not used
in `usb_strings[]`. The actual `iSerialNumber` USB string descriptor
(`usb_strings[2]`, `iSerialNumber=3`) comes entirely from
`SERIALNO_FLASH_LOCATION` instead: a fixed flash address in `BOOTLOADER`
builds, or a hardcoded literal in non-`BOOTLOADER` builds (the latter is
intentional/documented in `CLAUDE.md` for that debug build mode, so
that part isn't the issue here).

So `get_dev_unique_id()`'s result goes nowhere in either build
configuration -- it's dead computation, and a reader encountering it
would reasonably assume the USB serial number is chip-ID-derived when
it isn't.

## Next steps

- Either remove `get_dev_unique_id()`/`serial_no` entirely if the
  flash-based serial number is the intended permanent design, or wire
  `serial_no` into the actual `iSerialNumber` descriptor if a
  chip-unique serial was the original intent and the flash-based
  scheme was meant to be a fallback/placeholder.
- Low risk either way; no test coverage currently depends on this.
