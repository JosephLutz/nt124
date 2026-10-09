# Received BREAK isn't distinguished from an ordinary framing error

**Severity:** Low (cosmetic/informational gap -- no data loss or
corruption, just a less specific status report than the protocol already
has a bit for).

**Confidence:** Confirmed in source; not a behavior change, just a missing
one.

**Files:**
- `src/project/uart/uart.h` -- `ACM_CTRL_BRK` (`0x4`) is defined but never
  referenced anywhere outside its own declaration.
- `src/project/uart/uart.c` -- `uart_RX()`'s error branch (around line 960)
  sets `RX_F_ERROR` whenever `USART_SR_FE` is set, with no distinction for
  a break; `send_rx()` (around line 858) reports `RX_F_ERROR` to the host
  as `ACM_CTRL_FRAMING`, the same bit used for any ordinary framing error.

## The code

```c
// uart_RX()'s error branch
if (uart_sr & USART_SR_FE)
    dev->rx_state |= RX_F_ERROR;
...

// send_rx()
if (dev->rx_state & RX_F_ERROR)
    ctrl_state |= ACM_CTRL_FRAMING;
```

## The gap

A BREAK condition (the sender holding TX low continuously, longer than one
full character time) is a standard, well-defined special case of a framing
error: the USART samples a start bit, then all-zero data bits (the line is
still held low), then finds the stop-bit position also low instead of the
expected idle-high -- `USART_SR_FE` sets, and the byte read out of `DR` is
`0x00`. This is universal UART behavior, not specific to this firmware, and
not itself a bug -- see the `test_RS232_send_break_cycling.py` discussion
that prompted writing this up, which confirmed a peer receiving a break
from nt124 sees exactly one spurious `0x00`-with-framing-error byte
inserted into its stream, as expected.

What's missing is on nt124's own *receive* side: `uart_RX()` already reads
the character via `usart_recv()` in its error branch (to clear the error
flag -- see the comment there), but never checks whether that byte is
`0x00` at the same moment `FE` is set, which is the standard way a UART
driver distinguishes "this framing error was a break" from "this framing
error was just line noise/a glitch." Because of that, send_rx() has
nothing to base `ACM_CTRL_BRK` on and never sets it, even though the bit
exists in the protocol specifically for this. A host watching nt124's
status bits today sees the exact same `ACM_CTRL_FRAMING` flag for a real
break as for an ordinary single-byte framing glitch, with no way to tell
them apart without inspecting the payload byte itself (and even that's not
fully reliable, since an ordinary framing error can also happen to produce
a `0x00` payload byte).

## Next steps

Mechanical, low-risk fix if wanted: in `uart_RX()`'s error branch, when
`USART_SR_FE` is set, check whether the byte `usart_recv()` just read is
`0x00`; if so, also set a new `RX_BRK_ERROR` bit (next free value in
`rx_state_type_e`, `uart.h`) alongside `RX_F_ERROR`. In `send_rx()`, report
`ACM_CTRL_BRK` when that bit is set (in addition to, or instead of,
`ACM_CTRL_FRAMING` -- worth deciding which). Clear it in `send_rx()`'s
existing error-flag cleanup alongside `RX_F_ERROR`/the others.

No test currently exercises this distinction (it's new information, not
yet acted on); `test_RS232_framing_and_break.py`'s received-break test
already anticipates the framing-error-at-the-break-byte behavior but
doesn't check for a dedicated break flag, since there isn't one.
