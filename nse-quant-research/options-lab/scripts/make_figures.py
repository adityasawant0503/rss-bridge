"""Regenerate the figures in results/.

Usage: python scripts/make_figures.py --csv data/nifty50_index.csv
"""
import argparse
import os

import matplotlib
import numpy as np

import _path  # noqa: F401

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from nifty_hedge_backtest import FUT_COST, Q, R, backtest, load  # noqa: E402
from optlab import binomial, bs, mc  # noqa: E402
from optlab.hedging import gbm_paths, hedge_pnl  # noqa: E402

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
BASE = dict(S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.2)


def label_end(ax, x, y, text):
    ax.annotate(text, (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=9, color=INK, annotation_clip=False)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(OUT, name))


def fig_convergence():
    exact = bs.price(**BASE)
    steps = np.unique(np.logspace(1, 3.3, 25).astype(int))
    err = [abs(binomial.price(**BASE, steps=n) - exact) for n in steps]
    paths = np.unique(np.logspace(3, 6, 13).astype(int) // 2 * 2)
    variants = [("Plain", False, False, "#7a7974"), ("Antithetic", True, False, ORANGE),
                ("Control variate", False, True, AQUA), ("Both", True, True, BLUE)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    a1.loglog(steps, err, color=BLUE, marker="o", ms=4)
    a1.loglog(steps, 1 / steps * err[0] * steps[0], color=INK2, lw=1, ls="--")
    a1.text(steps[-1], err[0] * steps[0] / steps[-1] * 0.55, "slope -1", fontsize=8, color=INK2, ha="right")
    a1.set_xlabel("Tree steps")
    a1.set_ylabel("Absolute pricing error")
    a1.set_title("Binomial tree converges to Black-Scholes")
    for name, anti, cv, c in variants:
        se = [mc.price(**BASE, n_paths=int(n), antithetic=anti, control_variate=cv, seed=7)[1] for n in paths]
        a2.loglog(paths, se, color=c, marker="o", ms=4, label=name)
        label_end(a2, paths, se, name)
    a2.set_xlabel("Monte Carlo paths")
    a2.set_ylabel("Standard error of price")
    a2.set_title("Variance reduction: same accuracy, far fewer paths")
    a2.legend(loc="lower left", fontsize=9)
    a2.set_xlim(right=paths[-1] * 6)
    save(fig, "convergence.png")


def fig_hedge_frequency():
    paths = gbm_paths(100, 21 / 252, 0.10, 0.15, 21 * 8, 3000, seed=11, q=Q)
    every = [168, 84, 42, 24, 8, 4, 2, 1]          # rebalances per month = 168/k
    n_reb = [168 / k for k in every]
    sd, mean_c = [], []
    for k in every:
        sd.append(hedge_pnl(paths, 100, 21 / 252, R, 0.15, "call", Q, k).std() * 100)
        mean_c.append(-hedge_pnl(paths, 100, 21 / 252, R, 0.15, "call", Q, k, FUT_COST).mean() * 100)
    fig, a1 = plt.subplots(figsize=(8, 4.2))
    a1.loglog(n_reb, sd, color=BLUE, marker="o", ms=5)
    a1.loglog(n_reb, mean_c, color=ORANGE, marker="o", ms=5)
    label_end(a1, n_reb, sd, "Hedging error (std of P&L)")
    label_end(a1, n_reb, mean_c, "Average hedging cost")
    a1.set_xlabel("Hedge rebalances over a one-month option")
    a1.set_ylabel("% of spot")
    a1.set_title("Hedge more often: less risk, more cost (simulated, Nifty-like inputs)")
    a1.set_xlim(right=n_reb[-1] * 4)
    save(fig, "hedge_frequency.png")


def fig_nifty(px):
    b = backtest(px)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1, 1.3]})
    a1.scatter(b.approx * 100, b.pnl * 100, s=22, color=BLUE, edgecolor=SURFACE, linewidth=1)
    lim = [min(b.approx.min(), b.pnl.min()) * 100 - 0.3, max(b.approx.max(), b.pnl.max()) * 100 + 0.3]
    a1.plot(lim, lim, color=INK2, lw=0.8, ls="--")
    a1.set_xlabel("Theory: 0.5 x gamma x S x (implied^2 - realised^2) x T  (% of spot)")
    a1.set_ylabel("Actual hedged P&L (% of spot)")
    a1.set_title(f"P&L tracks the volatility gap (corr {b.pnl.corr(b.approx):.2f})")
    w = b.pnl.idxmin()
    a1.annotate(f"May 2009 election gap\n{b.pnl.min():.1%}", (b.approx[w] * 100, b.pnl[w] * 100),
                xytext=(12, 0), textcoords="offset points", fontsize=8, color=INK, va="center")
    for mk, c in [(0.0, ORANGE), (0.02, BLUE), (0.05, AQUA)]:
        cum = backtest(px, mk).pnl.cumsum() * 100
        a2.plot(cum.index, cum, color=c, label=f"Sell at trailing vol + {mk*100:.0f} pts")
        label_end(a2, cum.index, cum.values, f"+{mk*100:.0f} pts: {cum.iloc[-1]:+.0f}%")
    a2.axhline(0, color=INK2, lw=0.8)
    a2.set_ylabel("Cumulative P&L (% of spot, summed)")
    a2.set_title("Short 1-month Nifty calls, hedged daily, 2001-2023")
    a2.legend(loc="upper left", fontsize=9)
    save(fig, "nifty_hedging.png")


def fig_greeks():
    S = np.linspace(70, 130, 241)
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.2))
    for T, c, lab in [(0.5, BLUE, "6 months"), (1 / 12, ORANGE, "1 month"), (1 / 52, AQUA, "1 week")]:
        g = bs.greeks(S, 100, T, R, 0.15, "call", Q)
        p = bs.price(S, 100, T, R, 0.15, "call", Q)
        for ax, y, name in zip(axes, [p, g["delta"], g["gamma"], g["theta"] / 365],
                               ["Price", "Delta", "Gamma", "Theta per day"], strict=True):
            ax.plot(S, y, color=c, label=lab)
            ax.set_title(name)
            ax.set_xlabel("Spot (strike 100)")
    axes[0].legend(loc="upper left", fontsize=8, title="Time to expiry", title_fontsize=8)
    fig.suptitle("Call Greeks sharpen as expiry nears (vol 15%, r 6%, q 1.3%)", x=0.01, ha="left",
                 fontsize=12, fontweight="bold")
    save(fig, "greeks.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/nifty50_index.csv")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    fig_convergence()
    fig_hedge_frequency()
    fig_greeks()
    fig_nifty(load(args.csv))


if __name__ == "__main__":
    main()
