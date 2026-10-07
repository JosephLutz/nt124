# SET_LINE_CODING's bDataBits handling silently substitutes unsupported values

**Severity:** Low-medium (only matters if a host ever actually requests
an unsupported data-bits value).

**Confidence:** Confirmed inconsistency in the code; not confirmed to
cause a problem in practice (no evidence any real host sends 5/6/16).

**File:** `src/project/uart/uart.c`, `usbuart_set_line_coding()`
(currently lines 677-688).

## The code

```c
switch(coding->bDataBits) {
case 7:
	new_bits = 8;
	break;
case 8:
default:
	if (new_parity == USART_PARITY_NONE)
		new_bits = 8;
	else
		new_bits = 9;
	break;
}
```

CDC's `bDataBits` field allows 5, 6, 7, 8, or 16. Only 7 and 8 have
explicit cases; 5, 6, and 16 fall into `default` and are silently
treated exactly like a request for 8 data bits -- the device ACKs the
`SET_LINE_CODING` request but actually configures 8/9-bit USART frames,
not what was requested, with nothing telling the host its request was
only partially honored.

## Why this looks like a real inconsistency, not just an edge case

The parity switch immediately above this one (lines 666-676) handles its
own gap (CDC's Mark/Space parity, values 3 and 4) differently: unhandled
values leave `new_parity` at its initialized value (`dev->parity`, i.e.
the *previous* setting), not a substituted default. That "leave the
previous value in place" behavior is deliberate and already covered by
`test_invalid_enum_fields_leave_previous_value`. The databits switch
doesn't follow the same pattern -- it actively computes and applies a
substitute (8 or 9 bits) for any unhandled input instead of leaving
`dev->bits` alone.

## Next steps

- Decide whether unsupported `bDataBits` values should (a) leave the
  previous value in place, matching the parity switch's precedent, or
  (b) be explicitly rejected (e.g. via a control-transfer STALL, if the
  USB stack here supports rejecting a vendor request at that level), or
  (c) something else -- but make it a deliberate choice, not an
  accident of how the switch happened to be written.
- `test_invalid_enum_fields_leave_previous_value` would be the natural
  place to extend coverage to `bDataBits` once a decision is made.
