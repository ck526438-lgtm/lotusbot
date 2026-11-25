"""Application de bureau LotusBot (customtkinter + matplotlib)."""
from __future__ import annotations

import queue
import sys
import threading
from dataclasses import fields
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from .. import APP_NAME, __version__  # noqa: E402
from ..config import AppConfig, BacktestConfig, LiveConfig, StrategyConfig  # noqa: E402
from ..report import BG, LOTUS, draw_equity, save_report  # noqa: E402

ACCENT = LOTUS
ACCENT_HOVER = "#cf5a91"
CARD = "#171a21"
SIDEBAR = "#0b0d11"
GREEN = "#3ecf8e"
RED = "#ef5b5b"
MUTED = "#8b93a7"


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


FIELD_LABELS = {
    # stratégie
    "sma_fast": "SMA rapide", "sma_slow": "SMA lente", "sma_trend": "SMA tendance",
    "rsi_period": "Période RSI", "atr_period": "Période ATR", "rsi_min": "RSI min", "rsi_max": "RSI max",
    "stop_atr": "Stop (× ATR)", "rr_ratio": "Ratio gain/risque", "trend_exit": "Sortie sur cassure de tendance",
    "session_start_utc": "Début session (h UTC)", "session_end_utc": "Fin session (h UTC)",
    "allow_long": "Autoriser les achats", "allow_short": "Autoriser les ventes",
    # backtest
    "symbol": "Symbole Yahoo", "interval": "Unité de temps", "days": "Historique (jours)",
    "initial_capital": "Capital initial ($)", "risk_per_trade": "Risque par trade (0.008 = 0,8 %)",
    "spread": "Spread (prix)", "commission_per_lot": "Commission / lot ($)", "contract_size": "Taille de contrat",
    "max_leverage": "Levier max",
    # live
    "use_mt5": "Utiliser MetaTrader 5", "auto_trade": "Trading automatique", "mt5_symbol": "Symbole MT5",
    "mt5_login": "Login MT5", "mt5_password": "Mot de passe MT5", "mt5_server": "Serveur MT5",
    "mt5_path": "Chemin terminal64.exe (optionnel)", "magic": "Numéro magique", "max_lots": "Lots max",
    "scan_seconds": "Intervalle de scan (s)", "sound_alerts": "Alertes sonores",
}


def beep() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001
        pass


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str):
        super().__init__(master, fg_color=CARD, corner_radius=12)
        ctk.CTkLabel(self, text=title, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(size=22, weight="bold"))
        self.value.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, text: str, color: str | None = None) -> None:
        self.value.configure(text=text, text_color=color or "#e6e6e6")


