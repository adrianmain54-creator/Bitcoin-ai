import argparse
import json
from pathlib import Path

from .data_sources import DataSourceError, MempoolSpaceClient
from .corpus_audit import build_corpus_report, format_corpus_report
from .backtesting import BacktestError, load_close_csv, run_sma_backtest
from .knowledge import KnowledgeBase, BitcoinAnswerEngine
from .paper_service import PaperService
from .market_data import BinanceCandleClient, MarketDataError
from .performance import build_performance_report
from .state_store import PaperStateStore, StateStoreError
from .walk_forward import walk_forward_sma_backtest

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "starter.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(prog="bitcoin-ai", description="Local Bitcoin knowledge assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Ask the local Bitcoin knowledge base")
    ask_parser.add_argument("question", help="Question to answer")
    ask_parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to knowledge JSONL")
    ask_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    audit_parser = subparsers.add_parser("audit", help="Audit local knowledge corpus quality")
    audit_parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to knowledge JSONL")
    audit_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    network_parser = subparsers.add_parser(
        "network", help="Fetch a read-only live Bitcoin network snapshot"
    )
    network_parser.add_argument("--currency", default="USD", help="Three-letter currency code")
    network_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    paper_parser = subparsers.add_parser("paper-run", help="Run the continuous simulation-only BTC paper trader")
    paper_parser.add_argument("--state", type=Path, default=Path("bitcoin-ai-paper-state.json"), help="Persistent paper account state file")
    paper_parser.add_argument("--interval", choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"], default="1m")
    paper_parser.add_argument("--poll-seconds", type=float, default=60.0)
    paper_parser.add_argument("--initial-cash", type=float, default=10_000.0)
    report_parser = subparsers.add_parser("paper-report", help="Show read-only mark-to-market paper account performance")
    report_parser.add_argument("--state", type=Path, default=Path("bitcoin-ai-paper-state.json"))
    report_parser.add_argument("--initial-cash", type=float, default=10_000.0, help="Original starting cash used when the account was created")
    report_parser.add_argument("--interval", choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"], default="1m")
    report_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    backtest_parser = subparsers.add_parser("backtest", help="Research-test an SMA strategy on historical close-price CSV data")
    backtest_parser.add_argument("--csv", type=Path, required=True, help="CSV with timestamp and close columns")
    backtest_parser.add_argument("--fast-window", type=int, default=10)
    backtest_parser.add_argument("--slow-window", type=int, default=30)
    backtest_parser.add_argument("--fee-bps", type=float, default=10.0, help="Estimated fee per position change, in basis points")
    backtest_parser.add_argument("--slippage-bps", type=float, default=5.0, help="Estimated slippage per position change, in basis points")
    backtest_parser.add_argument("--periods-per-year", type=float, default=365.0, help="Use 365 for daily bars, 8760 for hourly bars")
    backtest_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    walk_parser = subparsers.add_parser("walk-forward", help="Select SMA parameters on past data and evaluate on unseen future windows")
    walk_parser.add_argument("--csv", type=Path, required=True, help="CSV with timestamp and close columns")
    walk_parser.add_argument("--candidates", default="5:20,10:30,12:48,20:80", help="Comma-separated fast:slow SMA candidates")
    walk_parser.add_argument("--train-bars", type=int, default=365)
    walk_parser.add_argument("--test-bars", type=int, default=90)
    walk_parser.add_argument("--step-bars", type=int, help="Advance between folds; defaults to test-bars")
    walk_parser.add_argument("--fee-bps", type=float, default=10.0)
    walk_parser.add_argument("--slippage-bps", type=float, default=5.0)
    walk_parser.add_argument("--periods-per-year", type=float, default=365.0)
    walk_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    if args.command == "ask":
        engine = BitcoinAnswerEngine(KnowledgeBase.from_jsonl(args.data))
        result = engine.answer(args.question)
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(result["answer"])
        if result["sources"]:
            print("\nSources:")
            for source in result["sources"]:
                print(f'[{source["id"]}] {source["title"]} — {source["url"]}')
        print(f'\nEvidence status: {"insufficient" if result["abstained"] else "retrieved"}')
        return

    if args.command == "audit":
        try:
            report = build_corpus_report(args.data)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"bitcoin-ai: corpus audit failed: {exc}\\n")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_corpus_report(report))
        return

    if args.command == "backtest":
        try:
            bars = load_close_csv(args.csv)
            result = run_sma_backtest(
                bars, fast_window=args.fast_window, slow_window=args.slow_window,
                fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
                periods_per_year=args.periods_per_year,
            )
        except (BacktestError, OSError) as exc:
            parser.exit(1, f"bitcoin-ai: backtest failed: {exc}\\n")
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Historical BTC research backtest: {result['strategy']}")
            print(f"Period: {result['start']} to {result['end']} ({result['bars_in_test']} returns)")
            print(f"Costs: {args.fee_bps:g} bps fee + {args.slippage_bps:g} bps slippage per turnover")
            print("Strategy:", json.dumps(result["strategy_metrics"], sort_keys=True))
            print("Buy & hold:", json.dumps(result["buy_and_hold_metrics"], sort_keys=True))
            print("Limitations: " + " ".join(result["limitations"]))
        return

    if args.command == "walk-forward":
        try:
            bars = load_close_csv(args.csv)
            candidates = []
            for item in args.candidates.split(","):
                fast, slow = item.strip().split(":", 1)
                candidates.append((int(fast), int(slow)))
            result = walk_forward_sma_backtest(
                bars, candidates=candidates, train_bars=args.train_bars,
                test_bars=args.test_bars, step_bars=args.step_bars,
                fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
                periods_per_year=args.periods_per_year,
            )
        except (BacktestError, OSError, ValueError) as exc:
            parser.exit(1, f"bitcoin-ai: walk-forward research failed: {exc}\\n")
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Walk-forward BTC research (out-of-sample only)")
            print(f"Folds: {result['fold_count']} | OOS returns: {result['out_of_sample_returns']}")
            print("Strategy:", json.dumps(result["out_of_sample_metrics"], sort_keys=True))
            print("Buy & hold:", json.dumps(result["buy_and_hold_metrics"], sort_keys=True))
            for fold in result["folds"]:
                print(f"Fold {fold['test_start']} to {fold['test_end']}: SMA {fold['selected_fast_window']}/{fold['selected_slow_window']}")
        return

    if args.command == "paper-run":
        try:
            service = PaperService(
                state_path=str(args.state), interval=args.interval,
                poll_seconds=args.poll_seconds, initial_cash=args.initial_cash,
            )
            service.run_forever()
        except KeyboardInterrupt:
            print("\\nBitcoin AI paper trader stopped. State was saved after the last completed cycle.")
        except (ValueError, OSError, StateStoreError) as exc:
            parser.exit(1, f"bitcoin-ai: paper trader stopped safely: {exc}\\n")
        return



    if args.command == "paper-report":
        try:
            account, _risk = PaperStateStore(args.state).load()
            closes, observed_at = BinanceCandleClient().completed_closes(interval=args.interval, limit=2)
            report = build_performance_report(account, price=closes[-1], starting_cash=args.initial_cash)
            report["observed_at"] = observed_at.isoformat()
        except (ValueError, OSError, StateStoreError, MarketDataError) as exc:
            parser.exit(1, f"bitcoin-ai: paper report unavailable: {exc}\\n")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("Bitcoin AI paper account performance (simulation only)")
            for key in ("mark_price", "cash", "btc", "btc_market_value", "equity", "net_pnl", "return_pct", "exposure_pct", "cumulative_simulated_fees", "trade_count", "observed_checkpoint_max_drawdown_pct"):
                print(f"{key}: {report[key]}")
            print(report["drawdown_note"])
            print(f"Market data observed: {report['observed_at']}")
        return

    if args.command == "network":
        try:
            result = MempoolSpaceClient().snapshot(currency=args.currency)
        except (DataSourceError, ValueError) as exc:
            parser.exit(1, f"bitcoin-ai: live data unavailable: {exc}\n")
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(f'Bitcoin network snapshot ({result["currency"]})')
        print(f'BTC price: {result["price"]["value"]:,.2f} {result["currency"]}')
        print(f'Block height: {result["block_height"]["value"]:,}')
        print(f'Mempool transactions: {result["mempool"]["value"]["count"]:,}')
        print(f'Fastest fee: {result["recommended_fees"]["value"]["fastestFee"]} sat/vB')
        print(f'Provider: {result["provider"]}')
        print(f'Retrieved: {result["retrieved_at"]}')
        print(result["disclaimer"])


if __name__ == "__main__":
    main()
