# Known issues

Each file in this folder documents one open, suspected, or unconfirmed
firmware problem, in enough depth to pick up and work from cold: the
normal/intended code flow, exactly where it deviates, a precise trigger
sequence, and the observable symptom.

**The convention:** when an issue here is fixed, or investigated and
determined not to actually be a bug, delete its file in the same commit as
the fix (or the commit that documents the "not a bug" conclusion,
referencing it in the commit message/`SEND_RX_LOCKUP_NOTES.md` instead).
This folder is only ever supposed to hold *open* issues -- git history is
where the resolved ones live on, not a stale write-up sitting here. An
empty folder (eventually just this README) means nothing's outstanding.

## Current issues

- [Line coding change can corrupt an in-flight DMA transfer](line-coding-change-corrupts-in-flight-dma.md) -- low-medium severity, confirmed mechanism, deferred alongside the other line-coding work below
- [`tx_empty` field not volatile](tx_empty-field-not-volatile.md) -- very low severity, confirmed inconsistency, no live race identified yet
- [bDataBits switch silently substitutes unsupported values](databits-switch-silently-substitutes-unsupported-values.md) -- low-medium severity, confirmed inconsistency with the adjacent parity switch's handling
- [rx_buffer/buffers not volatile](rx-buffers-not-volatile.md) -- very low severity, confirmed inconsistency, no concrete failure scenario found
