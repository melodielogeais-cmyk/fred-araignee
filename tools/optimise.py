"""Optimisation honnête : on cherche les réglages sur une période (entraînement),
puis on les vérifie à l'aveugle sur une période jamais vue (test).

  python3 tools/optimise.py --essais 200
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from araignee.__main__ import load_cfg, backtest, ROOT  # noqa: E402

SPACE = {
    "sweep_fenetre_1m": [2, 3, 5, 8],
    "sweep_min_pct": [0.02, 0.05, 0.08, 0.12],
    "sweep_max_pct": [0.3, 0.6, 1.0],
    "scan_bougies_5m": [24, 36, 48, 72, 96],
    "volume_pic_x": [1.2, 1.5, 2.0],
    "bos_recul_1m": [3, 5, 8, 12],
    "divergence_recul_1m": [20, 30, 45],
    "jev_score_min": [3, 4, 5],
    "chief_suivre_biais": [False, True],
    "ratio_gain_risque": [1.0, 1.5, 2.0, 3.0],
    "trail_apres_pct": [0.2, 0.3, 0.4, 0.6, 99],
    "trail_distance_pct": [0.1, 0.15, 0.25, 0.4],
    "stop_marge_pct": [0.02, 0.05, 0.1],
    "stop_min_pct": [0.0, 0.1, 0.15, 0.25, 0.4],
    "pause_apres_trade_min": [5, 10, 30],
    "duree_max_trade_min": [30, 60, 90, 180],
    "autoriser_short": [True, False],
    "taille_apres_perte": [0.5, 1],
    "quant_actif": [True, False],
    "quant_entrees": [["liquidite", "credit", "btc200", "vol_regime"], ["liquidite", "credit", "btc200"],
                      ["btc200", "vol_regime"], ["vol_regime"], ["liquidite", "credit", "volatilite", "btc200"]],
    "quant_cadran_min": [0.5, 0.75],
    "quant_vol_rang_min": [0.0, 0.1, 0.2, 0.3],
    "quant_vol_rang_max": [0.7, 0.8, 0.9, 1.0],
    "quant_journal_pf_min": [0.5, 0.7, 0.9],
}


def verdict(tr, te):
    """Les trois verdicts : battre la référence (rester en cash = 0 %) en rendement ET en profit factor,
    à l'entraînement ET sur la période jamais vue."""
    ok = lambda st: st["performance_pct"] > 0 and (st["profit_factor"] or 0) > 1
    if ok(tr) and ok(te):
        return "DATA VALIDATED"
    if ok(tr) or ok(te):
        return "TRADE-OFF"
    return "NO EDGE"


def score(st):
    """Rendement pénalisé par le drawdown, et un minimum de trades pour que ça veuille dire quelque chose."""
    if st["trades"] < 12:
        return -999
    return st["performance_pct"] - 0.5 * st["drawdown_max_pct"]


def _train(args):
    over, s, e = args
    cfg = dict(load_cfg({"cerveau": "regles"}), **over)
    return over, backtest(cfg, 0, cache=True, quiet=True, start=s, end=e, path=os.path.join(ROOT, "cache", "opt.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--essais", type=int, default=150)
    ap.add_argument("--test-jours", type=int, default=10)
    ap.add_argument("--graine", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.graine)
    m1 = json.load(open(os.path.join(ROOT, "cache", "BTC-EUR-60.json")))
    t_end = m1[-1]["t"]
    t_start = m1[0]["t"] + 8 * 3600
    t_split = t_end - a.test_jours * 86400
    base = load_cfg({"cerveau": "regles"})
    tmp = os.path.join(ROOT, "cache", "opt.json")

    def bt(cfg, s, e):
        return backtest(cfg, 0, cache=True, quiet=True, start=s, end=e, path=tmp)

    overs = [{}] + [{k: random.choice(v) for k, v in SPACE.items()} for _ in range(a.essais - 1)]
    results = []
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        for n, (over, tr) in enumerate(ex.map(_train, [(o, t_start, t_split) for o in overs], chunksize=4)):
            results.append((score(tr), over, tr))
            if n % 25 == 0:
                print("{} essais · {:.0f}s · meilleur entraînement {:.2f}".format(
                    n, time.time() - t0, max(r[0] for r in results)), flush=True)
    results.sort(key=lambda r: r[0], reverse=True)
    out = []
    for sc, over, tr in results[:10]:
        te = bt(dict(base, **over), t_split, t_end)
        v = verdict(tr, te)
        out.append({"reglages": over, "entrainement": tr, "test": te, "score_entrainement": sc, "verdict": v})
        print(v.ljust(15), "train {:+.2f}% ({} tr, PF {}, DD {}%) | TEST {:+.2f}% ({} tr, PF {}, DD {}%)".format(
            tr["performance_pct"], tr["trades"], tr["profit_factor"], tr["drawdown_max_pct"],
            te["performance_pct"], te["trades"], te["profit_factor"], te["drawdown_max_pct"]))
    for r in out:
        r["entrainement"].pop("par_jour", None)
        r["test"].pop("par_jour", None)
    json.dump(out, open(os.path.join(ROOT, "cache", "optimisation.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
