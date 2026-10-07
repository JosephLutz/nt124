# usb_reset_hardware()/usb_platform_init() toggle the CRC peripheral's clock for no apparent reason

**Severity:** Very low (no concrete failure scenario identified; flagged
because it looks purposeless, not because it's confirmed harmful).

**Confidence:** Low -- this is a "looks odd" observation, not a
confirmed bug.

**File:** `src/project/platform/STM32F1/platform_usb.c`
(`usb_reset_hardware()` and `usb_platform_init()`).

## The observation

`usb_reset_hardware()` disables the CRC peripheral's clock;
`usb_platform_init()` re-enables it. Nothing else in this codebase
touches the CRC peripheral at all -- no `crc_*()` calls anywhere in
`src/project/`. Both functions are each called exactly once at boot, in
the correct relative order (reset before init), so this isn't causing
an observable problem as far as could be determined by reading the
code.

Possibly inherited from the Black Magic Debug project this firmware is
based on (per `CLAUDE.md`), where CRC might have had a real use (e.g.
firmware image verification) that doesn't apply here.

## Next steps

- Low priority. Worth a quick check of whether anything (bootloader,
  DFU process, etc.) outside `src/project/` depends on CRC being
  enabled before concluding this is dead code to remove.
- If confirmed unused, removing both the disable and the enable would
  be a pure cleanup with no expected behavioral change.
