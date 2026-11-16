# Paper performance report

Inspect the persisted simulation account without changing it:

```bash
bitcoin-ai paper-report --state ./paper-state.json --initial-cash 10000 --interval 1m
```

The command fetches the latest completed public BTC/USDT candle and reports
mark-to-market equity, net P&L and return against the supplied original starting
cash, BTC exposure, cumulative simulated fees, and trade count.

**Important limitations:** the initial cash argument must match the amount used
when the paper account was first created. The state file does not yet store an
immutable starting-capital field. Drawdown is calculated only from recorded
trade-event equity checkpoints plus the current mark; it is not a continuous
equity curve and can miss losses between trades. This report does not claim
realized P&L, win rate, or strategy profitability. The command is read-only and
does not place trades or modify the account state.
