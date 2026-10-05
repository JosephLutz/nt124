# Cross-port silent byte loss under concurrent multi-port activity

**Severity:** Medium (silent, single-byte data loss, no error flag raised).
**Confidence:** Suspected -- a concrete, plausible mechanism has been
identified by code inspection, but not yet confirmed on hardware via
instrumentation. Reproduced twice so far via the test below, both within
a full `unittest discover` run of the whole functional suite (not yet
tried as a standalone, isolated repro).

**File:** `src/project/uart/uart.c`

**Regression test:**
`tests/functional/test_RS232_port_isolation.py::test_port0_unaffected_by_port1_perturbation`

## Observed symptom

Running a steady 8192-byte loopback transfer on port 0 while concurrently
perturbing port 1 (line-coding churn + an induced RX overrun + a TX burst,
see `_perturb_port()` in the test) has twice resulted in port 0's transfer
coming back exactly one byte short, with no line-error flag on any
packet:

- Run 1: byte value `0x01` missing (everything after it shifted back one
  position, otherwise correct).
- Run 2 (different full-suite run): byte value `0x0f` missing, same
  shifted-by-one pattern.

Both losses happened early in the transfer (within roughly the first 16
bytes), in different positions each time -- consistent with something
timing-dependent near the *start* of the concurrent activity, not a fixed
offset.

## Suspected mechanism

`sys_tick_handler()` (uart.c) runs at `IRQ_PRI_SYSTICK` -- priority 0, the
*highest* in this firmware's whole scheme (see `platform.h`'s `IRQ_PRI_*`
table: SysTick=0, UART TX DMA=1, UART RX DMA=2, UART timer=3, USB=4,
UART=5). It loops over *all 4* `uarts[]` entries every time it fires and,
for whichever ports have a pending countdown, calls `send_ctrl_update()`,
which calls `usbd_ep_write_packet()` directly from this top-priority ISR
context.

That's the same function `send_rx()` calls (from `uart_RX_DMA()`/
`uart_RX_timer()`, at priorities 2/3 -- both *lower* than SysTick) to
deliver actual RX data. Both paths write to `dev->ep`, the same bulk IN
endpoint, for a given port -- but regardless of which port, both are
calls into the same shared libopencm3 USB device stack
(`usbd_ep_write_packet()` and whatever internal state it touches --
buffer descriptor table bookkeeping, endpoint status, etc.).

This project's own architecture deliberately keeps USB *polled rather
than interrupt-driven* specifically to avoid calling into that stack from
more than one execution context at a time (see `CLAUDE.md`: "the USB IRQ
is deliberately left disabled... all USB work happens from the usb_task
poll loop and the libopencm3 callbacks it invokes"). `sys_tick_handler()`
calling `usbd_ep_write_packet()` appears to be an exception to that
invariant that was never audited for it: as the highest-priority
interrupt in the system, it can preempt *any* of the following, mid-call,
with no coordination:

- The main `usb_task()` loop's own `usbd_poll()` (thread-mode, lowest
  priority -- can be preempted by literally anything).
- `uart_RX_DMA()`/`uart_RX_timer()`'s own `send_rx()` call, for a
  *different* port than the one SysTick is servicing.

If the USB stack's internal state isn't safe against being reentered this
way, a SysTick-driven ctrl-status write for one port, firing in the
middle of an in-flight RX data write for another port, could plausibly
corrupt or drop a byte/packet on whichever transfer got interrupted --
silently, since the corruption would be below the level the UART-side
error-flagging (`RX_P_ERROR`/`RX_OR_ERROR`/etc.) ever sees.

`schedule_ctrl_update()` (which arms SysTick) is called from
`set_uart_parameters()` (uart.c:413, i.e. on every line-coding change) and
from the TX-DMA-empty path (uart.c:786, i.e. after every completed TX
burst) -- both of which `_perturb_port()` in the regression test
deliberately exercises repeatedly, which would keep SysTick firing
throughout the whole perturbation window, maximizing overlap with port
0's concurrent transfer.

## Trigger sequence (as reproduced)

1. Start a large (8192-byte), steady loopback transfer on port 0.
2. Concurrently (same moment, via `ThreadPoolExecutor`): repeatedly
   reconfigure port 1's line coding (3 genuine, non-redundant changes)
   and induce a TX-empty event on port 1 (an undrained write), both of
   which call `schedule_ctrl_update()` and keep SysTick actively firing.
3. Port 0 loses exactly one byte, early in its transfer, with no error
   flag.

## Next steps

- Confirm reentrancy is actually happening: instrument (a flag/counter
  tracking nested entry into `usbd_ep_write_packet()` or the broader
  usbd core) to directly observe whether `send_ctrl_update()` (from
  SysTick) can interrupt an in-progress `send_rx()` call for a different
  port.
- Try reproducing `test_port0_unaffected_by_port1_perturbation` in
  isolation (fresh boot, just this one test, nothing else run first) a
  few times, to rule out any involvement from residual state left by
  earlier tests in a full-suite run.
- If reentrancy is confirmed as the cause, the likely fix is to stop
  calling `usbd_ep_write_packet()` directly from `sys_tick_handler()`:
  have it only set a flag/pending state, and let the existing thread-mode
  `usb_task()` poll loop (or the already-interrupt-driven `send_rx()`
  paths, which already coordinate via NVIC disable/enable) perform the
  actual write -- consistent with the project's existing "USB work only
  happens from one place" design intent.