# ============================================================ BACKTEST
class BacktestPage(ctk.CTkFrame):
    SOURCES = ["Yahoo Finance", "Fichier CSV", "MetaTrader 5", "Démo hors ligne"]

    def __init__(self, master, app: "LotusApp"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.result = None

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text="Backtest EURUSD H1", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        self.export_btn = ctk.CTkButton(bar, text="Exporter", width=110, fg_color="#2a2f3a", hover_color="#353b48",
                                        command=self.export, state="disabled")
        self.export_btn.pack(side="right", padx=(8, 0))
        self.run_btn = ctk.CTkButton(bar, text="▶  Lancer le backtest", width=180, fg_color=ACCENT,
                                     hover_color=ACCENT_HOVER, command=self.run)
        self.run_btn.pack(side="right", padx=(8, 0))
        self.source = ctk.CTkSegmentedButton(bar, values=self.SOURCES, selected_color=ACCENT,
                                             selected_hover_color=ACCENT_HOVER)
        self.source.set(self.SOURCES[0])
        self.source.pack(side="right")

        self.status = ctk.CTkLabel(self, text="Choisis une source de données puis lance le backtest.", text_color=MUTED, anchor="w")
        self.status.pack(fill="x", pady=(0, 8))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x")
        self.cards = {}
        specs = [("capital_final", "Capital final"), ("performance_pct", "Performance"),
                 ("max_drawdown_pct", "Drawdown max"), ("profit_factor", "Profit factor"),
                 ("nb_trades", "Trades"), ("taux_reussite_pct", "Taux de réussite"),
                 ("sharpe", "Sharpe"), ("esperance_R", "Espérance / trade")]
        for k, (key, title) in enumerate(specs):
            card = Card(grid, title)
            card.grid(row=k // 4, column=k % 4, sticky="nsew", padx=5, pady=5)
            grid.grid_columnconfigure(k % 4, weight=1)
            self.cards[key] = card

        self.tabs = ctk.CTkTabview(self, fg_color=CARD, segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER)
        self.tabs.pack(fill="both", expand=True, pady=(10, 0))
        for name in ("Graphique", "Trades", "Rapport"):
            self.tabs.add(name)

        self.fig = Figure(figsize=(9, 4.5), dpi=100, facecolor=BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tabs.tab("Graphique"))
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        cols = ("entry_time", "side", "entry", "exit", "lots", "pnl", "r_multiple", "reason", "bars")
        heads = ("Entrée", "Sens", "Prix entrée", "Prix sortie", "Lots", "P&L ($)", "R", "Sortie", "Durée (h)")
        frame = ctk.CTkFrame(self.tabs.tab("Trades"), fg_color="transparent")
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="Lotus.Treeview")
        for c, hd in zip(cols, heads):
            self.tree.heading(c, text=hd)
            self.tree.column(c, width=150 if c == "entry_time" else 90, anchor="center")
        sb = ctk.CTkScrollbar(frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("win", foreground=GREEN)
        self.tree.tag_configure("loss", foreground=RED)

        self.report = ctk.CTkTextbox(self.tabs.tab("Rapport"), font=ctk.CTkFont(family="Consolas", size=13))
        self.report.pack(fill="both", expand=True)

    # ---------------------------------------------------------------
    def run(self) -> None:
        src = self.source.get()
        csv_path = None
        if src == "Fichier CSV":
            csv_path = filedialog.askopenfilename(title="Fichier OHLC H1", filetypes=[("CSV", "*.csv"), ("Tous", "*.*")])
            if not csv_path:
                return
        self.run_btn.configure(state="disabled", text="Calcul en cours…")
        self.status.configure(text=f"Chargement des données ({src})…", text_color=MUTED)
        threading.Thread(target=self._worker, args=(src, csv_path), daemon=True).start()

    def _worker(self, src: str, csv_path: str | None) -> None:
        from .. import data

        cfg = self.app.cfg
        try:
            if src == "Fichier CSV":
                df = data.load_csv(csv_path)
            elif src == "MetaTrader 5":
                from .. import mt5_broker

                mt5_broker.connect(cfg.live)
                df = data.fetch_mt5(cfg.live.mt5_symbol, 12_000)
            elif src == "Démo hors ligne":
                df = data.synthetic()
            else:
                df = data.fetch_yahoo(cfg.backtest.symbol, cfg.backtest.days, cfg.backtest.interval)
            self.app.post(lambda: self.run_backtest_on(df, src))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.app.post(lambda: self._fail(msg))

    def _fail(self, msg: str) -> None:
        self.run_btn.configure(state="normal", text="▶  Lancer le backtest")
        self.status.configure(text=f"Erreur : {msg}", text_color=RED)

    def run_backtest_on(self, df, label: str) -> None:
        from ..backtest import run_backtest
        from ..metrics import format_report

        cfg = self.app.cfg
        try:
            res = run_backtest(df, cfg.strategy, cfg.backtest)
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc))
            return
        self.result = res
        m = res.metrics
        self.run_btn.configure(state="normal", text="▶  Lancer le backtest")
        self.export_btn.configure(state="normal")
        self.status.configure(
            text=f"{label} — {len(df)} bougies du {df.index[0]:%d/%m/%Y} au {df.index[-1]:%d/%m/%Y}",
            text_color=MUTED)

        perf = m["performance_pct"]
        self.cards["capital_final"].set(f"{m['capital_final']:,.2f} $".replace(",", " "))
        self.cards["performance_pct"].set(f"{perf:+.2f} %", GREEN if perf >= 0 else RED)
        self.cards["max_drawdown_pct"].set(f"{m['max_drawdown_pct']:.2f} %", RED)
        pf = m.get("profit_factor", 0)
        self.cards["profit_factor"].set("∞" if pf == float("inf") else f"{pf:.2f}", GREEN if pf >= 1 else RED)
        self.cards["nb_trades"].set(str(m["nb_trades"]))
        self.cards["taux_reussite_pct"].set(f"{m.get('taux_reussite_pct', 0):.1f} %")
        self.cards["sharpe"].set(f"{m['sharpe']:.2f}")
        er = m.get("esperance_R", 0)
        self.cards["esperance_R"].set(f"{er:+.2f} R", GREEN if er >= 0 else RED)

        draw_equity(self.fig, res)
        self.canvas.draw_idle()

        self.tree.delete(*self.tree.get_children())
        for t in res.trades.iloc[::-1].itertuples(index=False):
            self.tree.insert("", "end", tags=("win" if t.pnl > 0 else "loss",), values=(
                f"{t.entry_time:%d/%m/%Y %H:%M}", t.side, f"{t.entry:.5f}", f"{t.exit:.5f}",
                f"{t.lots:.2f}", f"{t.pnl:+.2f}", f"{t.r_multiple:+.2f}", t.reason, t.bars))

        self.report.delete("1.0", "end")
        self.report.insert("1.0", format_report(m))

    def export(self) -> None:
        if self.result is None:
            return
        folder = filedialog.askdirectory(title="Dossier d'export")
        if folder:
            files = save_report(self.result, folder)
            messagebox.showinfo(APP_NAME, "Exporté :\n" + "\n".join(str(p) for p in files.values()))


