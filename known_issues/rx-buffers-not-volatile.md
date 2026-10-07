# rx_buffer/buffers arrays aren't volatile, unlike their governing state

**Severity:** Very low (no concrete failure scenario found; flagged for
consistency/paranoia).

**Confidence:** Confirmed as an inconsistency; not confirmed as an
active bug.

**File:** `src/project/uart/uart.h` (`struct uart_t`'s `rx_buffer` and
`buffers` fields, currently lines 58 and 64).

## The issue

The index/state fields that govern which `rx_buffer`/`buffers` slot is
"active" (`rx_dma_index`, `tx_curr_buffer_index`, `tx_dma_buffer_index`,
`rx_state`, `tx_state`, etc.) are all `volatile`, matching this file's
general discipline for anything touched from both ISR and thread-mode
contexts (or multiple ISR priority levels). The buffer arrays themselves
are not.

`send_rx()` reads `dev->rx_buffer[dev->rx_dma_index][i]` in a tight loop
right after `process_rx()` has already swapped DMA onto the *other*
buffer -- by the time that read loop runs, DMA is no longer writing to
the buffer being read, so there's no live concurrent-write race. The
theoretical risk is purely a compiler-reordering one: nothing in the
language forbids the compiler from assuming a global array's contents
are provably unchanged across a call it can't see into (e.g. across
`process_rx()`'s internal calls), and caching/reordering a read of it
accordingly. No concrete scenario where this actually happens with this
code's structure at `-O3` has been identified.

## Next steps

- Low-risk, mechanical fix if desired: mark both arrays `volatile` for
  consistency with the rest of the struct's discipline.
- Not expected to change any observable behavior or require new test
  coverage -- this is a "make the paranoia explicit" change, not a
  behavioral fix.
