"""Night shift : le cadran QUANT sépare-t-il vraiment les bons jours des mauvais ?

On laisse l'araignée trader tous les jours (QUANT coupé), puis on range chaque trade selon
le cadran que QUANT aurait publié ce jour-là. Si les groupes ne se séparent pas : NO EDGE,
le cadran se supprime, il ne se règle pas.

  python3 tools/night_shift.py [--jours 90]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from araignee.__main__ import load_cfg, load_history, simulate, ROOT, _CACHE  # noqa: E402
from araignee.brain import Brain  # noqa: E402
from araignee.portfolio import Portfolio  # noqa: E402
from araignee.quant import Quant, load_macro  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=88)
    a = ap.parse_args()
    cfg = load_cfg({"cerveau": "regles"})
    tmp = os.path.join(ROOT, "cache", "night.json")
    now = int(time.time())
    start = now - a.jours * 86400
    c2 = dict(cfg, quant_actif=False)
    pf = Portfolio(c2, tmp, fresh=True)
    pf.quiet = True
    m1, m5, d1 = load_history(c2["paires"][0], start, now, True)
    macro = _CACHE.get("macro") or load_macro(os.path.join(ROOT, "cache"))
    simulate(pf, Brain(c2, pf.s), c2, c2["paires"][0], m1, m5, start, d1=d1, macro=macro)
    q = Quant(dict(cfg, quant_actif=True), d1, macro)
    buckets = {}
    for tr in pf.s["trades"]:
        d, _ = q.dial(tr["t"], [])  # cadran sans le malus du journal : on teste les entrées seules
        b = min(1.0, round(d * 4) / 4)
        g = buckets.setdefault(b, [])
        g.append(tr["pnl"])
    print("cadran   trades   gagnants   P&L total   P&L moyen")
    for b in sorted(buckets):
        p = buckets[b]
        print("{:>6.2f}   {:>6}   {:>7.0%}   {:>9.2f}   {:>9.2f}".format(
            b, len(p), sum(1 for x in p if x > 0) / len(p), sum(p), sum(p) / len(p)))
    lo = [x for b, p in buckets.items() if b < cfg["quant_cadran_min"] for x in p]
    hi = [x for b, p in buckets.items() if b >= cfg["quant_cadran_min"] for x in p]
    if len(lo) < 5 or len(hi) < 5:
        print("\nVERDICT : pas assez de trades dans un des groupes pour conclure.")
    elif sum(hi) / len(hi) > sum(lo) / len(lo):
        print("\nVERDICT : le cadran sépare (P&L moyen {:.2f} au-dessus du seuil contre {:.2f} en dessous).".format(
            sum(hi) / len(hi), sum(lo) / len(lo)))
    else:
        print("\nVERDICT : NO EDGE. Le cadran ne sépare pas les bons jours des mauvais : à supprimer.")


if __name__ == "__main__":
    main()
