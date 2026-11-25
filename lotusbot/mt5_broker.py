"""Connexion MetaTrader 5 (Windows) : données H1, calcul des lots et passage d'ordres.

Le paquet MetaTrader5 n'existe que sous Windows avec le terminal MT5 installé.
Teste TOUJOURS d'abord sur un compte démo.
"""
from __future__ import annotations

import math

import pandas as pd

from .config import LiveConfig
from .strategy import Signal

try:  # pragma: no cover - dépend de la plateforme
    import MetaTrader5 as mt5
except Exception:  # noqa: BLE001
    mt5 = None


class BrokerError(RuntimeError):
    pass


def available() -> bool:
    return mt5 is not None


def _require():
    if mt5 is None:
        raise BrokerError("MetaTrader5 indisponible : installe MT5 et le paquet « MetaTrader5 » (Windows uniquement).")


def connect(cfg: LiveConfig) -> str:
    _require()
    kwargs = {}
    if cfg.mt5_path:
        kwargs["path"] = cfg.mt5_path
    if cfg.mt5_login:
        kwargs.update(login=int(cfg.mt5_login), password=cfg.mt5_password, server=cfg.mt5_server)
    if not mt5.initialize(**kwargs):
        raise BrokerError(f"Connexion MT5 impossible : {mt5.last_error()}")
    if not mt5.symbol_select(cfg.mt5_symbol, True):
        raise BrokerError(f"Symbole {cfg.mt5_symbol} introuvable chez le courtier.")
    info = mt5.account_info()
    if info is None:
        raise BrokerError("Aucun compte MT5 connecté.")
    kind = "DÉMO" if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "RÉEL"
    return f"MT5 connecté — compte {info.login} ({kind}) — {info.server} — solde {info.balance:.2f} {info.currency}"


def shutdown() -> None:
    if mt5 is not None:
        mt5.shutdown()


def balance() -> float:
    _require()
    info = mt5.account_info()
    return float(info.equity) if info else 0.0


def get_rates_h1(symbol: str, bars: int = 5000) -> pd.DataFrame:
    _require()
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    if rates is None or len(rates) == 0:
        raise BrokerError(f"Pas de données H1 pour {symbol} : {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def compute_lots(symbol: str, risk_money: float, stop_distance: float, max_lots: float) -> float:
    _require()
    info = mt5.symbol_info(symbol)
    if info is None:
        raise BrokerError(f"Infos symbole {symbol} indisponibles.")
    tick_value = info.trade_tick_value or 1.0
    tick_size = info.trade_tick_size or info.point
    loss_per_lot = stop_distance / tick_size * tick_value
    if loss_per_lot <= 0:
        return 0.0
    lots = risk_money / loss_per_lot
    step = info.volume_step or 0.01
    lots = math.floor(lots / step) * step
    lots = min(lots, max_lots, info.volume_max)
    return round(lots, 2) if lots >= info.volume_min else 0.0


def open_positions(cfg: LiveConfig) -> list:
    _require()
    pos = mt5.positions_get(symbol=cfg.mt5_symbol) or ()
    return [p for p in pos if p.magic == cfg.magic]


def place_order(signal: Signal, cfg: LiveConfig, risk_per_trade: float, rr_ratio: float) -> str:
    """Ordre au marché ; SL/TP recalculés à partir du prix d'exécution réel."""
    _require()
    if open_positions(cfg):
        return "Position LotusBot déjà ouverte — signal ignoré."
    tick = mt5.symbol_info_tick(cfg.mt5_symbol)
    info = mt5.symbol_info(cfg.mt5_symbol)
    if tick is None or info is None:
        raise BrokerError("Prix indisponible.")
    buy = signal.side == 1
    price = tick.ask if buy else tick.bid
    dist = signal.stop_distance
    sl = price - dist if buy else price + dist
    tp = price + dist * rr_ratio if buy else price - dist * rr_ratio
    lots = compute_lots(cfg.mt5_symbol, balance() * risk_per_trade, dist, cfg.max_lots)
    if lots <= 0:
        return "Lot calculé trop petit pour le risque choisi — ordre non envoyé."
    digits = info.digits
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": cfg.mt5_symbol,
        "volume": lots,
        "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": round(sl, digits),
        "tp": round(tp, digits),
        "deviation": 10,
        "magic": cfg.magic,
        "comment": "LotusBot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling(info),
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        code = getattr(res, "retcode", None)
        raise BrokerError(f"Ordre refusé (code {code}) : {getattr(res, 'comment', mt5.last_error())}")
    return f"{signal.side_label} {lots} lot(s) {cfg.mt5_symbol} @ {res.price:.5f} — SL {sl:.5f} — TP {tp:.5f}"


def close_all(cfg: LiveConfig, reason: str = "Tendance") -> list[str]:
    _require()
    msgs = []
    for p in open_positions(cfg):
        tick = mt5.symbol_info_tick(p.symbol)
        info = mt5.symbol_info(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": p.ticket,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 10,
            "magic": cfg.magic,
            "comment": f"LotusBot {reason}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling(info),
        }
        res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        msgs.append(f"Clôture #{p.ticket} ({reason}) : {'OK' if ok else 'ÉCHEC ' + str(getattr(res, 'comment', ''))}")
    return msgs


def _filling(info) -> int:
    modes = getattr(info, "filling_mode", 0)
    if modes & 1:
        return mt5.ORDER_FILLING_FOK
    if modes & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN
