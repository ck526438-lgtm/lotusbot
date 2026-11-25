"""Moteur de backtest événementiel de LotusBot.

Corrections par rapport au script d'origine :
  * plus de biais d'anticipation : signal sur la bougie i clôturée -> entrée à l'OUVERTURE de i+1
    (l'original entrait à l'ouverture de la bougie dont il venait de lire la clôture) ;
  * la sortie « tendance » est décidée à la clôture et exécutée à l'ouverture suivante ;
  * spread, commission et gaps (ouverture au-delà du SL/TP) sont pris en compte ;
  * si SL et TP sont touchés dans la même bougie, le SL est retenu (hypothèse prudente) ;
  * taille de position plafonnée par un levier maximal ;
  * courbe de capital valorisée à chaque bougie (P&L latent inclus).

Les prix fournis sont considérés comme des prix BID ; l'ASK = BID + spread.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BacktestConfig, StrategyConfig
from .metrics import compute_metrics
from .strategy import add_signals


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    data: pd.DataFrame
    metrics: dict = field(default_factory=dict)


TRADE_COLUMNS = [
    "entry_time", "exit_time", "side", "entry", "exit", "stop_loss", "take_profit",
    "size", "lots", "risk", "commission", "pnl", "r_multiple", "reason", "bars",
]


def run_backtest(df: pd.DataFrame, strat: StrategyConfig | None = None, bt: BacktestConfig | None = None) -> BacktestResult:
    strat = strat or StrategyConfig()
    bt = bt or BacktestConfig()
    data = add_signals(df, strat)

    o = data["open"].to_numpy()
    h = data["high"].to_numpy()
    lo = data["low"].to_numpy()
    c = data["close"].to_numpy()
    sig = data["signal"].to_numpy()
    atr = data["atr"].to_numpy()
    tb_long = data["trend_break_long"].to_numpy()
    tb_short = data["trend_break_short"].to_numpy()
    idx = data.index
    n = len(data)
    spr = bt.spread

    capital = bt.initial_capital
    pos = 0
    entry = sl = tp = size = risk = comm = 0.0
    entry_i = 0
    pending_entry: tuple[int, float] | None = None
    pending_exit = False
    trades: list[dict] = []
    equity = np.empty(n)

    def close_trade(i: int, price: float, reason: str) -> None:
        nonlocal capital, pos, pending_exit
        pnl = (price - entry) * pos * size - comm
        capital += pnl
        trades.append({
            "entry_time": idx[entry_i], "exit_time": idx[i],
            "side": "Long" if pos == 1 else "Short",
            "entry": round(entry, 5), "exit": round(price, 5),
            "stop_loss": round(sl, 5), "take_profit": round(tp, 5),
            "size": round(size, 0), "lots": round(size / bt.contract_size, 2),
            "risk": round(risk, 2), "commission": round(comm, 2),
            "pnl": round(pnl, 2), "r_multiple": round(pnl / risk, 2) if risk else 0.0,
            "reason": reason, "bars": i - entry_i,
        })
        pos = 0
        pending_exit = False

    for i in range(n):
        # 1) sortie « tendance » programmée -> exécutée à l'ouverture
        if pos != 0 and pending_exit:
            close_trade(i, o[i] if pos == 1 else o[i] + spr, "Tendance")

        # 2) entrée programmée -> exécutée à l'ouverture
        if pos == 0 and pending_entry is not None:
            side, dist = pending_entry
            pending_entry = None
            px = o[i] + spr if side == 1 else o[i]
            risk_amt = capital * bt.risk_per_trade
            units = risk_amt / dist
            units = min(units, capital * bt.max_leverage / px)
            if units > 0 and capital > 0:
                pos, entry, size, entry_i = side, px, units, i
                risk = units * dist
                comm = units / bt.contract_size * bt.commission_per_lot
                sl = px - side * dist
                tp = px + side * dist * strat.rr_ratio

        # 3) stop / objectif dans la bougie
        if pos == 1:
            if o[i] <= sl and i > entry_i:
                close_trade(i, o[i], "SL")
            elif lo[i] <= sl:
                close_trade(i, sl, "SL")
            elif o[i] >= tp and i > entry_i:
                close_trade(i, o[i], "TP")
            elif h[i] >= tp:
                close_trade(i, tp, "TP")
        elif pos == -1:
            ao, ah, al = o[i] + spr, h[i] + spr, lo[i] + spr
            if ao >= sl and i > entry_i:
                close_trade(i, ao, "SL")
            elif ah >= sl:
                close_trade(i, sl, "SL")
            elif ao <= tp and i > entry_i:
                close_trade(i, ao, "TP")
            elif al <= tp:
                close_trade(i, tp, "TP")

        # 4) décisions à la clôture
        if pos != 0 and strat.trend_exit:
            if (pos == 1 and tb_long[i]) or (pos == -1 and tb_short[i]):
                pending_exit = True
        if pos == 0 and sig[i] != 0 and i < n - 1:
            pending_entry = (int(sig[i]), float(atr[i]) * strat.stop_atr)

        # valorisation
        if pos == 1:
            equity[i] = capital + (c[i] - entry) * size
        elif pos == -1:
            equity[i] = capital + (entry - (c[i] + spr)) * size
        else:
            equity[i] = capital

    if pos != 0 and n:
        close_trade(n - 1, c[-1] if pos == 1 else c[-1] + spr, "Fin")
        equity[-1] = capital

    trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    equity_s = pd.Series(equity, index=idx, name="equity")
    result = BacktestResult(trades=trades_df, equity=equity_s, data=data)
    result.metrics = compute_metrics(trades_df, equity_s, bt.initial_capital)
    return result
