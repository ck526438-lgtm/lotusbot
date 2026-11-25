"""Stratégie LotusBot : croisement SMA rapide/lente dans le sens de la SMA tendance, filtré par le RSI.

Tous les signaux sont calculés sur des bougies CLÔTURÉES. Un signal sur la bougie i
s'exécute à l'ouverture de la bougie i+1 (aucun biais d'anticipation).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import StrategyConfig
from .indicators import atr, rsi, sma


def add_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = sma(out["close"], cfg.sma_fast)
    out["sma_slow"] = sma(out["close"], cfg.sma_slow)
    out["sma_trend"] = sma(out["close"], cfg.sma_trend)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    return out


def add_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """Ajoute les colonnes signal (+1 achat, -1 vente, 0 rien) et trend_break_long/short."""
    out = df if "sma_fast" in df else add_indicators(df, cfg)
    fast, slow, trend, close = out["sma_fast"], out["sma_slow"], out["sma_trend"], out["close"]

    cross_up = (fast.shift() <= slow.shift()) & (fast > slow)
    cross_down = (fast.shift() >= slow.shift()) & (fast < slow)
    rsi_ok = out["rsi"].between(cfg.rsi_min, cfg.rsi_max, inclusive="neither")

    hours = pd.DatetimeIndex(out.index).hour
    if cfg.session_start_utc <= cfg.session_end_utc:
        in_session = (hours >= cfg.session_start_utc) & (hours < cfg.session_end_utc)
    else:  # session qui passe minuit
        in_session = (hours >= cfg.session_start_utc) | (hours < cfg.session_end_utc)
    in_session = pd.Series(in_session, index=out.index)

    ready = out[["sma_fast", "sma_slow", "sma_trend", "rsi", "atr"]].notna().all(axis=1) & (out["atr"] > 0)

    long_sig = cross_up & (close > trend) & rsi_ok & in_session & ready & cfg.allow_long
    short_sig = cross_down & (close < trend) & rsi_ok & in_session & ready & cfg.allow_short

    out["signal"] = 0
    out.loc[long_sig, "signal"] = 1
    out.loc[short_sig, "signal"] = -1
    out["trend_break_long"] = close < trend
    out["trend_break_short"] = close > trend
    return out


@dataclass
class Signal:
    time: pd.Timestamp
    side: int                 # +1 achat, -1 vente
    price: float              # clôture de la bougie signal (entrée estimée à l'ouverture suivante)
    stop_distance: float
    stop_loss: float
    take_profit: float
    rsi: float
    atr: float

    @property
    def side_label(self) -> str:
        return "ACHAT" if self.side == 1 else "VENTE"


def last_signal(df: pd.DataFrame, cfg: StrategyConfig) -> Signal | None:
    """Signal sur la DERNIÈRE bougie clôturée de df (df ne doit pas contenir la bougie en cours)."""
    data = add_signals(df, cfg)
    if data.empty:
        return None
    row = data.iloc[-1]
    if row["signal"] == 0:
        return None
    side = int(row["signal"])
    dist = float(row["atr"]) * cfg.stop_atr
    price = float(row["close"])
    return Signal(
        time=data.index[-1],
        side=side,
        price=price,
        stop_distance=dist,
        stop_loss=price - side * dist,
        take_profit=price + side * dist * cfg.rr_ratio,
        rsi=float(row["rsi"]),
        atr=float(row["atr"]),
    )
