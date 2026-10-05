# Residual byte loss under concurrent multi-port activity (cause unknown)

**Severity:** Medium (silent, single-byte data loss, no error flag raised).
**Confidence:** Confirmed symptom, cause not yet identified. This is what's
left of `cross-port-byte-loss-under-concurrent-perturbation.md` (resolved
and deleted) after that issue's actual cause -- the USB stack being
reentered from `sys_tick_handler()` and from `usbd_poll()`'s own call
chain -- was fixed and directly verified gone via hardware
instrumentation. The same observable symptom still occurs at a lower
rate (roughly 1-in-10 to 1-in-20 runs, down from ~1-in-5-to-7 before the
fix), so this is very likely the same underlying class of problem
(cross-port interference), just via a mechanism the instrumentation used
so far didn't cover.

**File:** `src/project/uart/uart.c`, `src/project/usb/usb.c` (suspected;
not confirmed)

**Regression test:**
`tests/functional/test_RS232_port_isolation.py::test_port0_unaffected_by_port1_perturbation`

## Observed symptom

Running a steady 8192-byte loopback transfer on port 0 while concurrently
perturbing port 1 (line-coding churn + an induced RX overrun + a TX burst,
see `_perturb_port()` in the test) intermittently results in port 0's
transfer coming back exactly one byte short, with no line-error flag on
any packet. Always early in the transfer (within roughly the first
16-18 bytes), in a different position each time.

## What's been ruled out

Both call sites and mechanisms identified and fixed as part of the
now-resolved `cross-port-byte-loss-under-concurrent-perturbation.md`
issue were directly instrumented (a shared "who's currently inside the
USB stack" tracker across all six `usbd_ep_write_packet()`/
`usbd_ep_read_packet()`/`usbd_poll()` call sites) across dozens of
reproductions, both before and after that fix. After the fix, the
instrumentation showed zero genuine cross-context reentrancy -- the only
logged entries were the expected, benign same-call-stack nesting of
`usbd_poll()` calling its own registered `usbuart_usb_out_cb()` callback.
The residual failures occurred in runs where the reentry log was
completely clean, so this is **not** the SysTick-vs-`send_rx()`
reentrancy, and **not** the `schedule_ctrl_update()` nested-critical-
-section bug -- both of those are confirmed fixed.

## Suspected direction (not yet investigated)

Given the fixed issue was specifically about the shared USB peripheral/
stack, and this failure persists at a lower rate under the exact same
trigger conditions (concurrent multi-port activity, port 1 being
perturbed while port 0's transfer is watched), the next things worth
checking are other genuinely shared resources between ports that
*weren't* part of the USB-stack reentrancy fix:

- The single USB control endpoint itself, and whether two back-to-back
  control transfers (e.g. port 1's rapid-fire `SET_LINE_CODING` calls in
  `_perturb_port()`) can overlap with a data-stage/status-stage detail
  in a way that affects a different interface's endpoint.
- Something at the UART hardware level that isn't about USB at all --
  e.g. a shared clock/RCC side effect from `set_uart_parameters()`
  (called repeatedly by port 1's baud churn) that could transiently
  affect port 0's USART if APB2 (where USART1 for port 0 sits) is
  touched for an unrelated reason.
- Re-running the same instrumentation technique (a shared in-flight
  tracker, logged reentry) on a *different* set of suspected shared call
  sites once a concrete hypothesis exists -- the technique itself worked
  well and found the original bug conclusively; it just needs pointing
  at the right code this time.

## Next steps

- Form a concrete hypothesis before instrumenting again (the previous
  investigation's success came from testing a specific, well-reasoned
  mechanism, not broad speculation).
- Once a hypothesis exists, reuse the same "shared in-flight tracker +
  reentry log" instrumentation pattern against the newly-suspected call
  sites, and reproduce via repeated runs of
  `test_port0_unaffected_by_port1_perturbation` (roughly 1-in-10 to
  1-in-20 reproduction rate -- expect to need 20-40+ attempts).
