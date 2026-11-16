# Autonomous paper-trading cycle

`bitcoin_ai.autopilot.run_paper_cycle` connects the completed-close SMA baseline,
risk manager, and simulation-only account for one decision cycle. It is deliberately
not a scheduler or daemon: callers must supply completed candles and timezone-aware
timestamps. It has no network, exchange, wallet, or live-order capability.

## Cycle behavior

1. Validate the candle history and calculate the strategy target.
2. Mark account equity to the latest completed close.
3. Apply exposure, daily-loss, drawdown, data-freshness, cooldown, and kill-switch
   gates.
4. Simulate a rebalance only when permitted.
5. If a risk halt is triggered, simulate de-risking existing BTC to cash. A stale
   feed does not trade because the price cannot be trusted.
6. Record the last simulated trade time in the in-memory risk state.

The caller must persist account and risk state safely before this can become a
restart-resilient service. Do not treat this one-cycle function as an always-on bot.
