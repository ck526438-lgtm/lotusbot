<p align="center">
  <img src="assets/lotus.png" width="110" alt="LotusBot">
</p>

<h1 align="center">LotusBot</h1>
<p align="center"><b>Bot de trading EURUSD H1</b> — backtest réaliste, signaux temps réel et exécution MetaTrader 5, dans une appli Windows.</p>

<p align="center">
  <a href="../../releases/latest"><b>⬇ Télécharger LotusBot.exe</b></a>
</p>

---

## Fonctionnalités

| | |
|---|---|
| 📊 **Backtest** | Données Yahoo Finance (≈ 2 ans en H1), MetaTrader 5, CSV (export MT5 accepté) ou démo hors ligne |
| 📈 **Rapport pro** | Capital, performance, drawdown max, Sharpe, Calmar, profit factor, espérance en R, séries de pertes, courbe de capital + drawdown, journal des trades, export PNG/CSV/TXT |
| ⚡ **Signaux live** | Analyse chaque bougie H1 clôturée, alerte sonore, niveaux SL/TP calculés |
| 🤖 **Trading auto (MT5)** | Ordres au marché avec SL/TP, taille de lot selon le risque, sortie sur cassure de tendance, numéro magique |
| ⚙ **Paramètres** | Tous les réglages modifiables dans l'appli et sauvegardés (`%APPDATA%\LotusBot\config.json`) |

## La stratégie

- **Entrée achat** : la SMA 12 croise au-dessus de la SMA 36, la clôture est au-dessus de la SMA 100, RSI(14) entre 35 et 65.
- **Entrée vente** : symétrique.
- **Stop** : 1,8 × ATR(14). **Objectif** : 2,2 × le stop.
- **Sortie anticipée** : la clôture repasse de l'autre côté de la SMA 100.
- **Risque** : 0,8 % du capital par trade, plafonné par un levier maximal.
- **Filtre horaire** optionnel (par ex. 7 h – 17 h UTC pour Londres/New York).

## Résultats réels (backtest EURUSD H1, déc. 2024 → nov. 2026, paramètres par défaut)

| Performance | Drawdown max | Trades | Réussite | Profit factor | Espérance |
|---|---|---|---|---|---|
| +3,2 % | −10,2 % | 126 | 30 % | 1,05 | +0,04 R |

Coûts inclus (spread + 378 $ de commissions). La stratégie est **à peine rentable** dans sa version d'origine : elle sert de base à optimiser (filtre horaire, ratio, stop) — à valider hors échantillon avant tout usage réel. Le rapport complet et la courbe sont joints à chaque release.

## Ce qui a été corrigé par rapport au script d'origine

1. **Biais d'anticipation** : le script lisait la clôture d'une bougie puis entrait à *l'ouverture de cette même bougie*. LotusBot entre à l'ouverture de la bougie **suivante**.
2. **Sortie tendance** : décidée à la clôture, exécutée à l'ouverture suivante (et non au prix d'ouverture déjà passé).
3. **Coûts** : spread (0,8 pip) et commission (7 $/lot) inclus.
4. **Gaps** : si le prix ouvre au-delà du SL/TP, la sortie se fait au prix d'ouverture.
5. **SL et TP dans la même bougie** : le SL est retenu (hypothèse prudente).
6. **RSI et ATR de Wilder** (identiques à MT5/TradingView) au lieu de moyennes simples.
7. **yfinance récent** : gestion des colonnes MultiIndex.
8. **Courbe de capital** valorisée à chaque bougie (P&L latent inclus), donc drawdown réel.

Les tests (`tests/`) vérifient notamment qu'aucune donnée future n'influence les trades passés.

## Utilisation

### Appli Windows
Télécharge `LotusBot.exe` dans les [Releases](../../releases/latest) et lance-le. Aucune installation de Python n'est nécessaire.
> Windows SmartScreen peut afficher un avertissement (exe non signé) : « Informations complémentaires » → « Exécuter quand même ».

Pour le trading automatique : installe MetaTrader 5, connecte-toi à ton compte (**démo d'abord**), active *Algo Trading*, puis dans LotusBot : *Signaux live* → *MetaTrader 5* + *Trading automatique*.

### Depuis le code
```bash
pip install -r requirements.txt
python -m lotusbot                     # appli de bureau
python -m lotusbot backtest --out report
python -m lotusbot backtest --csv EURUSD_H1.csv
python -m lotusbot scan                # signaux dans le terminal
python -m lotusbot scan --mt5 --auto   # trading automatique MT5 (Windows)
pytest -q
```

### Construire l'exe soi-même
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name LotusBot --icon assets/lotus.ico ^
  --add-data "assets;assets" --collect-data customtkinter --hidden-import MetaTrader5 run_lotusbot.py
```
La GitHub Action `Build Windows .exe` le fait automatiquement à chaque push et publie l'exe à chaque tag `v*`.

## Structure

```
lotusbot/
  config.py       paramètres (JSON)
  data.py         Yahoo / MT5 / CSV / synthétique
  indicators.py   SMA, RSI, ATR (Wilder)
  strategy.py     signaux sur bougies clôturées
  backtest.py     moteur événementiel (spread, commission, gaps)
  metrics.py      statistiques
  live.py         scanner temps réel
  mt5_broker.py   connexion et ordres MetaTrader 5
  report.py       graphiques et exports
  gui/app.py      appli de bureau
```

## Avertissement

Ce logiciel est fourni à titre éducatif. Les performances passées ne préjugent pas des performances futures. Le trading sur le Forex comporte un risque élevé de perte en capital. Teste toujours sur un compte démo avant tout usage réel.
