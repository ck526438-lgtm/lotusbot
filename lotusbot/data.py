"""Chargement des données OHLC : Yahoo Finance, MetaTrader 5 ou CSV."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]


class DataError(RuntimeError):
    pass


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance >= 0.2.48 renvoie (Price, Ticker)
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    missing = [c for c in OHLC if c not in df.columns]
    if missing:
        raise DataError(f"Colonnes manquantes : {missing}")
    df = df[OHLC].astype(float).dropna()
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # barres invalides (high < low, prix nuls) écartées
    df = df[(df["high"] >= df["low"]) & (df[OHLC] > 0).all(axis=1)]
    return df


def drop_unclosed_bar(df: pd.DataFrame, bar: timedelta = timedelta(hours=1), now: datetime | None = None) -> pd.DataFrame:
    """Retire la dernière bougie si elle n'est pas encore clôturée."""
    if df.empty:
        return df
    now = now or datetime.now(timezone.utc)
    last_open = df.index[-1].to_pydatetime()
    if last_open + bar > now:
        return df.iloc[:-1]
    return df


def fetch_yahoo(symbol: str = "EURUSD=X", days: int = 700, interval: str = "1h") -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise DataError("Le paquet yfinance n'est pas installé.") from exc

    if interval in ("1h", "60m"):
        days = min(days, 729)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    df = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df is None or df.empty:
        raise DataError(
            f"Aucune donnée reçue de Yahoo Finance pour {symbol} ({interval}). "
            "Vérifie ta connexion Internet ou réessaie dans quelques minutes."
        )
    return _normalize(df)


def fetch_mt5(symbol: str = "EURUSD", bars: int = 5000) -> pd.DataFrame:
    from . import mt5_broker

    return mt5_broker.get_rates_h1(symbol, bars)


def load_csv(path: str | Path) -> pd.DataFrame:
    """CSV avec une colonne date/time + open, high, low, close (export MT5 accepté)."""
    raw = pd.read_csv(path, sep=None, engine="python")
    raw.columns = [str(c).strip("<> ").lower() for c in raw.columns]
    if "date" in raw.columns and "time" in raw.columns:
        ts = pd.to_datetime(raw["date"].astype(str) + " " + raw["time"].astype(str))
    else:
        col = next((c for c in raw.columns if c in ("datetime", "date", "time", "timestamp")), raw.columns[0])
        ts = pd.to_datetime(raw[col])
    raw.index = ts
    return _normalize(raw)


def synthetic(n: int = 4000, seed: int = 7, start: str = "2024-01-01") -> pd.DataFrame:
    """Série EURUSD H1 synthétique (marche aléatoire à régimes) — tests et autotest de l'appli."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.00012, n // 200 + 1), 200)[:n]
    rets = drift + rng.normal(0, 0.0011, n)
    close = 1.08 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, 0.0006, n)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0006, n)) * close
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
