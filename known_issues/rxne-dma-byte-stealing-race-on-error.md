# RXNE/RX-DMA byte-stealing race on a line error

**Severity:** High. **Confidence:** Confirmed on hardware (2026-10-02):
streaming 8192 bytes with deliberately mismatched parity (every byte a
real USART parity error) reproducibly loses 85-93% of the data, breaking
down right at the first RX DMA buffer boundary (`RX_BUFFER_SIZE`=29
bytes) and continuing from a shifted offset into the original stream
afterward -- exactly the symptom predicted below. 40 isolated single-
buffer trials with a full settle between each showed 0 failures, so this
specifically needs sustained, back-to-back buffer fills under errors to
show up, not an isolated one. Regression test:
`tests/functional/test_RS232_parity_error_injection.py::test_data_not_lost_under_sustained_parity_errors`
(marked `@unittest.expectedFailure` until fixed).

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

## Trigger sequence (confirmed)

A sustained run of real USART line errors (parity, framing, or noise)
landing close enough together, and close enough to DMA's own handling of
those same bytes, for the race to resolve against DMA repeatedly across
many buffer fills. A single isolated error is apparently not enough to
reliably hit the race (40/40 isolated single-buffer trials passed); it
needs the back-to-back, continuous conditions a real noisy line (or the
deliberately mismatched-parity stream in the regression test) produces.

## Observable symptom (confirmed)

Silent, large-scale data loss correlated with sustained line errors: the
first DMA buffer's worth of data arrives correctly, then the stream jumps
forward to a later, shifted point in the original data -- consistent with
DMA's internal buffer position repeatedly losing sync with the real byte
stream across multiple buffer fills in a row.

## Next step

Root cause still needs the precise mechanism nailed down -- either a close
read of the STM32F103 reference manual's documented arbitration behavior
between a CPU read and a pending DMA request on the same register, or a
logic-analyzer trace of `DMA_CNDTR`/`USART_DR` access timing during the
regression test's mismatched-parity stream -- before a fix can be
designed with confidence.
