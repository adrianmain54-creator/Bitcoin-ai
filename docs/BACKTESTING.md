# Historical research backtesting

Bitcoin AI includes a deliberately small, transparent SMA crossover backtester. It reads a local CSV with `timestamp` and `close` columns and compares a long/cash strategy with buy-and-hold over the same evaluated return intervals.

## Run

```bash
bitcoin-ai backtest --csv data/btc-daily.csv --fast-window 10 --slow-window 30 --fee-bps 10 --slippage-bps 5 --periods-per-year 365
```

CSV example:

```csv
timestamp,open,high,low,close,volume
2024-01-01,42000,43000,41500,42500,1000
2024-01-02,42500,43200,42000,43000,900
2024-01-03,43000,43100,41000,41500,1200
```

Only timestamp and close are currently consumed. Timestamps may be ISO-8601 or YYYY-MM-DD. Rows are sorted chronologically; duplicate timestamps, non-positive closes, malformed rows, and insufficient history are rejected.

## Methodology

- At close of bar *t*, calculate fast and slow simple moving averages using data available through that close.
- If fast SMA is above slow SMA, hold a long position; otherwise hold cash.
- Apply that signal to the close-to-close return from bar *t* to bar *t+1*. This one-bar delay prevents using the next bar's close to generate its own signal.
- Charge fee plus slippage assumptions on position changes, in basis points of notional turnover.
- Compare against buy-and-hold over the same return intervals.
- Report total return, annualized return, annualized volatility, zero-risk-free-rate Sharpe ratio, and maximum drawdown.

Use `--periods-per-year 365` for daily observations and `8760` for hourly observations. Set it consistently with the CSV interval. Irregular or missing intervals are not automatically detected; clean and document the input data first.

## Important limitations

This is a transparent educational baseline, not a realistic execution simulator. It uses close-to-close prices and estimated turnover costs. It does not model bid/ask spread, market impact, partial fills, funding, taxes, exchange outages, custody, or latency. It does not optimize parameters or establish out-of-sample profitability. SMA parameters are hypotheses, not recommendations.

For serious evaluation, split data chronologically into development, validation, and untouched test periods; freeze parameters before the final test; include realistic costs; compare multiple market regimes; and report all attempted strategies to reduce selection bias. A profitable historical result does not imply future returns. No real-money trading or wallet connection is part of this tool.

## Data provenance

Keep the original provider, symbol, quote currency, interval, download timestamp, timezone, adjustment/cleaning procedure, and license/terms alongside each CSV. Do not mix exchanges or quote currencies silently. This command does not download data or verify a provider's licensing terms.
