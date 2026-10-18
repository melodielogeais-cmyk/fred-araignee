"""Amélioration continue de Fred (une fois par semaine).

1. Télécharge les 90 derniers jours de vraies bougies.
2. Essaie N variantes de réglages sur les 60 premiers jours (entraînement).
3. Vérifie les meilleures à l'aveugle sur les 30 derniers jours (test).
4. Ne change config.json QUE si une variante est « DATA VALIDATED » ET fait mieux que les réglages
   actuels sur la période de test. Sinon, on garde les réglages actuels.
Chaque décision est notée dans data/ameliorations.json (visible sur le tableau de bord).

  python3 tools/autotune.py --essais 300
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from araignee import market  # noqa: E402
from araignee.__main__ import load_cfg, backtest, ROOT  # noqa: E402
from araignee.quant import load_macro  # noqa: E402
from optimise import SPACE, verdict, score, _train  # noqa: E402

CACHE = os.path.join(ROOT, "cache")
LOG = os.path.join(ROOT, "data", "ameliorations.json")


def refresh_cache(pair, days=90):
    os.makedirs(CACHE, exist_ok=True)
    now = int(time.time())
    for g, back in ((60, days), (300, days), (86400, 420)):
        c = market.history(pair, g, now - back * 86400 - 8 * 3600, now)
        json.dump(c, open(os.path.join(CACHE, "{}-{}.json".format(pair, g)), "w"))
    for f in os.listdir(CACHE):
        if f.startswith("fred-"):
            os.remove(os.path.join(CACHE, f))
    load_macro(CACHE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--essais", type=int, default=300)
    ap.add_argument("--sans-telechargement", action="store_true")
    a = ap.parse_args()
    base = load_cfg({"cerveau": "regles"})
    pair = base["paires"][0]
    if not a.sans_telechargement:
        refresh_cache(pair)
    m1 = json.load(open(os.path.join(CACHE, "{}-60.json".format(pair))))
    t_end, t_start = m1[-1]["t"], m1[0]["t"] + 8 * 3600
    t_split = t_end - 30 * 86400
    tmp = os.path.join(CACHE, "auto.json")

    def bt(over, s, e):
        return backtest(dict(base, **over), 0, cache=True, quiet=True, start=s, end=e, path=tmp)

    cur_tr, cur_te = bt({}, t_start, t_split), bt({}, t_split, t_end)
    cur_v = verdict(cur_tr, cur_te)
    # variantes : moitié autour des réglages actuels (petits pas), moitié au hasard
    overs = []
    for n in range(a.essais):
        if n % 2:
            overs.append({k: random.choice(v) for k, v in SPACE.items()})
        else:
            k = random.sample(list(SPACE), 3)
            overs.append({x: random.choice(SPACE[x]) for x in k})
    with ProcessPoolExecutor() as ex:
        res = [(score(tr), o, tr) for o, tr in ex.map(_train, [(o, t_start, t_split) for o in overs], chunksize=4)]
    res.sort(key=lambda r: r[0], reverse=True)
    best = None
    for sc, over, tr in res[:10]:
        if sc <= score(cur_tr):
            break
        te = bt(over, t_split, t_end)
        v = verdict(tr, te)
        if v == "DATA VALIDATED" and te["performance_pct"] > cur_te["performance_pct"]:
            best = (over, tr, te, v)
            break

    entry = {"date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "essais": a.essais,
             "actuel": {"verdict": cur_v, "train_pct": cur_tr["performance_pct"], "test_pct": cur_te["performance_pct"],
                        "test_pf": cur_te["profit_factor"]}}
    if best:
        over, tr, te, v = best
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.update(over)
        with open(os.path.join(ROOT, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        entry.update(decision="NOUVEAUX RÉGLAGES ADOPTÉS", changements=over,
                     nouveau={"verdict": v, "train_pct": tr["performance_pct"], "test_pct": te["performance_pct"],
                              "test_pf": te["profit_factor"]})
    else:
        entry["decision"] = "réglages actuels conservés (aucune variante validée et meilleure)"
    print(json.dumps(entry, ensure_ascii=False, indent=1))
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    log.append(entry)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    json.dump(log[-52:], open(LOG, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
