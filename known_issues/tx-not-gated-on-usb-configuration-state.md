# TX is never gated on USB configuration state

**Severity:** High. **Confidence:** High (traced precisely through both
this firmware and the relevant libopencm3 source).

**Files:** `src/project/usb/usb.c`, `src/project/uart/uart.c`

## The normal flow this is supposed to follow

A USB device has to behave differently depending on whether the host has
told it to go "configured" (via `SET_CONFIGURATION`) or not. Before
`SET_CONFIGURATION(1)`, or after `SET_CONFIGURATION(0)`, a device is
supposed to only respond on endpoint 0 (control transfers) -- not on its
bulk/interrupt endpoints at all. This firmware tracks that with one static
variable, `configured` (usb.c:51), set from `nt124_set_config()` (the
callback libopencm3 invokes on every `SET_CONFIGURATION` request) and read
back through `nt124_get_config()` (usb.c:363-366):

```c
int nt124_get_config(void)
{
	return configured;
}
```

The RX side of this firmware does this correctly. `send_rx()` (uart.c:819),
which delivers received UART data up to the host over the bulk IN
endpoint, checks it explicitly:

```c
void send_rx(struct uart_t *dev) {
	...
	if (dev->rx_state & RX_NEED_SERVICE) {
		if (nt124_get_config()) {
			... actually write the packet to the USB endpoint ...
		} else {
			/* Not configured ... leave RX_NEED_SERVICE set ... */
			serviced = false;
		}
```

So: no delivery happens while `configured == 0`. `schedule_ctrl_update()`
(uart.c:236) does the same thing for modem-status/tx-empty notifications --
it's wrapped in `if (nt124_get_config())` too. Both halves of the *RX and
status* path respect configuration state, which is a fix already made
this session (see `SEND_RX_LOCKUP_NOTES.md`).

## Where it breaks

The **TX** side -- data flowing from the USB host down into the physical
UART line -- has no such check anywhere. `usbuart_usb_out_cb()` (uart.c:582),
the function that runs every time the host writes to a port's bulk OUT
endpoint, reads the packet and immediately arms the UART's TX DMA with it:

```c
inline static void usbuart_usb_out_cb(struct uart_t *uart, usbd_device *dev) {
	int len;

	nvic_disable_irq(uart->hardware->tx.dma_irqn);
	...
	len = usbd_ep_read_packet(dev, uart->ep, uart->buffers[uart->tx_curr_buffer_index], CDCACM_PACKET_SIZE);
	if ((uart->tx_state != TX_WORKING) && (len)) {
		gpio_set(uart->hardware->dir.port, uart->hardware->dir.pin);
		...
		dma_set_memory_address(...);
		dma_set_number_of_data(uart->hardware->tx.dma, uart->hardware->tx.channel, len);
		...
		dma_enable_channel(uart->hardware->tx.dma, uart->hardware->tx.channel);
```

There's no `if (nt124_get_config())` anywhere in this function. It doesn't
know or care whether the device is supposed to be configured right now --
it just runs whenever the bulk OUT endpoint callback fires.

The reason that callback can fire *at all* while deconfigured is the other
half of the problem, in `usb.c`. `nt124_set_config()` (usb.c:368) is what
libopencm3 calls on every `SET_CONFIGURATION` request -- including a
deconfigure (`wValue = 0`). Checking libopencm3's own
`usb_standard_set_configuration()` (`src/libopencm3/lib/usb/usb_standard.c`)
confirms this precisely:

```c
/* Reset all endpoints. */
usbd_dev->driver->ep_reset(usbd_dev);

if (usbd_dev->user_callback_set_config[0]) {
	...
	for (i = 0; i < MAX_USER_SET_CONFIG_CALLBACK; i++) {
		if (usbd_dev->user_callback_set_config[i]) {
			usbd_dev->user_callback_set_config[i](usbd_dev, req->wValue);
		}
	}
}
```

It resets every endpoint first (tearing them down, as it should for a
deconfigure), but then calls `nt124_set_config(usbd_dev, req->wValue)`
unconditionally -- there's no `if (req->wValue > 0)` guard around that call
at all. So `nt124_set_config()` runs with `wValue == 0` too, and it does
exactly the same thing it does for a real configure:

```c
static void nt124_set_config(usbd_device *dev_, uint16_t wValue)
{
	configured = wValue;  // correctly becomes 0

	usbd_ep_setup(dev_, 0x01, USB_ENDPOINT_ATTR_BULK,
					CDCACM_PACKET_SIZE, ACM0_UART_OUT_CALL);
	usbd_ep_setup(dev_, 0x81, USB_ENDPOINT_ATTR_BULK,
					CDCACM_PACKET_SIZE, ACM0_UART_IN_CALL);
	... (same for all 4 ports, 8 endpoints total) ...

	usbd_register_control_callback(...);  // re-registers all 5 vendor requests too
}
```

`configured` does correctly become `0`. But `usbd_ep_setup()` re-arms all 8
bulk endpoints -- including their OUT-endpoint callbacks
(`ACM0_UART_OUT_CALL` etc., which is `usbuart_usb_out_cb1()` and friends) --
right back into the exact same state they were in before the deconfigure.
`ep_reset()` tore them down one line earlier; `nt124_set_config()` just put
them right back up, regardless of `wValue`.

## Trigger sequence

1. Host (or a test, via `usb.core.Device.set_configuration(0)`) sends a
   standard `SET_CONFIGURATION(0)` control request.
2. `nt124_set_config()` runs with `wValue=0`: `configured` becomes 0, but
   all 8 bulk endpoints get re-armed anyway.
3. Host writes to any port's bulk OUT endpoint (a perfectly normal bulk
   write -- nothing special needed to construct this).
4. `usbuart_usb_out_cb()` fires, since the endpoint is live again. It
   never checks `configured`/`nt124_get_config()` at all, so it reads the
   packet and arms the UART's TX DMA exactly as if the device were
   configured.
5. The data goes out the physical UART TX line.

## Observable symptom

A device that's supposed to be in the "unconfigured" USB state (no
business responding on anything but endpoint 0) will still transmit
whatever's written to a bulk OUT endpoint, out the real UART wire, to
whatever's connected there. This is the TX-direction mirror of the
`send_rx()` bug that was already found and fixed on the RX side -- it was
simply never checked on this side. `tests/functional/test_RS232_deconfigure_reconfigure.py`
(written this session) only verifies the RX-side gating; it doesn't check
TX, and would need a new test to catch this if it were fixed.
