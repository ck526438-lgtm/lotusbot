"""Statistiques de performance."""
from __future__ import annotations

import numpy as np
import pandas as pd

BARS_PER_YEAR_H1 = 24 * 5 * 52  # le forex cote ~24 h/24, 5 j/7


def _streak(wins: np.ndarray, value: bool) -> int:
    best = cur = 0
    for w in wins:
        cur = cur + 1 if w == value else 0
        best = max(best, cur)
    return best


def compute_metrics(trades: pd.DataFrame, equity: pd.Series, initial_capital: float) -> dict:
    final = float(equity.iloc[-1]) if len(equity) else initial_capital
    m: dict = {
        "capital_initial": initial_capital,
        "capital_final": round(final, 2),
        "performance_pct": round((final / initial_capital - 1) * 100, 2),
        "nb_trades": int(len(trades)),
    }

    if len(equity) > 1:
        peak = equity.cummax()
        dd = equity / peak - 1
        m["max_drawdown_pct"] = round(float(dd.min()) * 100, 2)
        rets = equity.pct_change().dropna()
        std = rets.std()
        m["sharpe"] = round(float(rets.mean() / std * np.sqrt(BARS_PER_YEAR_H1)), 2) if std > 0 else 0.0
        years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
        m["cagr_pct"] = round(((final / initial_capital) ** (1 / years) - 1) * 100, 2) if years > 0.05 and final > 0 else m["performance_pct"]
        m["calmar"] = round(m["cagr_pct"] / abs(m["max_drawdown_pct"]), 2) if m["max_drawdown_pct"] < 0 else 0.0
    else:
        m.update(max_drawdown_pct=0.0, sharpe=0.0, cagr_pct=0.0, calmar=0.0)

    if len(trades):
        pnl = trades["pnl"].to_numpy()
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        gross_win, gross_loss = wins.sum(), -losses.sum()
        m["taux_reussite_pct"] = round(len(wins) / len(pnl) * 100, 1)
        m["profit_factor"] = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")
        m["gain_moyen"] = round(float(wins.mean()), 2) if len(wins) else 0.0
        m["perte_moyenne"] = round(float(losses.mean()), 2) if len(losses) else 0.0
        m["esperance_R"] = round(float(trades["r_multiple"].mean()), 3)
        m["meilleur_trade"] = round(float(pnl.max()), 2)
        m["pire_trade"] = round(float(pnl.min()), 2)
        m["pertes_consecutives_max"] = _streak(pnl > 0, False)
        m["gains_consecutifs_max"] = _streak(pnl > 0, True)
        m["duree_moyenne_h"] = round(float(trades["bars"].mean()), 1)
        m["longs"] = int((trades["side"] == "Long").sum())
        m["shorts"] = int((trades["side"] == "Short").sum())
        m["commissions"] = round(float(trades["commission"].sum()), 2)
        m["sorties"] = trades["reason"].value_counts().to_dict()
    else:
        m.update(taux_reussite_pct=0.0, profit_factor=0.0, esperance_R=0.0)
    return m


LABELS = {
    "capital_final": "Capital final ($)",
    "performance_pct": "Performance (%)",
    "cagr_pct": "Rendement annualisé (%)",
    "max_drawdown_pct": "Drawdown max (%)",
    "sharpe": "Ratio de Sharpe",
    "calmar": "Ratio de Calmar",
    "nb_trades": "Nombre de trades",
    "taux_reussite_pct": "Taux de réussite (%)",
    "profit_factor": "Profit factor",
    "esperance_R": "Espérance (R / trade)",
    "gain_moyen": "Gain moyen ($)",
    "perte_moyenne": "Perte moyenne ($)",
    "meilleur_trade": "Meilleur trade ($)",
    "pire_trade": "Pire trade ($)",
    "pertes_consecutives_max": "Pertes consécutives max",
    "duree_moyenne_h": "Durée moyenne (h)",
    "commissions": "Commissions ($)",
}


def format_report(m: dict) -> str:
    lines = ["=" * 50, "RÉSULTATS — LOTUSBOT EURUSD H1", "=" * 50]
    for key, label in LABELS.items():
        if key in m:
            lines.append(f"{label:<28}: {m[key]}")
    if m.get("sorties"):
        lines.append(f"{'Sorties':<28}: " + ", ".join(f"{k} {v}" for k, v in m["sorties"].items()))
    return "\n".join(lines)
