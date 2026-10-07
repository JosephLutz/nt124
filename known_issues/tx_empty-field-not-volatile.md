# `tx_empty` is the one uart_t state field that isn't `volatile`

**Severity:** Very low (stylistic/consistency issue; no live race
identified with the current call sites).

**Confidence:** Confirmed as an inconsistency; not confirmed as an
active bug.

**File:** `src/project/uart/uart.h` (`struct uart_t`'s `tx_empty` field).

## The issue

Every other RX/TX state field in `struct uart_t` that's touched from
both ISR and thread-mode contexts is `volatile`: `tx_state`, `rx_state`,
`num_read`, `tx_num_to_send`, `tx_curr_buffer_index`,
`tx_dma_buffer_index`, etc. `tx_empty` (`bool tx_empty;`) is the one
exception.

Traced its actual readers/writers:
- Written from `sys_tick_handler()` (the highest-priority ISR in this
  firmware).
- Written from `usbuart_usb_out_cb()`, always inside that function's
  `CM_ATOMIC_BLOCK()` (full PRIMASK mask).
- Read from `send_ctrl_update()`, which today is only ever called from
  inside `sys_tick_handler()` itself.

Given the only reader currently runs in a context nothing can preempt
(it's the top-priority ISR reading its own prior write), and the other
writer is fully interrupt-masked, there's no live data race with the
code as it stands today.

## Why it's worth fixing anyway

It's an inconsistency with the rest of the struct's volatile discipline,
and it's fragile: if `send_ctrl_update()` is ever called from anywhere
else, or if `sys_tick_handler()`'s priority or `tx_empty`'s read/write
sites change during some future refactor, the missing `volatile` could
silently become a real bug (the compiler would be free to cache a stale
value across the call, especially relevant given this firmware builds
with `-O3`).

## Next steps

- Low-risk, mechanical fix: add `volatile` to the field declaration.
- No specific test needed beyond the existing regression suite, since
  this isn't expected to change any current observable behavior.
