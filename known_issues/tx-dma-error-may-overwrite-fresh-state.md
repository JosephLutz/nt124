# TX DMA error could overwrite freshly-armed TX state

**Severity:** Low (requires an actual DMA transfer error; architecturally
possible, not confirmed to occur).

**Confidence:** Unconfirmed -- flagged by pattern-matching against the
RX-side issue in `rx-dma-error-leaks-irqs.md` (independent `if (TCIF)`/
`if (TEIF)` checks in the same function, rather than coordinated
handling), not verified by reproducing it.

**File:** `src/project/uart/uart.c`, `uart_TX_DMA_empty()` (currently
around line 764).

## The code

```c
inline static void uart_TX_DMA_empty(struct uart_t *dev) {
	dma_disable_channel(dev->hardware->tx.dma, dev->hardware->tx.channel);
	usart_disable_tx_dma(dev->hardware->usart);
	UART_TRACE(dev, __LINE__);
	if (dma_get_interrupt_flag(dev->hardware->tx.dma, dev->hardware->tx.channel, DMA_TCIF)) {
		dma_clear_interrupt_flags(dev->hardware->tx.dma, dev->hardware->tx.channel, DMA_TCIF);
		if (dev->tx_num_to_send) {
			// ... arms a new DMA transfer, sets tx_state = TX_WORKING ...
		} else {
			dev->tx_num_to_send = 0;
			dev->tx_state = TX_IDLE;
			schedule_ctrl_update(dev, true);
		}
	}
	if (dma_get_interrupt_flag(dev->hardware->tx.dma, dev->hardware->tx.channel, DMA_TEIF)) {
		dma_clear_interrupt_flags(dev->hardware->tx.dma, dev->hardware->tx.channel, DMA_TEIF);
		dev->tx_state = TX_ERROR;
		UART_TRACE(dev, __LINE__);
	}
}
```

## The suspected issue

If both `DMA_TCIF` and `DMA_TEIF` are set in the same interrupt entry,
the `TCIF` branch runs first and can arm a brand-new DMA transfer
(setting `tx_state = TX_WORKING`, enabling the channel) or mark the port
idle (`tx_state = TX_IDLE`) -- and then the independent `TEIF` check
unconditionally stomps `tx_state = TX_ERROR` right after, regardless of
what the `TCIF` branch just did. If a new transfer was just armed, the
state machine would now claim "errored, stopped" while DMA is actually
mid-flight on that freshly-started transfer.

## Why this is unconfirmed

Would require an actual TX DMA transfer error to occur, which -- same
reasoning as the RX side -- shouldn't happen against this firmware's
fixed, valid, statically-allocated TX buffers in normal operation. Not
reproduced; flagged because the shape of the code (two independent
`if`s touching the same state, no precedence/coordination between them)
matches a pattern already confirmed to be a real bug on the RX side.

## Next steps

- Decide whether `TCIF`-then-`TEIF` in the same entry is actually
  possible on this hardware/DMA configuration (may be worth checking
  the STM32F103 reference manual/errata for whether both flags can
  genuinely be set simultaneously for one channel).
- If possible, decide the correct precedence (should an error always
  win over a completion, or should a completion that already re-armed a
  transfer take priority) and make it explicit rather than incidental.
- No test currently exercises TX DMA errors; would need one to verify
  either the risk or a fix.
