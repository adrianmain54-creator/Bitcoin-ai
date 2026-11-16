# Continuous paper trader

The local paper service polls public Binance BTC/USDT klines (default: 1-minute),
drops the currently forming candle, runs the baseline strategy and independent
risk checks, simulates any permitted rebalance, then atomically persists the
account and risk state.

## Run locally

```bash
python -m pip install -e ".[dev]"
bitcoin-ai paper-run --state ./paper-state.json --interval 1m --poll-seconds 60
```

Stop with Ctrl+C. Each completed cycle writes a JSON status line. Network/data
errors produce a no-trade status and do not mutate account state. If an existing
state file is corrupt or has an unsupported version, the service stops rather
than silently resetting balances or risk halts.

The default simulation starts with 10,000 units of quote currency, uses the
configured paper fees/slippage, and caps BTC allocation at 20%. The risk manager
uses a 2% daily loss halt, 10% peak drawdown halt, 180-second data-age limit, and
15-minute trade cooldown. These are conservative starter settings, not evidence
that the strategy is safe or profitable.

## Operational limits

- This is a local foreground process. It runs only while the computer, process,
  and network remain available; it is not deployed or supervised as a daemon.
- Binance public market data is unauthenticated but still subject to availability,
  regional access, and rate limits.
- The service uses completed 1-minute candles. It does not use order-book depth,
  spread, trade impact, or exchange execution quality.
- The strategy is a simple SMA baseline, not a trained or adaptive model.
- State is stored locally as JSON. Protect the file and back it up; do not put it
  in a public repository. Atomic replacement protects against partial writes but
  does not encrypt the file or provide multi-process locking.
- A halt persists across restarts. Manual inspection and an intentional state
  reset are required before resuming after a halt.
- No exchange credentials, wallet access, or live-order functionality exists.

This service is for paper testing only. It is not financial advice and cannot
guarantee profit or prevent losses in future live trading.
