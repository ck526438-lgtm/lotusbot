"""Optimisation des paramètres avec validation hors échantillon.

Principe :
  1. l'historique est coupé en deux : IN-SAMPLE (début, par défaut 70 %) et OUT-OF-SAMPLE (fin) ;
  2. chaque combinaison est testée uniquement sur l'in-sample ;
  3. le classement se fait sur l'in-sample, avec un nombre minimal de trades ;
  4. le meilleur jeu est ensuite jugé sur l'out-of-sample, que la recherche n'a jamais vu ;
  5. on mesure aussi la robustesse : performance moyenne des réglages « voisins ».

    python -m lotusbot.optimize --out optim
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .config import AppConfig, BacktestConfig, StrategyConfig

GRID = {
    "sma_pair": [(12, 36), (9, 26), (20, 50), (8, 21)],
    "sma_trend": [100, 200],
    "rsi_band": [(35, 65), (40, 60), (30, 70)],
    "stop_atr": [1.2, 1.8, 2.5],
    "rr_ratio": [1.5, 2.2, 3.0],
    "trend_exit": [True, False],
    "session": [(0, 24), (7, 17), (7, 20), (12, 17)],
}


def combos(base: StrategyConfig):
    keys = list(GRID)
    for values in itertools.product(*(GRID[k] for k in keys)):
        p = dict(zip(keys, values))
        yield replace(
            base,
            sma_fast=p["sma_pair"][0], sma_slow=p["sma_pair"][1], sma_trend=p["sma_trend"],
            rsi_min=p["rsi_band"][0], rsi_max=p["rsi_band"][1],
            stop_atr=p["stop_atr"], rr_ratio=p["rr_ratio"], trend_exit=p["trend_exit"],
            session_start_utc=p["session"][0], session_end_utc=p["session"][1],
        )


def _key(s: StrategyConfig) -> tuple:
    return (s.sma_fast, s.sma_slow, s.sma_trend, s.rsi_min, s.rsi_max, s.stop_atr, s.rr_ratio,
            s.trend_exit, s.session_start_utc, s.session_end_utc)


def score(m: dict, min_trades: int) -> float:
    """Rendement / drawdown, pénalisé si trop peu de trades ou profit factor < 1."""
    if m["nb_trades"] < min_trades or m.get("profit_factor", 0) <= 1.0:
        return -1e9 + m["performance_pct"]
    dd = max(abs(m["max_drawdown_pct"]), 2.0)
    return m["performance_pct"] / dd


_DF = None
_BT = None


def _init(df, bt):
    global _DF, _BT
    _DF, _BT = df, bt


def _eval(strat: StrategyConfig) -> dict:
    m = run_backtest(_DF, strat, _BT).metrics
    return {"key": _key(strat), "strat": asdict(strat), **{k: v for k, v in m.items() if k != "sorties"}}


def evaluate_all(df: pd.DataFrame, strategies: list[StrategyConfig], bt: BacktestConfig, workers: int | None = None) -> list[dict]:
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(df, bt)) as ex:
        return list(ex.map(_eval, strategies, chunksize=16))


def neighbours(key: tuple, table: dict) -> list[dict]:
    """Réglages qui ne diffèrent que d'UN paramètre (mesure de robustesse)."""
    out = []
    for k, row in table.items():
        diff = sum(a != b for a, b in zip(k, key))
        if diff == 1 or (diff == 2 and (k[0], k[1]) != (key[0], key[1]) and k[2:] == key[2:]):
            out.append(row)
    return out


