"""Configuration de LotusBot (stratégie, backtest, live) — sérialisable en JSON."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class StrategyConfig:
    sma_fast: int = 12
    sma_slow: int = 36
    sma_trend: int = 100
    rsi_period: int = 14
    atr_period: int = 14
    rsi_min: float = 35.0
    rsi_max: float = 65.0
    stop_atr: float = 1.8
    rr_ratio: float = 2.2
    trend_exit: bool = True          # sortie si la clôture repasse de l'autre côté de la SMA tendance
    session_start_utc: int = 0       # heures de trading autorisées pour les ENTRÉES (UTC)
    session_end_utc: int = 24
    allow_long: bool = True
    allow_short: bool = True


@dataclass
class BacktestConfig:
    symbol: str = "EURUSD=X"         # symbole Yahoo Finance
    interval: str = "1h"
    days: int = 700                  # yfinance limite le H1 à ~730 jours
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.008    # 0,8 % du capital par trade
    spread: float = 0.00008          # 0,8 pip payé à l'entrée
    commission_per_lot: float = 7.0  # $ aller-retour par lot standard (100 000)
    contract_size: float = 100_000.0
    max_leverage: float = 30.0       # plafond de taille : notionnel <= capital * levier


@dataclass
class LiveConfig:
    use_mt5: bool = False            # données + exécution via MetaTrader 5 (Windows)
    auto_trade: bool = False         # placer les ordres automatiquement (MT5 requis)
    mt5_symbol: str = "EURUSD"
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""
    magic: int = 52626
    max_lots: float = 5.0
    scan_seconds: int = 60
    sound_alerts: bool = True


@dataclass
class AppConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    live: LiveConfig = field(default_factory=LiveConfig)

    # ---------- persistance ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        def build(kls, values):
            names = {f.name: f.type for f in fields(kls)}
            obj = kls()
            for key, value in (values or {}).items():
                if key in names:
                    default = getattr(obj, key)
                    try:
                        value = type(default)(value) if not isinstance(default, bool) else bool(value)
                    except (TypeError, ValueError):
                        value = default
                    setattr(obj, key, value)
            return obj

        return cls(
            strategy=build(StrategyConfig, data.get("strategy")),
            backtest=build(BacktestConfig, data.get("backtest")),
            live=build(LiveConfig, data.get("live")),
        )

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or default_config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = Path(path or default_config_path())
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return cls()


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "LotusBot"


def default_config_path() -> Path:
    return app_dir() / "config.json"
