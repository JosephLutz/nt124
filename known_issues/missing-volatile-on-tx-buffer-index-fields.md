# Missing `volatile` on TX ping-pong buffer-index fields

**Severity:** Medium. **Confidence:** High (the inconsistency with the
rest of the same struct is unambiguous; whether it's actually been
miscompiled is unverified without inspecting generated assembly).

**File:** `src/project/uart/uart.h`

## The normal flow this is supposed to follow

`struct uart_t` (uart.h:46-77) marks every field that's touched from both
ISR and thread-mode contexts as `volatile` -- this tells the compiler "this
value can change for reasons you can't see in this function's own code, so
don't cache it in a register across a call or a loop iteration; always
re-read/re-write memory." Look at the fields that already have this:

```c
volatile rx_state_type_e rx_state;
volatile uint16_t num_read;
volatile uint8_t rx_dma_index;
...
volatile tx_state_type_e tx_state;
...
volatile usb_tx_state_type_e usb_in_tx_state;
...
volatile int tx_empty_count_down;
volatile int ctrl_count_down;
```

Every one of these is read or written from both an ISR and thread-mode
code (or two different ISRs). That's the established, deliberate pattern
in this codebase for exactly this kind of shared state.

## Where it breaks

Three fields right next to `tx_state` in the same struct (uart.h, "TX
variables" section) are *not* `volatile`, even though they're part of the
exact same TX ping-pong mechanism and are touched from the same two
contexts as `tx_state` itself:

```c
int tx_num_to_send;
uint8_t tx_curr_buffer_index;	// buffers index to place new characters into.
uint8_t tx_dma_buffer_index;	// buffers index currently being used by DMA.
```

You can see all three being read and written from thread-mode in
`usbuart_usb_out_cb()` (uart.c:582-620, e.g. `uart->tx_curr_buffer_index`
at line 599, `uart->tx_num_to_send` at line 615) and from the TX-DMA ISR in
`uart_TX_DMA_empty()` (uart.c:747-786, e.g. `dev->tx_curr_buffer_index` at
line 756, `dev->tx_num_to_send` at lines 754/761/767).

`usbuart_usb_out_cb()` does wrap its own access in
`nvic_disable_irq(uart->hardware->tx.dma_irqn)` / `nvic_enable_irq(...)`
(uart.c:585 and 619) -- so there *is* a guard preventing the ISR from
actually running concurrently with this function. But `nvic_disable_irq()`
and `nvic_enable_irq()` are ordinary function calls into libopencm3, not
compiler intrinsics or memory barriers the compiler is required to respect
for optimization purposes. Without `volatile`, the compiler is technically
permitted -- and at `-O3`, which this project builds with (see `Makefile`)
-- to decide it already knows the value of `tx_curr_buffer_index` from
earlier in the function (or even from before the `nvic_disable_irq()`
call) and reuse that cached value instead of re-reading memory, if it
can't prove the intervening function calls could have changed it. Whether
a specific compiler actually does this for this specific code is hard to
predict without inspecting the generated assembly -- but relying on that is
exactly the kind of "it happens to work with today's compiler and
optimization settings" fragility the existing `volatile` fields in this
same struct were clearly added to avoid.

## Trigger sequence

Would require a compiler (at `-O3`) to actually perform the
register-caching optimization described above across one of the
`nvic_disable_irq`/`nvic_enable_irq` brackets in `usbuart_usb_out_cb()` --
not something that can be triggered by any specific sequence of USB
traffic; it depends on what the compiler decides to do with the code.

## Observable symptom

If it does happen: `usbuart_usb_out_cb()` or `uart_TX_DMA_empty()` acting
on a stale buffer index or stale byte count -- which buffer a chunk of data
actually gets written into, or how many bytes DMA is told to send, could
be wrong. The result would be intermittent, hard-to-reproduce TX data
corruption or a dropped/duplicated chunk, correlated with nothing
obviously identifiable from the USB traffic pattern alone (since the cause
is a compiler decision, not a timing race in the traditional sense).
