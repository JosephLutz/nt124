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

- [Missing `volatile` on TX buffer-index fields](missing-volatile-on-tx-buffer-index-fields.md) -- medium severity, high confidence
- [DIR pins glitch high at boot](dir-pins-glitch-high-at-boot.md) -- medium severity, confirmed, narrow real-world impact
- [RXNE/DMA byte-stealing race on error](rxne-dma-byte-stealing-race-on-error.md) -- high severity, confirmed on hardware
- [Missing `-Wall` compiler warning flag](missing-wall-compiler-warning-flag.md) -- cosmetic, confirmed
