# uart_reset_hardware() resets TIM1, which this firmware never uses

**Severity:** Trivial (harmless -- resets an unused, unclocked
peripheral).

**Confidence:** Confirmed by reading the code.

**File:** `src/project/platform/STM32F1/platform_uart.c`,
`uart_reset_hardware()`.

## The issue

`uart_reset_hardware()` resets `RCC_APB2RSTR_TIM1RST` alongside
`USART1RST`/`AFIORST`. All four UARTs' idle-gap timers are `TIM2`
through `TIM5` (APB1, correctly reset in the same function's second
`rcc_peripheral_reset()`/`rcc_peripheral_clear_reset()` call pair).
`TIM1` isn't instantiated, clocked, or referenced anywhere else in this
codebase -- this looks like copy-paste cruft, possibly inherited from
the Black Magic Debug project this firmware is based on (per
`CLAUDE.md`), where TIM1 may have had a real use.

## Next steps

- Remove `RCC_APB2RSTR_TIM1RST` from the reset mask. Purely a cleanup;
  no behavioral change expected since TIM1 is never clocked or used.
