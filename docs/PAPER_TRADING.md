# Paper trading and automated-trader architecture

Bitcoin AI is being developed toward a 24/7 BTC trading system. The current execution component is **simulation only**.

## Current capability

`bitcoin_ai.paper_trading.PaperAccount` simulates portfolio rebalancing between cash and BTC. It:
- accepts a target BTC allocation and a reference price;
- caps the target at a configured maximum allocation;
- models adverse slippage and trading fees;
- never borrows, shorts, contacts an exchange, signs a transaction, or handles credentials;
- records timestamped simulated fills and resulting balances.

Example:

```python
from bitcoin_ai.paper_trading import PaperAccount

account = PaperAccount(cash=10_000, max_allocation=0.20, fee_bps=10, slippage_bps=5)
event = account.rebalance(target_allocation=0.15, price=60_000)
print(event)
```

This is an execution simulator, not a profitable strategy. The caller is responsible for producing a target allocation. A hold target of zero means exit the BTC position; it does not imply that the system should always trade.

## Planned always-on architecture

1. **Market data:** fetch timestamped candles and market observations from documented public endpoints. Validate symbol, quote currency, interval, missing bars, duplicates, and staleness.
2. **Signal engine:** produce buy/sell/hold or target allocation with an explanation and versioned strategy parameters.
3. **Risk gate:** reject stale data, excessive exposure, invalid prices, abnormal volatility, daily loss breaches, and repeated orders. Enforce a global kill switch.
4. **Execution adapter:** paper broker first. Any later exchange adapter must be isolated behind explicit permissions, use least-privilege trading-only credentials, and never request withdrawal permission.
5. **Persistence and recovery:** durable order/fill ledger, idempotency keys, reconciliation after restart, structured logs, health checks, and alerting.
6. **Evaluation:** chronological walk-forward tests, unseen holdout periods, realistic fees/slippage/spread, bull/bear/sideways regimes, and paper-trading forward observation.

## Before any live trading

Live execution remains disabled. It requires separate explicit approval and a reviewed exchange adapter, secret management, order reconciliation, kill switch, loss/exposure limits, outage behavior, and evidence from backtests plus a meaningful forward paper-trading period. No seed phrase or private key should ever be entered into Bitcoin AI.

## Reliability and cost

A bot can only operate while its process and network are available. A sleeping phone is not a reliable host. A free always-on host is not guaranteed; free tiers may sleep, restart, impose quotas, or change terms. A local computer can run the process while powered on and connected, but is not equivalent to resilient production hosting.

No strategy or risk control can guarantee profits or eliminate losses.