# ============================================================ LIVE
class LivePage(ctk.CTkFrame):
    def __init__(self, master, app: "LotusApp"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.scanner = None

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text="Signaux temps réel", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        self.stop_btn = ctk.CTkButton(bar, text="■  Arrêter", width=120, fg_color="#2a2f3a", hover_color="#353b48",
                                      command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=(8, 0))
        self.start_btn = ctk.CTkButton(bar, text="▶  Démarrer", width=140, fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, command=self.start)
        self.start_btn.pack(side="right")

        opts = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        opts.pack(fill="x")
        self.mt5_var = ctk.BooleanVar(value=app.cfg.live.use_mt5)
        self.auto_var = ctk.BooleanVar(value=app.cfg.live.auto_trade)
        ctk.CTkSwitch(opts, text="Données + ordres via MetaTrader 5", variable=self.mt5_var,
                      progress_color=ACCENT).pack(side="left", padx=14, pady=12)
        ctk.CTkSwitch(opts, text="Trading automatique (place les ordres)", variable=self.auto_var,
                      progress_color=ACCENT).pack(side="left", padx=14, pady=12)
        self.state_lbl = ctk.CTkLabel(opts, text="● Arrêté", text_color=MUTED)
        self.state_lbl.pack(side="right", padx=14)

        self.sig_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        self.sig_card.pack(fill="x", pady=10)
        ctk.CTkLabel(self.sig_card, text="Dernier signal", text_color=MUTED).pack(anchor="w", padx=14, pady=(10, 0))
        self.sig_lbl = ctk.CTkLabel(self.sig_card, text="Aucun signal pour l'instant",
                                    font=ctk.CTkFont(size=20, weight="bold"), anchor="w", justify="left")
        self.sig_lbl.pack(anchor="w", padx=14, pady=(0, 12))

        self.log = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12), fg_color=CARD)
        self.log.pack(fill="both", expand=True)
        self.write("Prêt. Le scanner analyse chaque bougie H1 clôturée et affiche les signaux LotusBot.")
        self.write("Sans MT5, les données viennent de Yahoo Finance (signaux uniquement, aucun ordre).")

    def write(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def start(self) -> None:
        from ..live import LiveScanner

        cfg = self.app.cfg
        cfg.live.use_mt5 = bool(self.mt5_var.get())
        cfg.live.auto_trade = bool(self.auto_var.get())
        if cfg.live.auto_trade and not cfg.live.use_mt5:
            messagebox.showwarning(APP_NAME, "Le trading automatique nécessite MetaTrader 5.")
            return
        if cfg.live.auto_trade and not messagebox.askyesno(
                APP_NAME, "Le bot va placer des ordres réels sur ton compte MT5.\n"
                          "Teste d'abord sur un compte DÉMO. Continuer ?"):
            return
        self.scanner = LiveScanner(cfg, on_log=lambda m: self.app.post(lambda: self.write(m)),
                                   on_signal=lambda s: self.app.post(lambda: self.show_signal(s)))
        self.scanner.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.state_lbl.configure(text="● En marche", text_color=GREEN)

    def stop(self) -> None:
        if self.scanner:
            self.scanner.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.state_lbl.configure(text="● Arrêté", text_color=MUTED)

    def show_signal(self, s) -> None:
        color = GREEN if s.side == 1 else RED
        self.sig_lbl.configure(
            text=f"{s.side_label} EURUSD — {s.time:%d/%m %H:%M} UTC\n"
                 f"Prix {s.price:.5f}   SL {s.stop_loss:.5f}   TP {s.take_profit:.5f}   RSI {s.rsi:.1f}",
            text_color=color)
        if self.app.cfg.live.sound_alerts:
            beep()
        try:
            self.app.bell()
            self.app.deiconify()
            self.app.lift()
        except Exception:  # noqa: BLE001
            pass


# ============================================================ PARAMÈTRES
class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app: "LotusApp"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bar, text="Paramètres", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(bar, text="Enregistrer", fg_color=ACCENT, hover_color=ACCENT_HOVER, width=130,
                      command=self.save).pack(side="right", padx=(8, 0))
        ctk.CTkButton(bar, text="Valeurs par défaut", fg_color="#2a2f3a", hover_color="#353b48", width=150,
                      command=self.reset).pack(side="right")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self.widgets: dict[tuple[str, str], object] = {}
        self.build()

    def build(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self.widgets.clear()
        cfg = self.app.cfg
        sections = [("strategy", "Stratégie", StrategyConfig, cfg.strategy),
                    ("backtest", "Backtest & gestion du risque", BacktestConfig, cfg.backtest),
                    ("live", "Temps réel & MetaTrader 5", LiveConfig, cfg.live)]
        for key, title, kls, obj in sections:
            box = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=12)
            box.pack(fill="x", pady=6)
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=15, weight="bold")).grid(
                row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 6))
            for k, f in enumerate(fields(kls)):
                r, c = 1 + k // 2, (k % 2) * 2
                ctk.CTkLabel(box, text=FIELD_LABELS.get(f.name, f.name), text_color=MUTED).grid(
                    row=r, column=c, sticky="w", padx=(14, 6), pady=4)
                val = getattr(obj, f.name)
                if isinstance(val, bool):
                    var = ctk.BooleanVar(value=val)
                    w = ctk.CTkSwitch(box, text="", variable=var, progress_color=ACCENT)
                    w.var = var
                else:
                    w = ctk.CTkEntry(box, width=200, show="•" if f.name == "mt5_password" else "")
                    w.insert(0, str(val))
                w.grid(row=r, column=c + 1, sticky="w", padx=(0, 20), pady=4)
                self.widgets[(key, f.name)] = w
            box.grid_columnconfigure((1, 3), weight=1)
            ctk.CTkLabel(box, text="").grid(row=99, column=0, pady=2)

    def save(self) -> None:
        cfg = self.app.cfg
        try:
            for (section, name), w in self.widgets.items():
                obj = getattr(cfg, section)
                cur = getattr(obj, name)
                if isinstance(cur, bool):
                    setattr(obj, name, bool(w.var.get()))
                else:
                    setattr(obj, name, type(cur)(w.get().strip().replace(",", ".") if not isinstance(cur, str) else w.get()))
        except ValueError as exc:
            messagebox.showerror(APP_NAME, f"Valeur invalide : {exc}")
            return
        path = cfg.save()
        self.app.pages["live"].mt5_var.set(cfg.live.use_mt5)
        self.app.pages["live"].auto_var.set(cfg.live.auto_trade)
        messagebox.showinfo(APP_NAME, f"Paramètres enregistrés :\n{path}")

    def reset(self) -> None:
        if messagebox.askyesno(APP_NAME, "Revenir aux paramètres par défaut ?"):
            self.app.cfg = AppConfig()
            self.build()


