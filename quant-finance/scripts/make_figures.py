"""Regenerate every figure in results/ from the raw price data.

Usage:
  python scripts/make_figures.py --nifty data/nifty50_index.csv --stocks data/nifty50_stocks/
"""
import argparse
import itertools
import os

import matplotlib
import numpy as np
import pandas as pd

import _path  # noqa: F401

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from quantlab.costs import MARKETS, cost_per_side  # noqa: E402
from quantlab.data import load_csv, load_csv_dir  # noqa: E402
from quantlab.pairs import CRIT_5, SECTORS, backtest, eg  # noqa: E402
from quantlab.risk import simulate, var_backtest, var_es  # noqa: E402
from quantlab.stats import ols, perf_stats  # noqa: E402
from quantlab.trend import FAST, SLOW, run_rule  # noqa: E402

# Validated categorical slots (light surface) + reserved status red, text inks.
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "lines.linewidth": 2, "legend.frameon": False,
})
OUT = "results"
RF = MARKETS["in"]["risk_free"]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), dpi=160)
    plt.close(fig)
    print("wrote", os.path.join(OUT, name))


def fig_var_backtest(nifty):
    logret = np.log(nifty).diff().dropna()
    df, _ = var_backtest(logret.values[:, None], np.array([1.0]), methods=("normal",))
    dates = logret.index[df.i.astype(int)]
    var99 = -df[("normal", 99)].values
    breach = df.actual.values < var99
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.bar(dates, df.actual * 100, width=20, color=np.where(df.actual > 0, "#c9c8c2", "#9e9d97"),
           label="Actual next-month return")
    ax.plot(dates, var99 * 100, color=BLUE, label="Forecast 99% VaR (normal Monte Carlo)")
    ax.scatter(dates[breach], df.actual[breach] * 100, s=40, color=RED, zorder=3,
               edgecolor=SURFACE, linewidth=1.5, label=f"Breach ({breach.sum()} of {len(df)} = "
                                                         f"{breach.mean():.1%}, promised 1%)")
    i = int(np.argmin(df.actual))
    ax.annotate(f"Mar 2020: {df.actual.iloc[i]:.0%} vs\nforecast {var99[i]:.0%}",
                (dates[i], df.actual.iloc[i] * 100), xytext=(-110, 5), textcoords="offset points",
                color=INK, fontsize=9, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("Monthly return (%)")
    ax.set_title("Monte Carlo VaR backtest: Nifty 50, 2002-2023", pad=28)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=8.5, handlelength=1.5)
    save(fig, "var_backtest.png")


def fig_var_correlation(stocks):
    tick = ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"]
    px = stocks[tick]
    r = np.log(px).diff().dropna()
    mu, vol, corr = r.mean().values, r.std().values, r.corr().values
    w, k, rng = np.full(5, 0.2), 5, np.random.default_rng(0)
    rows = []
    # same scenario order and seed as scripts/monte_carlo_var.py, so the numbers match
    for label, c in [("Estimated correlation", corr), ("Zero correlation", np.eye(k)),
                     ("Perfect correlation", np.full((k, k), 0.999) + np.eye(k) * 0.001)]:
        v, e = var_es(simulate(mu, np.outer(vol, vol) * c, w, 10_000, 21, rng) * 1e7, 0.95)
        rows.append((label, v / 1e5, e / 1e5))
    rows = [rows[1], rows[0], rows[2]]
    fig, ax = plt.subplots(figsize=(8, 3))
    y = np.arange(3)
    ax.barh(y + 0.19, [x[1] for x in rows], height=0.36, color=BLUE, label="95% VaR")
    ax.barh(y - 0.19, [x[2] for x in rows], height=0.36, color=ORANGE, label="Expected Shortfall")
    for yy, (_, v, e) in zip(y, rows):
        ax.text(v + 0.15, yy + 0.19, f"Rs {v:.1f} L", va="center", fontsize=9, color=INK)
        ax.text(e + 0.15, yy - 0.19, f"Rs {e:.1f} L", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, [x[0] for x in rows])
    ax.set_xlabel("One-month loss on Rs 1 crore (lakh)")
    ax.set_title("Same five stocks, only correlation changes")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=9)
    ax.set_xlim(0, max(x[2] for x in rows) * 1.18)
    save(fig, "var_correlation.png")


