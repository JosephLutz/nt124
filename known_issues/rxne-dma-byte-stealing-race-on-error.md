# Possible RXNE/RX-DMA byte-stealing race on a line error

**Severity:** Potentially high if real. **Confidence:** Uncertain --
architecture-based reasoning only, not confirmed against the STM32F103
reference manual's documented arbitration behavior or a hardware test.

**File:** `src/project/uart/uart.c`

## The normal flow this is supposed to follow

RX data normally flows entirely through DMA: the USART's RXNE ("receive
register not empty") condition triggers a DMA request, DMA silently copies
the byte from `USART_DR` into the `rx_buffer[]` array and decrements its
internal "number of data left" counter (`DMA_CNDTR`), with no CPU
involvement at all. `process_rx()` later figures out how many bytes
actually arrived by computing `RX_BUFFER_SIZE - DMA_CNDTR(...)`
(uart.c:804) -- this only gives the right answer if *every* received byte
actually went through DMA, decrementing that counter exactly once per
byte.

## Where it breaks (or might)

`setup_uart_starting_interrupts()` (uart.c:427-445) turns on *both*
mechanisms on the same USART peripheral at the same time:

```c
static void setup_uart_starting_interrupts(struct uart_t *dev) {
	usart_disable_tx_dma(dev->hardware->usart);
	usart_enable_rx_dma(dev->hardware->usart);
	usart_enable_rx_interrupt(dev->hardware->usart);
	usart_enable_error_interrupt(dev->hardware->usart);
	...
```

`usart_enable_rx_dma()` arms DMA to respond to RXNE. `usart_enable_rx_interrupt()`
and `usart_enable_error_interrupt()` arm the CPU's own USART ISR
(`uart_RX()`) to respond to the same RXNE condition (for normal bytes) and
to PE/FE/NE/ORE (for errors). Both the DMA controller and the CPU are now
potentially reacting to the same hardware event.

`uart_RX()`'s error branch (uart.c:919-934) does this on an error:

```c
if (uart_sr & (USART_SR_PE | USART_SR_FE | USART_SR_NE | USART_SR_ORE)) {
	// read character to clear the error flag
	usart_recv(dev->hardware->usart);
	...
```

`usart_recv()` does a manual CPU read of `USART_DR` -- the same register
DMA is also watching. On STM32F1, reading `USART_DR` is part of how the
RXNE flag gets cleared (both for a plain CPU read and for a DMA-serviced
read). The concern: if the CPU's manual read in `uart_RX()`'s error branch
races against DMA's own in-progress service of that *same* byte, and the
CPU's read "wins" (i.e., happens in a way that satisfies the RXNE
condition before DMA's own access completes), DMA's internal counter
(`DMA_CNDTR`) would never decrement for that particular byte, and its
memory pointer would never advance to receive it either. Every subsequent
byte in that buffer would then land one position earlier than
`process_rx()`'s length math (`RX_BUFFER_SIZE - DMA_CNDTR(...)`) expects --
silently shifting the whole rest of the buffer out of alignment with what
the host receives.

**This one is flagged as uncertain deliberately.** Confirming it precisely
needs either a close read of the STM32F103 reference manual's documented
arbitration behavior between a CPU read and a pending DMA request on the
same register (not yet done), or a hardware test with a logic analyzer and
a way to deliberately inject a line error (parity or framing mismatch) in
the middle of a multi-byte burst, then checking whether the byte at and
after the error position comes out shifted.

## Trigger sequence (if real)

A real USART line error (parity, framing, or noise) occurring in close
enough proximity to DMA's own handling of that same byte for the race to
actually resolve against DMA -- not something that can be forced
deterministically without hardware-level fault injection.

## Observable symptom (if real)

Silent data corruption specifically correlated with real line errors: the
byte at the error position and everything after it in that DMA buffer
would be shifted by one position, read by `process_rx()`/`send_rx()` as if
it were one byte shorter or differently aligned than what was actually
received.

## Next step

Before treating this as confirmed: either trace the exact RXNE-clear/DMA-
request arbitration behavior in the STM32F103 reference manual, or design
a hardware test that deliberately injects a line error mid-burst (e.g. via
a second UART driving the same RX line with a deliberately wrong baud/
parity for one byte) and checks for a one-byte shift in everything after
it.
