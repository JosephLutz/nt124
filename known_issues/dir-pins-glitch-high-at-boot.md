# All 4 ports' RS-485 DIR pins glitch HIGH for a few instructions at every boot

**Severity:** Medium. **Confidence:** Confirmed mechanism; narrow
real-world impact. **Files:** `src/project/platform/STM32F1/platform_STM32F1.c`,
`src/project/platform/STM32F1/platform_uart.c`, `src/project/main.c`

## The normal flow this is supposed to follow

Each UART port has a "DIR" pin that controls direction on an RS-485/RS-422
transceiver -- asserted (driven high) while this UART is actively
transmitting, so the transceiver's driver is enabled onto the shared bus,
and deasserted (low) the rest of the time so the transceiver stays in
receive mode and doesn't contend with other devices on the bus. You can
see this in `usbuart_usb_out_cb()` (uart.c:597): `gpio_set(uart->hardware->dir.port, uart->hardware->dir.pin);`
right before a TX burst starts, and `set_uart_parameters()` (uart.c:411):
`gpio_clear(dev->hardware->dir.port, dev->hardware->dir.pin);` as part of
bringing a port up. The intent is clear: DIR should be low (receive mode,
bus released) at every moment except while this port is actually
transmitting.

## Where it breaks

`main.c`'s startup sequence is:

```c
platform_reset_hardware();
platform_init();
uart_init();
usb_init();
```

`platform_init()` (`platform_STM32F1.c:35-93`) includes this block, labeled
as driving "unused" pins for a debug LED purpose:

```c
{	// DEBUG: LEDs
	gpio_set_mode(GPIOA, GPIO_MODE_OUTPUT_10_MHZ, GPIO_CNF_OUTPUT_PUSHPULL, UNUSED_PORTA_PIN1 | UNUSED_PORTA_PIN2);
	gpio_set(GPIOA, UNUSED_PORTA_PIN1 | UNUSED_PORTA_PIN2);
	gpio_set_mode(GPIOB, GPIO_MODE_OUTPUT_10_MHZ, GPIO_CNF_OUTPUT_PUSHPULL, UNUSED_PORTB_PIN1);
	gpio_set(GPIOB, UNUSED_PORTB_PIN1);
	gpio_set_mode(GPIOC, GPIO_MODE_OUTPUT_10_MHZ, GPIO_CNF_OUTPUT_PUSHPULL, UNUSED_PORTC_PIN1 | UNUSED_PORTC_PIN2 | UNUSED_PORTC_PIN3);
	gpio_set(GPIOC, UNUSED_PORTC_PIN1 | UNUSED_PORTC_PIN2 | UNUSED_PORTC_PIN3);
}
```

where (from the `#define`s right above, `platform_STM32F1.c:14-19`):

```c
#define UNUSED_PORTA_PIN2 GPIO7   // = PA7
#define UNUSED_PORTC_PIN1 GPIO0   // = PC0
#define UNUSED_PORTC_PIN2 GPIO1   // = PC1
#define UNUSED_PORTC_PIN3 GPIO4   // = PC4
```

Cross-checking those exact pins against each port's `.dir` field in
`platform_uart.c`:

| Pin | "Unused" macro | Actually used as |
|---|---|---|
| PA7 | `UNUSED_PORTA_PIN2` | UART1's DIR pin (`platform_uart.c:58-62`) |
| PC1 | `UNUSED_PORTC_PIN2` | UART2's DIR pin (`platform_uart.c:117-121`) |
| PC0 | `UNUSED_PORTC_PIN1` | UART3's DIR pin (`platform_uart.c:176-180`) |
| PC4 | `UNUSED_PORTC_PIN3` | UART4's DIR pin (`platform_uart.c:234-238`) |

Every single one of the "unused LED" pins this block drives high is
actually a live UART's DIR pin. This isn't a one-port coincidence -- it's
all 4, exactly. The pin-naming (`UNUSED_PORTx_PINn`) and the "DEBUG: LEDs"
comment are simply stale relative to what `platform_uart.c` repurposed
those same physical pins for later.

The window where this matters is between `platform_init()` driving them
high and `uart_init()` reclaiming them: `uart_init()` →
`setup_uart_device()` → `set_uart_parameters()` (uart.c:357-414) does
`gpio_clear(dev->hardware->dir.port, dev->hardware->dir.pin);` for each
port near the end of bringing it up -- but that's a handful of instructions
*after* `platform_init()` already drove them high, and `setup_uart_device()`
itself does other setup (DMA, timers, EXTI, pin modes) before even
reaching `set_uart_parameters()`.

## Trigger sequence

Just a normal boot or hardware reset. No special user action needed -- this
happens every single time, deterministically, at the very start of
`main()`.

## Observable symptom

For the sub-millisecond window between `platform_init()` and
`uart_init()` reclaiming each pin: all 4 ports' RS-485/RS-422 transceiver
drivers would be enabled simultaneously, with nothing actually being
clocked out yet. On a live RS-485 multi-drop bus with other devices
already talking, this is a brief, simultaneous assertion of 4 drivers onto
the bus at once -- a potential bus contention glitch, though extremely
short. **Confirmed harmless for every test this session**, because the
bench's transceiver has been in RS-232 or internal loopback mode the whole
time, and it was separately confirmed earlier this session (via the actual
SP339E datasheet) that "when it is in RS-232 mode the DIR line does not
affect anything." So this would only matter on real deployments actually
using RS-485/RS-422 mode on the transceiver, at the exact moment of a
reset or power-up.
