import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from lotusbot.backtest import run_backtest
from lotusbot.config import AppConfig, BacktestConfig, StrategyConfig
from lotusbot.data import _normalize, drop_unclosed_bar, synthetic
from lotusbot.indicators import atr, rsi
from lotusbot.strategy import add_signals, last_signal


@pytest.fixture(scope="module")
def df():
    return synthetic(5000, seed=3)


def test_rsi_bounds_and_wilder(df):
    r = rsi(df["close"], 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert rsi(up, 14).iloc[-1] == 100.0


def test_atr_positive(df):
    a = atr(df, 14).dropna()
    assert (a > 0).all()


def test_entries_at_next_bar_open(df):
    """Chaque trade entre à l'ouverture de la bougie qui SUIT le signal (pas d'anticipation)."""
    bt = BacktestConfig(spread=0.0, commission_per_lot=0.0)
    res = run_backtest(df, StrategyConfig(), bt)
    assert len(res.trades) > 10
    sig = res.data["signal"]
    for t in res.trades.itertuples():
        i = res.data.index.get_loc(t.entry_time)
        assert sig.iloc[i - 1] != 0, "l'entrée doit suivre une bougie signal"
        assert t.entry == pytest.approx(res.data["open"].iloc[i], abs=1e-5)


def test_no_lookahead_future_data_does_not_change_past(df):
    """Modifier le futur ne doit pas changer les trades déjà clôturés."""
    cut = 3500
    a = run_backtest(df.iloc[:cut])
    b = run_backtest(df)
    end = df.index[cut - 2]
    ta = a.trades[a.trades["exit_time"] < end].reset_index(drop=True)
    tb = b.trades[b.trades["exit_time"] < end].reset_index(drop=True)
    pd.testing.assert_frame_equal(ta, tb)


def test_risk_per_trade_respected(df):
    bt = BacktestConfig(spread=0.0, commission_per_lot=0.0, max_leverage=1000)
    res = run_backtest(df, StrategyConfig(), bt)
    sl = res.trades[res.trades["reason"] == "SL"]
    assert len(sl)
    # une perte au stop (sans gap) vaut ~ -1R
    assert (sl["r_multiple"] >= -1.6).all()
    assert sl["r_multiple"].median() == pytest.approx(-1.0, abs=0.05)


def test_take_profit_is_rr(df):
    bt = BacktestConfig(spread=0.0, commission_per_lot=0.0, max_leverage=1000)
    res = run_backtest(df, StrategyConfig(), bt)
    tp = res.trades[res.trades["reason"] == "TP"]
    assert len(tp)
    assert tp["r_multiple"].median() == pytest.approx(2.2, abs=0.05)


def test_costs_reduce_performance(df):
    free = run_backtest(df, StrategyConfig(), BacktestConfig(spread=0, commission_per_lot=0))
    paid = run_backtest(df, StrategyConfig(), BacktestConfig())
    assert paid.metrics["capital_final"] < free.metrics["capital_final"]


def test_equity_matches_trades(df):
    res = run_backtest(df)
    assert res.equity.iloc[-1] == pytest.approx(res.metrics["capital_initial"] + res.trades["pnl"].sum(), abs=0.05)


def test_session_filter(df):
    cfg = StrategyConfig(session_start_utc=7, session_end_utc=17)
    data = add_signals(df, cfg)
    hours = data.index[data["signal"] != 0].hour
    assert ((hours >= 7) & (hours < 17)).all()


def test_last_signal_levels(df):
    data = add_signals(df, StrategyConfig())
    i = int(np.flatnonzero(data["signal"].to_numpy() != 0)[-1])
    s = last_signal(df.iloc[: i + 1], StrategyConfig())
    assert s is not None and s.side in (1, -1)
    assert (s.take_profit - s.price) * s.side == pytest.approx(s.stop_distance * 2.2)


def test_normalize_multiindex():
    idx = pd.date_range("2025-01-01", periods=3, freq="h")
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close"], ["EURUSD=X"]])
    raw = pd.DataFrame([[1.1, 1.2, 1.0, 1.15]] * 3, index=idx, columns=cols)
    out = _normalize(raw)
    assert list(out.columns) == ["open", "high", "low", "close"]
    assert str(out.index.tz) == "UTC"


def test_drop_unclosed_bar():
    idx = pd.date_range("2025-01-01 10:00", periods=3, freq="h", tz="UTC")
    d = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1}, index=idx)
    now = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)
    assert len(drop_unclosed_bar(d, now=now)) == 2


def test_config_roundtrip(tmp_path):
    cfg = AppConfig()
    cfg.strategy.sma_fast = 9
    cfg.backtest.risk_per_trade = 0.01
    p = cfg.save(tmp_path / "c.json")
    back = AppConfig.load(p)
    assert back.strategy.sma_fast == 9 and back.backtest.risk_per_trade == 0.01
    json.loads(p.read_text())
