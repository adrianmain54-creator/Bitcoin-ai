# Autonomous paper-trading foundation

Bitcoin AI is being developed toward a fully autonomous BTC trader. The current stage
is deliberately paper-only: it can create a deterministic signal and apply fail-closed
risk gates, but it does not yet fetch candles continuously or place exchange orders.

## Strategy baseline

`bitcoin_ai.strategy.generate_signal` uses a transparent long/cash moving-average
trend rule. It targets the configured BTC allocation only when the fast SMA is above
the slow SMA and the latest close is above the slow SMA. Otherwise it targets cash.
This is a baseline for evaluation, not a proven edge or a price prediction.

## Risk controls

`bitcoin_ai.risk` provides:
- maximum BTC allocation (default 20%);
- daily loss halt (default 2%);
- peak-to-trough drawdown halt (default 10%);
- stale/future market-data rejection (default maximum age 180 seconds);
- rebalance cooldown (default 15 minutes);
- explicit emergency kill switch.

A daily-loss or drawdown breach halts the current risk state and requests a cash
target. An operator must deliberately reset the state; it does not silently resume
the next day. Stale data blocks rebalancing without forcing a trade on an untrusted
price. The risk layer is independent of the strategy.

## Not yet implemented

A durable always-on runner, candle ingestion, restart reconciliation, alerts, and
exchange execution are not included yet. No credentials are required or accepted.
Live trading remains disabled. Do not infer profitability from a simple trend signal.
