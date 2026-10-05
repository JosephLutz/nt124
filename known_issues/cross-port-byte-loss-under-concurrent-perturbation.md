# Cross-port silent byte loss under concurrent multi-port activity

**Severity:** Medium (silent, single-byte data loss, no error flag raised).
**Confidence:** Confirmed on hardware (2026-10-05). Instrumented both
`usbd_ep_write_packet()` call sites (`send_rx()`, `send_ctrl_update()`)
with a simple "who's currently inside this call" tracker; a single
isolated repro run that also lost a byte showed the shared USB stack
being reentered 3 separate times during that one run, every single time
in the exact shape the mechanism below predicts: `send_rx()` for port 0
(endpoint 1) was still inside `usbd_ep_write_packet()` when
`send_ctrl_update()` (called from `sys_tick_handler()`) entered the same
function for ports 3, 2, and 1's own endpoints (7, 5, 3) in turn. Raw
log: `{outer_caller=send_rx, outer_port=1, inner_caller=send_ctrl_update,
inner_port=7}`, `{..., inner_port=5}`, `{..., inner_port=3}`. Reproduced
4 times total via the test below before instrumenting: twice within a
full `unittest discover` run of the whole functional suite, and twice
more running this test *in complete isolation*, repeated back to back on
its own with nothing else run first -- confirming this is an intrinsic
race in this test's own concurrent port 0/port 1 activity, not
contamination from other tests. Roughly a 1-in-5-to-7 reproduction rate
when run repeatedly on the same boot.

**File:** `src/project/uart/uart.c`

**Regression test:**
`tests/functional/test_RS232_port_isolation.py::test_port0_unaffected_by_port1_perturbation`

## Observed symptom

Running a steady 8192-byte loopback transfer on port 0 while concurrently
perturbing port 1 (line-coding churn + an induced RX overrun + a TX burst,
see `_perturb_port()` in the test) intermittently results in port 0's
transfer coming back exactly one byte short, with no line-error flag on
any packet:

- Run 1 (full suite): byte value `0x01` missing.
- Run 2 (different full-suite run): byte value `0x0f` missing.
- Run 3 (isolated, this test alone, attempt 7 of a repeated series):
  byte value `0x12` missing.

All three: everything after the missing byte shifted back one position,
otherwise correct, no error flag anywhere. A failing run also reliably
takes ~6 seconds longer than a passing one (~8.8s vs ~2.9s) -- expected,
not a separate symptom: `read_payload()`'s loop keeps retrying
`read_packet()` until it hits the full 8000ms timeout, since the missing
byte never arrives.

All losses happened early in the transfer (within roughly the first 16-18
bytes), in different positions each time -- consistent with something
timing-dependent near the *start* of the concurrent activity, not a fixed
offset.

## Confirmed mechanism

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

This reentrancy is now directly confirmed (see above). The remaining,
still-unconfirmed step is that the USB stack's internal state is what
actually gets corrupted by it -- the timing (reentrancy logged in a run
that also lost a byte) and the lack of any alternative explanation after
ruling out cross-test contamination make it the leading candidate, but no
instrumentation has yet caught the corruption itself mid-flight, only its
precondition. If so, it would corrupt or drop a byte/packet on whichever
transfer got interrupted silently, below the level the UART-side
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

- Implement the fix: stop calling `usbd_ep_write_packet()` directly from
  `sys_tick_handler()` (priority 0, can preempt anything). Have it only
  mark a port's ctrl-update as due; move the actual write to the
  thread-mode `usb_task()` poll loop, consistent with the project's
  existing "USB work only happens from one place" design intent (see
  CLAUDE.md). This doesn't claim to close every theoretical reentrancy
  path (`uart_RX_DMA()`/`uart_RX_timer()` still call `send_rx()` from real
  ISR context, at priorities 2/3, and could in principle still interrupt
  a thread-mode ctrl-update write) -- but it removes the specific,
  confirmed, highest-frequency offender (SysTick fires far more often
  than RX DMA/timer events), and is a meaningfully smaller change than a
  full redesign.
- After the fix, re-run the same instrumentation to confirm the
  SysTick/send_rx reentrancy specifically is gone, then re-run
  `test_port0_unaffected_by_port1_perturbation` repeatedly (its ~1-in-5
  to 1-in-7 rate) to see if the byte loss itself stops.
