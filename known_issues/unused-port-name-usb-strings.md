# "Port 1".."Port 4" USB strings are defined but never shown to the host

**Severity:** Trivial (cosmetic/missing-feature, not a malfunction).

**Confidence:** Confirmed by reading the code.

**File:** `src/project/usb/usb.c` (`usb_strings[]`, and each
`portN_data_iface`'s `.iInterface` field).

## The issue

`usb_strings[]` includes `"Port 1"` through `"Port 4"` at string
descriptor indices 4-7. But every interface descriptor
(`port1_data_iface` through `port4_data_iface`) sets `.iInterface = 0`
(no string). Nothing ever points the host at these four strings, so
they're dead data -- `lsusb -v`, Windows Device Manager, etc. will never
show per-port names; all 4 ports just show as unnamed interfaces under
the one device-level product string.

This looks like an intended feature (label each interface distinctly)
that was defined but never wired up.

## Next steps

- If per-port names are wanted: set each `portN_data_iface`'s
  `.iInterface` to the matching string index (4 for port 1, 5 for port
  2, etc. -- double check against the `uart_lookup[]`/ACM-to-physical-port
  mapping so the *displayed* name matches the port the host actually
  thinks it's talking to).
- If not wanted: remove the four unused string table entries.
- Cosmetic only; no test coverage needed either way beyond confirming
  enumeration still works if descriptors are changed.
