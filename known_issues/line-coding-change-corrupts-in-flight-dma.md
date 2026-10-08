# Line coding change can corrupt an in-flight DMA transfer

**Severity:** Low-medium (requires a line coding change to land while a
transfer is actively in progress; window is narrow but the firmware does
nothing to avoid it).

**Confidence:** Confirmed mechanism, not reproduced on hardware.

**File:** `src/project/uart/uart.c`, `set_uart_parameters()` (around line
360), called from `usbuart_set_line_coding()` (around line 648). The gap is
explicitly flagged by the existing comment at line 704: `/* need to make
certain we can change at this time (is DMA finished, lines set at state
saying no longer trying to send) */`.

## The code

`set_uart_parameters()` reconfigures baud/bits/parity/stopbits by:

```c
usart_disable(dev->hardware->usart);
usart_set_baudrate(dev->hardware->usart, dev->baud);
usart_set_databits(dev->hardware->usart, (uint32_t)dev->bits);
usart_set_stopbits(dev->hardware->usart, dev->stopbits);
usart_set_parity(dev->hardware->usart, dev->parity);
usart_set_flow_control(dev->hardware->usart, dev->flowcontrol);
usart_set_mode(dev->hardware->usart, USART_MODE_TX_RX);
usart_enable(dev->hardware->usart);
```

It never touches the TX or RX DMA channels, and never checks `tx_state`/
`rx_state` first.

## The issue

If a TX DMA transfer is actively in flight (`tx_state == TX_WORKING`) when
this runs, `usart_disable()` stops the USART from generating the TXE
requests DMA is waiting on, but the TX DMA channel itself is never disabled
-- it stays armed, mid-count, holding onto its current `CNDTR`/`CMAR`. When
`usart_enable()` re-enables the USART moments later with the *new*
baud/bits/parity, the same DMA transfer resumes from wherever it left off.
The remaining bytes of that buffer then go out on the wire at the new baud
rate and/or frame format -- garbage, from the receiving end's perspective --
before DMA's transfer-complete interrupt eventually fires and lets
`tx_state` recover normally. (The DMA registers themselves are untouched, so
this isn't expected to be a permanent stall -- just a mid-stream format
glitch on whatever was still queued.)

RX is less exposed to a stuck state the same way (RX DMA doesn't need a
completion interrupt to keep accepting bytes), but toggling the USART
mid-byte would likely register as a framing/noise error on whatever byte was
in flight at the moment of the reconfigure.

This is a different, narrower problem than the already-known "extra idle
frame byte emitted on line coding change" issue (see git history / `usart
disable then re-enable sends an idle frame as the first thing back out`)
-- that one is about an always-happens spurious byte; this one is about
mid-transfer corruption that only happens if a transfer happens to be
in-flight at the moment of the change.

## Next steps

Deferred: this is expected to be addressed together with the planned work
to generalize line-coding handling (which will also need to touch
`bDataBits`-switch value handling and the `tx_empty`/`rx_buffer` volatility
issues already tracked separately). Candidate approach when that work
happens: have `usbuart_set_line_coding()` wait for/force `tx_state` to
`TX_IDLE` (and the RX side quiesced) before calling `set_uart_parameters()`,
rather than reconfiguring unconditionally.
