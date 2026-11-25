"""Ligne de commande LotusBot.

    lotusbot                 -> ouvre l'application de bureau
    lotusbot backtest        -> backtest EURUSD H1 (Yahoo Finance)
    lotusbot backtest --csv fichier.csv
    lotusbot scan            -> signaux temps réel dans le terminal
    lotusbot --selftest      -> autotest (utilisé par la CI sur l'exe)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig


def _load_df(args, cfg: AppConfig):
    from . import data

    if getattr(args, "demo", False):
        return data.synthetic()
    if getattr(args, "csv", None):
        return data.load_csv(args.csv)
    if cfg.live.use_mt5 or getattr(args, "mt5", False):
        from . import mt5_broker

        print(mt5_broker.connect(cfg.live))
        return data.fetch_mt5(cfg.live.mt5_symbol, 12_000)
    return data.fetch_yahoo(cfg.backtest.symbol, cfg.backtest.days, cfg.backtest.interval)


def cmd_backtest(args) -> int:
    from .backtest import run_backtest
    from .metrics import format_report
    from .report import save_report

    cfg = AppConfig.load(args.config) if args.config else AppConfig.load()
    print("Téléchargement des données H1 EURUSD...")
    df = _load_df(args, cfg)
    print(f"{len(df)} bougies du {df.index[0]:%d/%m/%Y} au {df.index[-1]:%d/%m/%Y}")
    res = run_backtest(df, cfg.strategy, cfg.backtest)
    print(format_report(res.metrics))
    if len(res.trades):
        print("\nDerniers trades :")
        cols = ["entry_time", "side", "entry", "exit", "lots", "pnl", "r_multiple", "reason"]
        print(res.trades[cols].tail(8).to_string(index=False))
    if args.out:
        files = save_report(res, args.out)
        print("\nFichiers : " + ", ".join(str(p) for p in files.values()))
    return 0


def cmd_scan(args) -> int:
    from .live import LiveScanner, wait_forever

    cfg = AppConfig.load(args.config) if args.config else AppConfig.load()
    if args.mt5:
        cfg.live.use_mt5 = True
    if args.auto:
        cfg.live.auto_trade = True
    wait_forever(LiveScanner(cfg, on_log=print))
    return 0


def selftest(log_path: str | None = None) -> int:
    """Vérifie moteur + interface sans réseau. Code de sortie 0 = OK."""
    lines = []
    ok = True
    try:
        from .backtest import run_backtest
        from .data import synthetic

        res = run_backtest(synthetic(3000))
        lines.append(f"backtest OK — {res.metrics['nb_trades']} trades, capital {res.metrics['capital_final']}")
        try:
            from .gui.app import LotusApp

            app = LotusApp()
            app.after(200, lambda: app.run_backtest_on(synthetic(3000), "autotest"))
            app.after(4000, app.destroy)
            app.mainloop()
            lines.append("interface OK")
        except Exception as exc:  # noqa: BLE001
            if "display" in str(exc).lower() or "tkinter" in str(exc).lower():
                lines.append(f"interface ignorée (pas d'écran) : {exc}")
            else:
                raise
    except Exception as exc:  # noqa: BLE001
        import traceback

        ok = False
        lines.append("ÉCHEC : " + "".join(traceback.format_exception(exc)))
    text = "\n".join(lines)
    if log_path:
        Path(log_path).write_text(text, encoding="utf-8")
    if sys.stdout:
        print(text)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lotusbot", description="LotusBot — bot de trading EURUSD H1")
    p.add_argument("--version", action="version", version=f"LotusBot {__version__}")
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--selftest-log", default=None, help=argparse.SUPPRESS)
    p.add_argument("--config", default=None, help="fichier de configuration JSON")
    sub = p.add_subparsers(dest="cmd")

    b = sub.add_parser("backtest", help="lancer un backtest")
    b.add_argument("--csv", help="données OHLC depuis un CSV (export MT5 accepté)")
    b.add_argument("--mt5", action="store_true", help="données depuis MetaTrader 5")
    b.add_argument("--demo", action="store_true", help="données synthétiques (hors ligne)")
    b.add_argument("--out", default=None, help="dossier d'export (graphique, trades CSV, rapport)")
    b.add_argument("--config", default=None)
    b.set_defaults(func=cmd_backtest)

    s = sub.add_parser("scan", help="signaux temps réel")
    s.add_argument("--mt5", action="store_true", help="utiliser MetaTrader 5")
    s.add_argument("--auto", action="store_true", help="placer les ordres automatiquement (MT5)")
    s.add_argument("--config", default=None)
    s.set_defaults(func=cmd_scan)

    args = p.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest_log)
    if not args.cmd:
        from .gui.app import run

        run()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
