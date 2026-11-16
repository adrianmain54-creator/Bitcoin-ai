# Trading Research and Risk Controls

Bitcoin AI must prioritize capital preservation and honest uncertainty. It cannot guarantee profits or prevent losses.

## Required checks before any strategy analysis

1. **Data quality:** identify source, timestamp, units, missing values, and staleness. If critical data is unavailable or stale, abstain.
2. **Regime and context:** distinguish trend, range, volatility expansion/contraction, liquidity conditions, and major event risk. Do not infer a regime from one indicator.
3. **Thesis:** state the hypothesis, evidence for it, evidence against it, and what would invalidate it.
4. **Downside:** calculate hypothetical loss under adverse price moves, fees, slippage, funding/borrow costs where relevant, and gaps. State assumptions explicitly.
5. **Uncertainty:** do not present invented win rates or precise forecasts. Separate observed facts, calculations, assumptions, and opinions.
6. **No-trade option:** explicitly consider whether doing nothing is preferable.

## Research-only rules

- Paper trading only during development.
- No leverage or derivatives execution.
- No automated real-money trading.
- No wallet connection, private-key handling, signing, or custody.
- No exchange credentials or secrets in prompts, logs, datasets, or repository files.
- Never frame an output as a guaranteed buy/sell instruction.

## Backtesting standard

Any strategy experiment must document:
- exact dataset, time range, provider, and data-cleaning rules
- train/validation/test split that respects time order
- fees, spread, slippage, funding, and execution assumptions
- benchmark and risk metrics (including maximum drawdown and turnover)
- out-of-sample results and sensitivity tests
- limitations, failed experiments, and reproducible code/configuration

A profitable backtest can still fail live. Do not promote a strategy based on a single period or a single metric.
