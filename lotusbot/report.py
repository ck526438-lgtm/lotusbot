"""Graphiques et exports."""
from __future__ import annotations

from pathlib import Path

import matplotlib

from .backtest import BacktestResult
from .metrics import format_report

BG = "#0f1115"
PANEL = "#171a21"
FG = "#e6e6e6"
MUTED = "#8b93a7"
LOTUS = "#e86fa8"
GREEN = "#3ecf8e"
RED = "#ef5b5b"


def draw_equity(fig, result: BacktestResult) -> None:
    """Dessine capital + drawdown dans une Figure matplotlib existante."""
    fig.clear()
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(3, 1, hspace=0.08)
    ax = fig.add_subplot(gs[:2, 0])
    ax_dd = fig.add_subplot(gs[2, 0], sharex=ax)
    eq = result.equity
    for a in (ax, ax_dd):
        a.set_facecolor(PANEL)
        a.tick_params(colors=MUTED, labelsize=8)
        for s in a.spines.values():
            s.set_color("#2a2f3a")
        a.grid(color="#262b35", linewidth=0.6)

    ax.plot(eq.index, eq.values, color=LOTUS, linewidth=1.4)
    ax.axhline(eq.iloc[0], color=MUTED, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Capital ($)", color=MUTED, fontsize=9)
    ax.set_title("Courbe de capital — LotusBot EURUSD H1", color=FG, fontsize=11, loc="left")
    t = result.trades
    if len(t):
        ex = eq.reindex(t["exit_time"])
        win = t["pnl"].to_numpy() > 0
        ax.scatter(t["exit_time"][win], ex.values[win], s=9, color=GREEN, zorder=3)
        ax.scatter(t["exit_time"][~win], ex.values[~win], s=9, color=RED, zorder=3)
    plt_dd = (eq / eq.cummax() - 1) * 100
    ax_dd.fill_between(plt_dd.index, plt_dd.values, 0, color=RED, alpha=0.35, linewidth=0)
    ax_dd.set_ylabel("Drawdown (%)", color=MUTED, fontsize=9)
    ax.tick_params(labelbottom=False)
    fig.autofmt_xdate()


def save_report(result: BacktestResult, folder: str | Path) -> dict:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    matplotlib.use("Agg", force=False)
    from matplotlib.figure import Figure

    fig = Figure(figsize=(11, 6), dpi=110)
    draw_equity(fig, result)
    png = folder / "lotusbot_equity.png"
    fig.savefig(png, facecolor=BG)
    trades = folder / "lotusbot_trades.csv"
    result.trades.to_csv(trades, index=False)
    txt = folder / "lotusbot_rapport.txt"
    txt.write_text(format_report(result.metrics), encoding="utf-8")
    return {"chart": png, "trades": trades, "report": txt}
