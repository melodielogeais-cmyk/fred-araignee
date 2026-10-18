"""QUANT : ne trade jamais, ne choisit jamais. Chaque jour (UTC), il publie un cadran entre 0 et 1 :
avec quelle force l'équipe a le droit de pousser aujourd'hui.

  cadran < quant_cadran_min (0.50) -> on ne trade pas aujourd'hui
  0.50 -> demi-taille · 0.75 -> trois quarts · 1.00 -> pleine taille

Le cadran = part de « feux verts » parmi les entrées choisies dans config.json :
  liquidite   liquidité nette Fed (WALCL - WTREGEN - RRPONTSYD) en hausse sur 4 semaines   (FRED)
  credit      écart high-yield (BAMLH0A0HYM2) stable ou en baisse sur 4 semaines           (FRED)
  volatilite  VIX sous 22                                                                  (FRED)
  btc200      clôture BTC de la veille au-dessus de sa moyenne 200 jours
  vol_regime  amplitude BTC de la veille dans la zone de confort (rang parmi 30 jours)
puis le journal de l'équipe : si les derniers trades sont mauvais, on lève le pied.

Uniquement des données publiées AVANT le jour concerné (aucune triche en backtest).
On n'arrondit jamais un cadran vers le haut.
"""
import csv
import io
import json
import math
import os
import subprocess
import urllib.request
from datetime import datetime, timezone

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
SERIES = ["WALCL", "WTREGEN", "RRPONTSYD", "BAMLH0A0HYM2", "VIXCLS"]
LAG_DAYS = 2  # une valeur datée J n'est connue qu'environ 1 à 2 jours plus tard


def _download(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agent-araignee"})
        return urllib.request.urlopen(req, timeout=15).read().decode()
    except Exception:  # certains réseaux bloquent Python mais pas curl
        return subprocess.run(["curl", "-sL", "--max-time", "30", url], capture_output=True,
                              text=True, check=True).stdout


def fetch_fred(series_id):
    text = _download(FRED.format(series_id))
    out = []
    for row in csv.reader(io.StringIO(text)):
        try:
            d = int(datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) // 86400
            out.append((d, float(row[1])))
        except (ValueError, IndexError):
            continue
    return out


def load_macro(cache_dir=None):
    """{série: [(jour, valeur), ...]}. Avec cache_dir : lit/écrit un cache local."""
    macro = {}
    for s in SERIES:
        path = os.path.join(cache_dir, "fred-{}.json".format(s)) if cache_dir else None
        if path and os.path.exists(path):
            macro[s] = [tuple(x) for x in json.load(open(path))]
            continue
        try:
            macro[s] = fetch_fred(s)
            if path:
                json.dump(macro[s], open(path, "w"))
        except Exception as e:
            print("  (QUANT : FRED {} indisponible : {})".format(s, e))
            macro[s] = []
    return macro


def _asof(series, day):
    """Dernière valeur connue au jour `day` (avec le délai de publication)."""
    lo, hi, best = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= day - LAG_DAYS:
            best, lo = series[mid], mid + 1
        else:
            hi = mid - 1
    return best


class Quant:
    def __init__(self, cfg, d1, macro):
        self.cfg = cfg
        self.macro = macro or {}
        self.closes = {c["t"] // 86400: c["close"] for c in d1}
        self.ranges = {c["t"] // 86400: (c["high"] - c["low"]) / c["close"] * 100 for c in d1}
        self.days = sorted(self.closes)

    def inputs(self, day):
        """Feux verts du jour : {entrée: (vert ?, valeur)} ; None = donnée absente (comptée rouge)."""
        g = {}
        m = self.macro
        w, t, r = (_asof(m.get(k, []), day) for k in ("WALCL", "WTREGEN", "RRPONTSYD"))
        w4, t4, r4 = (_asof(m.get(k, []), day - 28) for k in ("WALCL", "WTREGEN", "RRPONTSYD"))
        if all((w, t, r, w4, t4, r4)):
            now = w[1] / 1000 - t[1] / 1000 - r[1]
            before = w4[1] / 1000 - t4[1] / 1000 - r4[1]
            g["liquidite"] = (now - before > 0, round(now - before, 1))
        else:
            g["liquidite"] = (False, None)
        hy, hy4 = _asof(m.get("BAMLH0A0HYM2", []), day), _asof(m.get("BAMLH0A0HYM2", []), day - 28)
        g["credit"] = (hy[1] - hy4[1] <= 0, round(hy[1] - hy4[1], 2)) if hy and hy4 else (False, None)
        vix = _asof(m.get("VIXCLS", []), day)
        g["volatilite"] = (vix[1] < self.cfg["quant_vix_max"], vix[1]) if vix else (False, None)
        hist = [self.closes[d] for d in range(day - 200, day) if d in self.closes]
        prev = self.closes.get(day - 1)
        if prev and len(hist) >= 150:
            ma = sum(hist) / len(hist)
            g["btc200"] = (prev > ma, round(prev / ma - 1, 3))
        else:
            g["btc200"] = (False, None)
        rg = self.ranges.get(day - 1)
        past = [self.ranges[d] for d in range(day - 31, day - 1) if d in self.ranges]
        if rg is not None and len(past) >= 10:
            rank = sum(1 for v in past if v < rg) / len(past)
            g["vol_regime"] = (self.cfg["quant_vol_rang_min"] <= rank <= self.cfg["quant_vol_rang_max"], round(rank, 2))
        else:
            g["vol_regime"] = (False, None)
        return g

    def dial(self, t, trades):
        """Renvoie (cadran, détails)."""
        cfg = self.cfg
        if not cfg.get("quant_actif", True):
            return 1.0, {"info": "quant off"}
        day = t // 86400
        g = self.inputs(day)
        used = cfg["quant_entrees"]
        greens = sum(1 for k in used if g[k][0])
        score = greens / len(used) if used else 1.0
        info = {"entrees": {k: g[k] for k in used}, "verts": greens, "total": len(used)}
        recent = [x for x in trades if x["t_exit"] < day * 86400][-cfg["quant_journal_trades"]:]
        if len(recent) >= cfg["quant_journal_trades"]:
            won = sum(x["pnl"] for x in recent if x["pnl"] > 0)
            lost = -sum(x["pnl"] for x in recent if x["pnl"] <= 0)
            pf = won / lost if lost else 9.9
            info["desk_pf"] = round(pf, 2)
            if pf < cfg["quant_journal_pf_min"]:
                score *= cfg["quant_journal_malus"]
        score = math.floor(score * 100) / 100  # jamais arrondi vers le haut
        info["info"] = "{}/{} green".format(greens, len(used)) + (" · desk PF {}".format(info["desk_pf"]) if "desk_pf" in info else "")
        return score, info


def today(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
