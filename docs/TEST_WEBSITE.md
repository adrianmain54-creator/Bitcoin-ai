# Temporary test website

This is a local, read-only test dashboard for the simulation account. It is
intended to be disposable and does not change the trading engine.

## Start it

First start the paper engine in one terminal:

```bash
bitcoin-ai paper-run --state ./paper-state.json --interval 1m --poll-seconds 60
```

Then start the dashboard in another terminal:

```bash
bitcoin-ai web --state ./paper-state.json --initial-cash 10000 --port 8765
```

Open http://127.0.0.1:8765. The page refreshes every 15 seconds.

## Safety and limitations

- The server binds to loopback only; it is not public or deployed.
- The UI is read-only. It has no buy/sell buttons and exposes no order endpoint.
- It reads the existing paper state and latest completed public Binance candle.
- It displays the strategy's current SMA signal and existing risk-state fields.
- No login is provided because it must remain local to your own machine.
- Do not port-forward this service or expose it to the internet.
- The drawdown shown is only based on trade checkpoints, not a continuous curve.
- If the paper service is not running or state does not exist, the dashboard shows
  an unavailable status rather than creating/resetting an account.

Delete the `web/` folder, `web_dashboard.py`, its tests, and the `web` CLI
subcommand to remove this temporary interface. The paper engine and saved state
remain separate.
