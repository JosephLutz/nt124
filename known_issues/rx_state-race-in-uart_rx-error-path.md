# Unprotected `rx_state` read-modify-write race in `uart_RX()`'s error path

**Severity:** Medium-high. **Confidence:** Medium (the race window and
mechanism are concretely identified; actually triggering it needs a real
line error landing at an unlucky moment, which hasn't been reproduced on
the bench).

**File:** `src/project/uart/uart.c`

## The normal flow this is supposed to follow

`dev->rx_state` is a bitfield (`RX_NEED_SERVICE`, `RX_P_ERROR`,
`RX_F_ERROR`, `RX_N_ERROR`, `RX_OR_ERROR`, etc., uart.h:13-24) that gets
read and written from several different interrupt contexts running at
different NVIC priorities (lower number = higher priority, see
`platform.h:21-27`):

- `uart_RX_DMA()` -- the RX-DMA-complete ISR -- runs at `IRQ_PRI_UART_RX_DMA`
  (priority 2).
- `uart_RX_timer()` -- the idle-gap timer ISR -- runs at `IRQ_PRI_UART_TIM`
  (priority 3).
- `uart_RX()` -- the plain USART ISR (RXNE/error flags) -- runs at
  `IRQ_PRI_UART` (priority 5, the *lowest* priority of this group, meaning
  it's the one most likely to get interrupted by the others).

Everywhere this file already protects a field shared across these
contexts, it does so by disabling the relevant NVIC lines first. You can
see this pattern explicitly in `send_rx()` (uart.c:822-824), `uart_RX_DMA()`
(uart.c:892-895), and `uart_RX_timer()` (uart.c:957-960) -- each one calls
`nvic_disable_irq()` on the other RX-related IRQ lines for that port
*before* touching `dev->rx_state` or related fields, then re-enables them
afterward. This is exactly the pattern whose absence caused the 26-hour
lockup bug and the EXTI9 misrouting bug fixed earlier this session -- the
project has already run into this class of problem more than once.

## Where it breaks

`uart_RX()`'s error branch doesn't follow that pattern. Here's the whole
function (uart.c:919-949):

```c
inline static void uart_RX(struct uart_t *dev) {
	uint32_t uart_sr = USART_SR(dev->hardware->usart);
	UART_TRACE(dev, __LINE__);
	if (uart_sr & (USART_SR_PE | USART_SR_FE | USART_SR_NE | USART_SR_ORE)) {
		UART_TRACE(dev, __LINE__);
		// read character to clear the error flag
		usart_recv(dev->hardware->usart);
		// store which error occured
		if (uart_sr & USART_SR_PE)
			dev->rx_state |= RX_P_ERROR;
		if (uart_sr & USART_SR_FE)
			dev->rx_state |= RX_F_ERROR;
		if (uart_sr & USART_SR_NE)
			dev->rx_state |= RX_N_ERROR;
		if (uart_sr & USART_SR_ORE)
			dev->rx_state |= RX_OR_ERROR;
	} else {
		... (the no-error branch DOES disable timer_irqn before touching state) ...
```

Notice the error branch (the `if` side) never calls `nvic_disable_irq()` on
anything. Each `dev->rx_state |= RX_x_ERROR;` is a plain
read-modify-write: the CPU reads the current value of `rx_state` into a
register, ORs in the new bit, and writes the result back. That's at least
three separate instructions (load, or, store) with no atomicity guarantee
at all.

`uart_RX_DMA()` runs at a *higher* priority (2) than `uart_RX()` (5), which
on a Cortex-M3 means it can preempt `uart_RX()` at literally any
instruction boundary -- including in between the load and the store of that
read-modify-write. If it does, and it calls `process_rx()`
(uart.c:792-817), which does its own read-modify-write of the same field
(`dev->rx_state |= RX_OR_ERROR;` at uart.c:801, or the multi-bit clear
inside `send_rx()` at uart.c:880-881), then whichever one's *store*
instruction executes last simply overwrites the other's result. The one
that got overwritten is silently lost -- not merged, not reapplied, gone.

## Trigger sequence

This needs two things to happen close enough together to overlap:

1. A real USART line error (parity, framing, noise, or overrun) arrives,
   triggering `uart_RX()`'s error branch.
2. While that branch is mid-read-modify-write of `dev->rx_state` (between
   loading the old value and storing the new one), an RX DMA buffer-full
   event fires and preempts it, running `uart_RX_DMA()` → `process_rx()`,
   which also reads and writes `dev->rx_state`.

This is a narrow timing window -- a handful of instructions wide -- so it
needs a real line error landing at just the wrong moment relative to
normal DMA buffer-fill timing. Not something that would show up under
clean bench conditions; more likely under real-world line noise or a noisy
RS-485/RS-422 bus.

## Observable symptom

A line error that should have been flagged to the host (as
`ACM_CTRL_FRAMING`/`PARITY`/`OVERRUN` in the next packet's status header,
per the already-fixed reporting logic in `send_rx()`) could instead
silently vanish -- the bit gets set by `uart_RX()`, then immediately
clobbered by a concurrent `process_rx()` store that doesn't include it.
The opposite is also possible: `process_rx()`'s `RX_NEED_SERVICE` bit (or
its own freshly-set `RX_OR_ERROR`) could get wiped out by a
stale-snapshot store coming from `uart_RX()`'s side, landing after it.