# ============================================================ APP
class LotusApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.cfg = AppConfig.load()
        self._q: queue.Queue = queue.Queue()
        self.title(f"{APP_NAME} {__version__} — EURUSD H1")
        self.geometry("1320x840")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        ico = resource_path("assets/lotus.ico")
        if ico.exists() and sys.platform.startswith("win"):
            try:
                self.iconbitmap(str(ico))
            except Exception:  # noqa: BLE001
                pass
        self._style_tree()

        side = ctk.CTkFrame(self, width=220, fg_color=SIDEBAR, corner_radius=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        png = resource_path("assets/lotus.png")
        if png.exists():
            from PIL import Image

            img = ctk.CTkImage(Image.open(png), size=(72, 72))
            ctk.CTkLabel(side, image=img, text="").pack(pady=(26, 4))
        ctk.CTkLabel(side, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold"), text_color=ACCENT).pack()
        ctk.CTkLabel(side, text=f"EURUSD H1 · v{__version__}", text_color=MUTED).pack(pady=(0, 24))

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.pack(side="left", fill="both", expand=True, padx=22, pady=20)
        self.pages = {
            "backtest": BacktestPage(self.main, self),
            "live": LivePage(self.main, self),
            "settings": SettingsPage(self.main, self),
        }
        self.nav = {}
        for key, label in (("backtest", "📊  Backtest"), ("live", "⚡  Signaux live"), ("settings", "⚙  Paramètres")):
            b = ctk.CTkButton(side, text=label, anchor="w", height=40, corner_radius=8, fg_color="transparent",
                              hover_color="#1c2029", font=ctk.CTkFont(size=14), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=14, pady=3)
            self.nav[key] = b
        ctk.CTkLabel(side, text="Le trading comporte un risque\nde perte en capital.\nTeste d'abord en démo.",
                     text_color="#5b6273", font=ctk.CTkFont(size=11), justify="center").pack(side="bottom", pady=18)

        self.show("backtest")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)

    def _style_tree(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Lotus.Treeview", background=CARD, fieldbackground=CARD, foreground="#e6e6e6",
                     rowheight=26, borderwidth=0, font=("Segoe UI", 10))
        st.configure("Lotus.Treeview.Heading", background="#20242d", foreground=MUTED, relief="flat",
                     font=("Segoe UI", 10, "bold"))
        st.map("Lotus.Treeview", background=[("selected", "#2c3140")])

    def show(self, key: str) -> None:
        for k, p in self.pages.items():
            p.pack_forget()
            self.nav[k].configure(fg_color="transparent", text_color="#c9cfdc")
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].configure(fg_color="#1c2029", text_color=ACCENT)

    def post(self, fn) -> None:
        """Exécute fn sur le thread de l'interface (appelable depuis n'importe quel thread)."""
        self._q.put(fn)

    def _poll(self) -> None:
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def run_backtest_on(self, df, label: str) -> None:
        self.show("backtest")
        self.pages["backtest"].run_backtest_on(df, label)

    def on_close(self) -> None:
        live = self.pages["live"]
        if live.scanner and live.scanner.running:
            live.scanner.stop()
        self.destroy()


def run() -> None:
    app = LotusApp()
    app.mainloop()