def fig_ma(nifty, div_yield=0.013):
    ret = nifty.pct_change().fillna(0) + div_yield / 252
    buy, sell = cost_per_side("in", "etf")
    cash = (1 + RF) ** (1 / 252) - 1
    warm = max(SLOW)
    grids = {}
    for kind in ("SMA", "EMA"):
        g = pd.DataFrame(np.nan, index=FAST, columns=SLOW)
        for f, s in itertools.product(FAST, SLOW):
            if f < s:
                g.loc[f, s] = perf_stats(run_rule(nifty, ret, f, s, kind, buy, sell, cash, warm)[0], RF)["Sharpe"]
        grids[kind] = g
    bh = perf_stats(ret.iloc[warm:], RF)["Sharpe"]
    vmin, vmax = min(g.min().min() for g in grids.values()), max(g.max().max() for g in grids.values())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, (kind, g) in zip(axes, grids.items()):
        im = ax.imshow(g.values, cmap="Blues", vmin=vmin, vmax=vmax, aspect="auto")
        for (i, j), v in np.ndenumerate(g.values):
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                        color="white" if v > (vmin + vmax) / 2 else INK,
                        fontweight="bold" if v > bh else "normal")
        ax.set_xticks(range(len(SLOW)), SLOW)
        ax.set_yticks(range(len(FAST)), ["price" if f == 1 else f for f in FAST])
        ax.set_xlabel("Slow average (days)")
        ax.set_title(f"{kind} crossovers")
        ax.grid(False)
    axes[0].set_ylabel("Fast average (days)")
    cb = fig.colorbar(im, ax=axes, shrink=0.85)
    cb.set_label("Sharpe ratio (excess of 6%)")
    cb.ax.axhline(bh, color=ORANGE, lw=2)
    fig.suptitle(f"Nifty 50 2002-2023: Sharpe of 70 rules. Bold beats buy & hold ({bh:.2f}, "
                 "orange tick on the scale)", x=0.01, ha="left",
                 fontsize=12, fontweight="bold")
    fig.savefig(os.path.join(OUT, "ma_sweep_heatmap.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote results/ma_sweep_heatmap.png")

    series = {"Buy & hold": (ret.iloc[warm:], "#7a7974"),
              "Price vs 100-day SMA": (run_rule(nifty, ret, 1, 100, "SMA", buy, sell, cash, warm)[0], BLUE),
              "50/200 SMA cross": (run_rule(nifty, ret, 50, 200, "SMA", buy, sell, cash, warm)[0], ORANGE)}
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    for name, (r, c) in series.items():
        eq = (1 + r).cumprod()
        a1.plot(eq.index, eq, color=c, label=name)
        a1.text(eq.index[-1], eq.iloc[-1], f"  {name} {eq.iloc[-1]:.0f}x", color=INK, fontsize=9,
                va="center", clip_on=False)
        a2.plot(eq.index, (eq / eq.cummax() - 1) * 100, color=c, lw=1.5)
    a1.set_yscale("log")
    a1.set_ylabel("Growth of Rs 1 (log)")
    a1.set_title("Trend filters cut crashes; whether they beat buy & hold depends on the period")
    a1.legend(loc="upper left", fontsize=9)
    a2.set_ylabel("Drawdown (%)")
    fig.tight_layout()
    fig.subplots_adjust(right=0.80)
    fig.savefig(os.path.join(OUT, "ma_equity_drawdown.png"), dpi=160)
    plt.close(fig)
    print("wrote results/ma_equity_drawdown.png")


def fig_pairs(stocks, split="2023-10-01"):
    buy, sell = cost_per_side("in", "futures")
    form, trade = stocks[:split], stocks[split:]
    rows, seen = [], set()
    for names in SECTORS.values():
        for x, y in itertools.combinations([n for n in names if n in stocks], 2):
            if frozenset((x, y)) in seen:
                continue
            seen.add(frozenset((x, y)))
            (s1, _), (s2, _) = eg(form[x], form[y]), eg(form[y], form[x])
            a, b = (x, y) if s1 <= s2 else (y, x)
            coef, _, _ = ols(form[a].values, form[b].values)
            r, _, _ = backtest(pd.concat([form[[a, b]], trade[[a, b]]]), coef[1], coef[0], buy, sell)
            rows.append(dict(pair=f"{a}/{b}", coint=min(s1, s2) < CRIT_5,
                             ins=r[:split].mean() * 252 * 100, oos=r[split:].mean() * 252 * 100))
    d = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for flag, c, lab in [(False, ORANGE, "Not cointegrated"), (True, BLUE, "Cointegrated at 5% (formation)")]:
        s = d[d.coint == flag]
        ax.scatter(s.ins, s.oos, s=46, color=c, edgecolor=SURFACE, linewidth=1.5, label=f"{lab}: {len(s)}")
    lim = [min(d.ins.min(), d.oos.min()) - 3, max(d.ins.max(), d.oos.max()) + 3]
    ax.plot(lim, lim, color=INK2, lw=0.8, ls="--")
    ax.text(lim[1], lim[1], "same as in-sample ", ha="right", va="bottom", fontsize=8, color=INK2)
    ax.axhline(RF * 100, color=INK2, lw=0.8, ls=":")
    ax.text(lim[0] + 1, RF * 100 + 1, "6% risk-free", fontsize=8, color=INK2)
    offsets = [(-8, 10, "right"), (8, 8, "left"), (8, -12, "left")]
    for (_, r), (dx, dy, ha) in zip(d[d.coint].nlargest(3, "oos").sort_values("ins").iterrows(), offsets):
        ax.annotate(r.pair, (r.ins, r.oos), xytext=(dx, dy), textcoords="offset points", fontsize=8,
                    color=INK, ha=ha, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    ax.set_xlabel("Formation period return, Oct 2020-Sep 2023 (% a year)")
    ax.set_ylabel("Trading period return, Oct 2023-Sep 2025 (% a year)")
    ax.set_title("69 same-sector Nifty 50 pairs: out-of-sample decay")
    ax.legend(loc="upper left", fontsize=9)
    save(fig, "pairs_oos.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nifty", default="data/nifty50_index.csv")
    ap.add_argument("--stocks", default="data/nifty50_stocks")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    nifty = load_csv(args.nifty)
    stocks = load_csv_dir(args.stocks)
    fig_var_backtest(nifty)
    fig_var_correlation(stocks)
    fig_ma(nifty)
    fig_pairs(stocks)


if __name__ == "__main__":
    main()
