"""Scanner temps réel : surveille chaque nouvelle bougie H1 clôturée et émet les signaux."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from . import mt5_broker
from .config import AppConfig
from .data import drop_unclosed_bar, fetch_yahoo
from .strategy import Signal, add_signals, last_signal


@dataclass
class ScanResult:
    bar_time: pd.Timestamp
    close: float
    rsi: float
    trend: str
    signal: Signal | None
    trend_break: dict


def scan_once(cfg: AppConfig) -> ScanResult:
    if cfg.live.use_mt5:
        df = mt5_broker.get_rates_h1(cfg.live.mt5_symbol, 600)
    else:
        df = fetch_yahoo(cfg.backtest.symbol, days=40, interval="1h")
    df = drop_unclosed_bar(df)
    data = add_signals(df, cfg.strategy)
    row = data.iloc[-1]
    return ScanResult(
        bar_time=data.index[-1],
        close=float(row["close"]),
        rsi=float(row["rsi"]),
        trend="HAUSSIÈRE" if row["close"] > row["sma_trend"] else "BAISSIÈRE",
        signal=last_signal(df, cfg.strategy),
        trend_break={"long": bool(row["trend_break_long"]), "short": bool(row["trend_break_short"])},
    )


class LiveScanner:
    """Boucle en arrière-plan. `on_log(msg)` et `on_signal(signal)` sont appelés depuis le thread."""

    def __init__(self, cfg: AppConfig, on_log: Callable[[str], None], on_signal: Callable[[Signal], None] | None = None):
        self.cfg = cfg
        self.on_log = on_log
        self.on_signal = on_signal or (lambda s: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_bar: pd.Timestamp | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="LotusScanner")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _log(self, msg: str) -> None:
        self.on_log(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}")

    def _loop(self) -> None:
        live = self.cfg.live
        if live.use_mt5:
            try:
                self._log(mt5_broker.connect(live))
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERREUR MT5 : {exc}")
                return
        self._log("Scanner démarré — analyse de chaque bougie H1 clôturée.")
        while not self._stop.is_set():
            try:
                res = scan_once(self.cfg)
                if res.bar_time != self._last_bar:
                    self._last_bar = res.bar_time
                    self._handle(res)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Erreur de scan : {exc}")
            self._stop.wait(max(15, live.scan_seconds))
        self._log("Scanner arrêté.")
        if live.use_mt5:
            mt5_broker.shutdown()

    def _handle(self, res: ScanResult) -> None:
        live = self.cfg.live
        self._log(f"Bougie {res.bar_time:%d/%m %H:%M} — clôture {res.close:.5f} — RSI {res.rsi:.1f} — tendance {res.trend}")

        if live.use_mt5 and live.auto_trade and self.cfg.strategy.trend_exit:
            for p in mt5_broker.open_positions(live):
                is_buy = p.type == 0
                if (is_buy and res.trend_break["long"]) or (not is_buy and res.trend_break["short"]):
                    for m in mt5_broker.close_all(live, "Tendance"):
                        self._log(m)
                    break

        sig = res.signal
        if sig is None:
            return
        self._log(
            f"SIGNAL {sig.side_label} — prix {sig.price:.5f} — SL {sig.stop_loss:.5f} — TP {sig.take_profit:.5f} "
            f"— stop {sig.stop_distance * 10000:.1f} pips"
        )
        self.on_signal(sig)
        if live.use_mt5 and live.auto_trade:
            try:
                self._log(mt5_broker.place_order(sig, live, self.cfg.backtest.risk_per_trade, self.cfg.strategy.rr_ratio))
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERREUR ORDRE : {exc}")


def wait_forever(scanner: LiveScanner) -> None:  # utilisé par la CLI
    scanner.start()
    try:
        while scanner.running:
            time.sleep(1)
    except KeyboardInterrupt:
        scanner.stop()