def optimize(df: pd.DataFrame, cfg: AppConfig, split: float = 0.7, min_trades: int = 40, top: int = 15) -> dict:
    cut = int(len(df) * split)
    warm = 300  # bougies de préchauffage des indicateurs pour l'OOS
    df_is, df_oos = df.iloc[:cut], df.iloc[max(0, cut - warm):]
    oos_start = df.index[cut]

    strategies = list(combos(cfg.strategy))
    print(f"{len(strategies)} combinaisons — in-sample {df_is.index[0]:%d/%m/%Y} → {df_is.index[-1]:%d/%m/%Y}, "
          f"out-of-sample {oos_start:%d/%m/%Y} → {df.index[-1]:%d/%m/%Y}", flush=True)

    is_rows = evaluate_all(df_is, strategies, cfg.backtest)
    for r in is_rows:
        r["score"] = score(r, min_trades)
    table = {r["key"]: r for r in is_rows}

    # robustesse : score moyen des voisins
    for r in is_rows:
        nb = neighbours(r["key"], table)
        r["voisins_perf_moy"] = round(sum(x["performance_pct"] for x in nb) / len(nb), 2) if nb else 0.0
        r["voisins_pf_moy"] = round(sum(min(x.get("profit_factor", 0), 5) for x in nb) / len(nb), 3) if nb else 0.0

    ranked = sorted(is_rows, key=lambda r: r["score"], reverse=True)[:top]

    def oos_metrics(strat_dict):
        res = run_backtest(df_oos, StrategyConfig(**strat_dict), cfg.backtest)
        t = res.trades[res.trades["entry_time"] >= oos_start]
        eq = res.equity[res.equity.index >= oos_start]
        from .metrics import compute_metrics

        start_cap = float(eq.iloc[0]) if len(eq) else cfg.backtest.initial_capital
        m = compute_metrics(t, eq / start_cap * cfg.backtest.initial_capital, cfg.backtest.initial_capital)
        m.pop("sorties", None)
        return m

    baseline_strat = asdict(cfg.strategy)
    baseline = {
        "in_sample": {k: v for k, v in table[_key(cfg.strategy)].items() if k not in ("key", "strat")}
        if _key(cfg.strategy) in table else None,
        "out_of_sample": oos_metrics(baseline_strat),
    }
    for r in ranked:
        r["oos"] = oos_metrics(r["strat"])

    # choix final : meilleur score IS dont l'OOS reste rentable et les voisins aussi
    robust = [r for r in ranked if r["oos"].get("profit_factor", 0) > 1.0 and r["voisins_pf_moy"] > 1.0]
    best = robust[0] if robust else None
    return {"baseline": baseline, "top": ranked, "best": best, "oos_start": str(oos_start),
            "n_combos": len(strategies), "bars": len(df)}


def _fmt(m: dict) -> str:
    pf = m.get("profit_factor", 0)
    return (f"perf {m['performance_pct']:+6.2f}% | DD {m['max_drawdown_pct']:6.2f}% | trades {m['nb_trades']:3d} | "
            f"réussite {m.get('taux_reussite_pct', 0):4.1f}% | PF {pf:4.2f} | E {m.get('esperance_R', 0):+.3f}R")


def print_summary(res: dict) -> None:
    print("\n=== RÉGLAGES D'ORIGINE ===")
    if res["baseline"]["in_sample"]:
        print("IN  :", _fmt(res["baseline"]["in_sample"]))
    print("OOS :", _fmt(res["baseline"]["out_of_sample"]))
    print("\n=== TOP IN-SAMPLE (jugé ensuite hors échantillon) ===")
    for i, r in enumerate(res["top"], 1):
        s = r["strat"]
        print(f"\n#{i} SMA {s['sma_fast']}/{s['sma_slow']} tendance {s['sma_trend']} | RSI {s['rsi_min']:.0f}-{s['rsi_max']:.0f} | "
              f"stop {s['stop_atr']}xATR | RR {s['rr_ratio']} | sortie tendance {s['trend_exit']} | "
              f"session {s['session_start_utc']}-{s['session_end_utc']}h UTC")
        print("   IN  :", _fmt(r))
        print("   OOS :", _fmt(r["oos"]))
        print(f"   voisins : perf moy {r['voisins_perf_moy']:+.2f}% | PF moy {r['voisins_pf_moy']:.2f}")
    b = res["best"]
    print("\n=== CHOIX ROBUSTE ===")
    print("aucun réglage ne tient hors échantillon" if b is None else f"#{res['top'].index(b) + 1} retenu")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="lotusbot.optimize")
    p.add_argument("--csv")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--split", type=float, default=0.7)
    p.add_argument("--min-trades", type=int, default=40)
    p.add_argument("--out", default="optim")
    a = p.parse_args(argv)

    from . import data

    cfg = AppConfig()
    if a.demo:
        df = data.synthetic(8000)
    elif a.csv:
        df = data.load_csv(a.csv)
    else:
        df = data.fetch_yahoo(cfg.backtest.symbol, cfg.backtest.days, cfg.backtest.interval)
    res = optimize(df, cfg, a.split, a.min_trades)
    print_summary(res)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [{**{k: v for k, v in r.items() if k not in ("key", "strat", "oos")}, **r["strat"],
             **{f"oos_{k}": v for k, v in r["oos"].items()}} for r in res["top"]]
    pd.DataFrame(rows).to_csv(out / "top.csv", index=False)
    clean = json.loads(json.dumps({k: v for k, v in res.items()}, default=str))
    for r in clean["top"]:
        r.pop("key", None)
    if clean["best"]:
        clean["best"].pop("key", None)
    (out / "resultats.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    if res["best"]:
        best_cfg = AppConfig(strategy=StrategyConfig(**res["best"]["strat"]))
        best_cfg.save(out / "config_optimisee.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
