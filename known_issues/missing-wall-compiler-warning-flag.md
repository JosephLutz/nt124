# Dead local variable in `nt124_get_txempty_callback`, and a missing `-Wall`

**Severity:** Cosmetic (the variable itself); worth knowing about (the
Makefile finding). **Confidence:** Confirmed.

**Files:** `src/project/usb/usb.c`, `Makefile`

## What's there

```c
static enum usbd_request_return_codes nt124_get_txempty_callback(usbd_device *dev_,
		struct usb_setup_data *req, uint8_t **buf, uint16_t *len,
		usbd_control_complete_callback *complete)
{
	(void)dev_;
	(void)complete;
	register uint16_t pin_state;     // <-- declared, never used anywhere below
	struct uart_t *uart;
	...
	txempty_buffer = usbuart_get_txempty(uart);
	*buf = &txempty_buffer;
	*len = 1;

	return USBD_REQ_HANDLED;
}
```

`pin_state` is declared and never read or written anywhere in the
function. Harmless by itself -- but it's worth asking why `-Werror` (which
the `Makefile` sets, specifically to turn every warning into a hard build
failure) doesn't catch this, since an unused local variable is normally a
basic, universally-enabled warning.

## Where it breaks

The answer is in the `Makefile` itself:

```makefile
CFLAGS += -g
CFLAGS += -Wextra
CFLAGS += -Werror
CFLAGS += -Wstrict-prototypes
CFLAGS += -Wmissing-prototypes
```

It sets `-Wextra`, but never `-Wall`. This is a common mix-up:
`-Wunused-variable` (and several other commonly-expected warnings, like
plain unused-parameter in some contexts, mismatched sign comparisons
outside of strict contexts, etc.) are part of `-Wall`, not `-Wextra` --
despite the name, `-Wextra` is specifically *additional* warnings on top
of `-Wall`, not a superset that includes it. Without `-Wall` in the flags,
`-Wunused-variable` is simply never enabled, so this dead variable (and
potentially other things `-Wall` would have caught) compiles cleanly
despite `-Werror` being set.

## Why this is worth noting beyond just deleting the one variable

If `-Wall` were added, it's possible (not confirmed -- an actual build with
it hasn't been tried) that other latent issues elsewhere in the firmware
that `-Wall` would catch (other unused variables, potentially some of the
implicit-conversion or format-string classes of warning `-Wall` covers)
would surface too, each becoming a hard build failure. If `-Wall` gets
added, expect to spend some time clearing whatever it finds the first time
it's turned on -- not something to flip on casually right before a
release.
