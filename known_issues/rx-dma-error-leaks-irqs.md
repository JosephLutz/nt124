# RX DMA transfer error permanently disables a port's RX interrupts

**Severity:** Low-medium (requires an actual DMA bus/transfer error to
trigger, which shouldn't happen against the static, valid SRAM buffers
this firmware uses -- but if it ever does, the affected port's RX is
silently dead until reboot/reflash).

**Confidence:** Confirmed by reading the code; not reproduced on
hardware (would require actually inducing a DMA transfer error, which
isn't currently exercised by any test).

**File:** `src/project/uart/uart.c`, `uart_RX_DMA()` (currently around
line 914), contrasted with `send_rx()` (currently around line 838).

## The code

```c
inline static void uart_RX_DMA(struct uart_t *dev) {
	dma_disable_channel(dev->hardware->rx.dma, dev->hardware->rx.channel);
	nvic_disable_irq(dev->hardware->timer_irqn);
	nvic_disable_irq(dev->hardware->rx.dma_irqn);
	nvic_disable_irq(dev->hardware->irqn);
	UART_TRACE(dev, __LINE__);
	if (dma_get_interrupt_flag(dev->hardware->rx.dma, dev->hardware->rx.channel, DMA_TCIF)) {
		dma_clear_interrupt_flags(dev->hardware->rx.dma, dev->hardware->rx.channel, DMA_TCIF);
		process_rx(dev);
		UART_TRACE(dev, __LINE__);
	}
	if (dma_get_interrupt_flag(dev->hardware->rx.dma, dev->hardware->rx.channel, DMA_TEIF)) {
		// DMA error was encountered
		// TODO: Better handiling should be implemented and not just disable the uart
		dma_clear_interrupt_flags(dev->hardware->rx.dma, dev->hardware->rx.channel, DMA_TEIF);
		dev->rx_state |= RX_DMA_ERROR;
		usart_disable(dev->hardware->usart);
		UART_TRACE(dev, __LINE__);
	}
}
```

The three `nvic_disable_irq()` calls at the top have no matching
`nvic_enable_irq()` anywhere in this function. The only thing that
re-enables them is `send_rx()`, which unconditionally disables then
re-enables all three of the same lines -- but `send_rx()` is only
reached via `process_rx()`, which is only called from the `DMA_TCIF`
branch above (or unconditionally from `uart_RX_timer()`, which is fine).

## The bug

If `DMA_TEIF` (transfer error) fires **without** `DMA_TCIF` (transfer
complete) -- a genuine DMA error on its own, not simultaneous with a
buffer filling up -- the `TCIF` branch never runs, so `process_rx()`/
`send_rx()` never run, so the three IRQs disabled at the top of this
function are never re-enabled. That port's idle-gap timer interrupt, RX
DMA completion interrupt, and per-byte RXNE/error interrupt are all
masked at the NVIC from that point on.

Nothing in the runtime reconfigure path recovers from this either:
`usbuart_set_line_coding()` -> `set_uart_parameters()` reconfigures the
USART/timer registers but never touches NVIC enable state -- only the
one-time boot sequence (`setup_uart_starting_interrupts()`) does that.
So once this happens, the port's RX is dead until reboot/reflash, with
no error surfaced beyond the already-set `RX_DMA_ERROR` bit (which nothing
currently reports to the host, since `send_rx()` -- the only thing that
would report it -- never runs again either).

The existing `// TODO: Better handiling should be implemented` comment
suggests the original author already knew this path was incomplete.

## Why this is probably rare in practice

A DMA transfer error on this channel configuration would need an actual
invalid bus access -- the source/destination addresses are fixed,
valid, statically-allocated locations (`USART_DR` and `rx_buffer[]`),
so this shouldn't occur in normal operation. This is the firmware's
attempt to handle a failure mode that may never actually happen on this
hardware. Still worth fixing properly rather than leaving a silent,
unrecoverable failure mode in place.

## Next steps

- Decide what *should* happen on a genuine RX DMA transfer error --
  right now the code's intent (`usart_disable()`) looks like "shut this
  port down deliberately," but it does that by accident (via orphaned
  NVIC state) rather than as a clean, documented, permanent disable.
- If permanent disable is actually the right behavior, do it
  deliberately and document it (and ideally report it to the host some
  way, since the port would otherwise just appear to stop working).
- If it should be recoverable, re-enable the three IRQs in the `TEIF`
  branch (matching what `send_rx()` already does unconditionally), and
  make sure `set_uart_parameters()`/a reconfigure can actually recover
  the port afterward.
- No test currently exercises this path; would need a way to
  deliberately induce a DMA transfer error to verify fully once fixed.
