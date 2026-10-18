"""Agent araignée (GROKBOT + JEV) – SIMULATION uniquement : argent fictif, aucun ordre réel.

  python3 -m araignee run                  # rattrape les bougies depuis le dernier passage (GitHub Actions)
  python3 -m araignee live                 # tourne en continu + tableau de bord (serveur / Docker)
  python3 -m araignee backtest --jours 7   # rejoue l'historique (règles seules ; --ia pour Grok)
  python3 -m araignee serve                # tableau de bord seul (http://localhost:4010)
"""
import argparse
import json
import os
import time

from . import market
from .brain import Brain
from .notify import telegram
from .portfolio import Portfolio
from .quant import Quant, load_macro
from .spider import Features, setup, scan_note, context, FACTORS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def load_cfg(overrides=None):
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["cerveau"] = os.environ.get("CERVEAU", cfg["cerveau"])
    cfg.update(overrides or {})
    return cfg


def simulate(pf, brain, cfg, pair, m1, m5, after, notify=None, d1=None, macro=None):
    """Rejoue chaque bougie 1 min clôturée après `after`, comme si on y était."""
    F = Features(m1, m5, cfg)
    quant = Quant(cfg, d1 or [], macro)
    last_setup = None
    day = None
    for i, c in enumerate(m1):
        t = c["t"]
        if t <= after:
            continue
        pf.update(pair, c, notify)
        if t // 86400 != day:  # QUANT publie le cadran du jour
            day = t // 86400
            pf.s["cadran"], info = quant.dial(t, pf.s["trades"])
            pf.s["cadran_info"] = info.get("info", "")
            pf.s["cadran_detail"] = info
        if (pf.can_trade(pair, t) and not cfg["arret_urgence"] and not os.environ.get("ARRET_URGENCE")
                and pf.s["cadran"] >= cfg["quant_cadran_min"]):
            sig = setup(F, i)
            if sig and sig["score"] >= min(cfg["jev_score_min"], cfg["jev_score_min_ia"]):
                go, note, source, conf, vet = brain.decide(pair, sig, context(F, i))
                sig.update(conf=conf, vet=vet, go=go, note=note, source=source)
                last_setup = sig
                if go:
                    pf.open(pair, sig, t, note, source, conf, notify)
                elif source != "règles":
                    pf.note(pair, t, note if note.startswith("skip") else "skip · " + note, "skip", agent="chief")
        pf.s["dernier_t"][pair] = t
        pf.s["prix"][pair] = c["close"]
    return F, last_setup


def snapshot(pf, cfg, pair, F, last_setup):
    """Ce que le tableau de bord affiche : les 6 agents, le graphique, l'analyse JEV."""
    if not F or not F.m1:
        return
    m1, m5 = F.m1, F.m5
    i = len(m1) - 1
    pos = pf.s["positions"].get(pair)
    st = pf.stats()
    sig = last_setup or pf.s.get("vue", {}).get(pair, {}).get("setup")
    rg = F.range5(i)
    trades = pf.s["trades"]
    red = bool(trades) and trades[-1]["pnl"] <= 0
    risk_pct = cfg["risque_par_trade_pct"] * (cfg["taille_apres_perte"] if red else 1)
    notional = pos["notional"] if pos else pf.s["capital"] * cfg["levier"] * min(1, risk_pct / 100 / 0.002 / cfg["levier"])
    agents = {
        "quant": {"cadran": pf.s.get("cadran", 1.0), "info": pf.s.get("cadran_info", ""),
                  "min": cfg["quant_cadran_min"], "arret": bool(cfg["arret_urgence"] or os.environ.get("ARRET_URGENCE"))},
        "chief": {"etat": "LONG" if pos and pos["side"] == "long" else "SHORT" if pos else F.bias(i) if F.bias(i) != "WAIT" else "WAIT",
                  "ligne": "worth ≥ {} · conf ≥ {}".format(cfg["chief_worth_min"], cfg["chief_conf_min"]) if not sig else
                  "worth {} · conf {}".format(sig.get("worth"), sig.get("conf"))},
        "scan": {"valeur": "{} / {}".format(rg[2] if rg else 0, cfg["scan_bougies_5m"]), "note": scan_note(F, i)},
        "vet": {"valeur": (sig or {}).get("conf") or cfg["vet_defaut"], "note": ((sig or {}).get("vet") or {}).get("texte", "waiting")},
        "size": {"valeur": round(notional, 2), "note": "margin fits, stop far from liq", "levier": cfg["levier"]},
        "fills": {"valeur": round(pos["entry"], 2) if pos else None,
                  "note": "{:.4f} {} filled".format(pos["size"], pair.split("-")[0]) if pos else "waiting for the plan"},
        "risk": {"valeur": "{}W {}L".format(st["gagnants"], st["perdants"]),
                 "note": "stop {:,.2f} · trail after +{}%".format(pos["stop"], cfg["trail_apres_pct"]) if pos
                 else ("no size up after a red ticket" if red else "flat, stops ready")},
    }
    jev = None
    if sig:
        jev = {"facteurs": [{"nom": k, "ok": bool(sig["checks"][k]), "detail": sig["details"][k]} for k in FACTORS],
               "score": sig["score"], "grade": sig["grade"], "side": sig["side"], "t": sig["t"], "go": sig.get("go"),
               "note": sig.get("note")}
    pf.s.setdefault("vue", {})[pair] = {
        "m1": [[c["t"], c["open"], c["high"], c["low"], c["close"], round(c["vol"], 4)] for c in m1[-90:]],
        "m5": [[c["t"], c["open"], c["high"], c["low"], c["close"], round(c["vol"], 4)] for c in m5[-40:]],
        "range": [rg[0], rg[1]] if rg else None, "agents": agents, "jev": jev,
        "setup": {k: v for k, v in sig.items() if k != "extreme"} if sig else None,
        "var_24h": round((m1[-1]["close"] / m1[-1440]["close"] - 1) * 100, 2) if len(m1) > 1440 else None,
    }


def finish(pf, cfg):
    pf.s["stats"] = pf.stats()
    pf.s["maj"] = int(time.time())
    pf.s["cerveau"] = cfg["cerveau"]
    pf.s["paires"] = cfg["paires"]
    pf.s["devise"] = cfg["devise"]
    pf.s["levier"] = cfg["levier"]
    pf.save()


def run(cfg, pf=None, notify=None, live=False):
    pf = pf or Portfolio(cfg, os.path.join(DATA, "state.json"))
    brain = Brain(cfg, pf.s, live=True)
    now = int(time.time())
    macro = load_macro() if cfg["quant_actif"] else {}
    # CHIEF prouve les outils : une source en panne = DEGRADED (et compte comme feu rouge pour QUANT)
    key = {"grok": "XAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}.get(cfg["cerveau"])
    pf.s["outils"] = {
        "coinbase": "OK",
        "fred": "OK" if all(macro.values()) or not cfg["quant_actif"] else "DEGRADED",
        "cerveau": "règles (gratuit)" if not key else ("OK" if os.environ.get(key) else "DEGRADED : pas de " + key),
    }
    for pair in cfg["paires"]:
        after = pf.s["dernier_t"].get(pair) or now - cfg["premier_passage_heures"] * 3600
        after = max(after, now - cfg["rattrapage_max_heures"] * 3600)
        m1 = market.history(pair, 60, min(after, now - 3600) - 25 * 3600, now)
        m5 = market.history(pair, 300, min(after, now - 3600) - 30 * 3600, now)
        d1 = market.history(pair, 86400, now - 260 * 86400, now)
        F, last = simulate(pf, brain, cfg, pair, m1, m5, after, notify, d1, macro)
        snapshot(pf, cfg, pair, F, last)
    finish(pf, cfg)
    st = pf.s["stats"]
    print("{} · capital fictif {:,.2f} ({:+.2f} %) · {} trades".format(
        time.strftime("%d/%m %H:%M"), pf.s["capital"], st["performance_pct"], st["trades"]))
    return pf


def daily_recap(pf, notify):
    """Rapport de CHIEF, une fois par jour : assemblé à partir des chiffres, jamais inventé."""
    if not notify:
        return
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if pf.s.get("recap_envoye") == today:
        return
    hier = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    tr = [x for x in pf.s["trades"] if time.strftime("%Y-%m-%d", time.gmtime(x["t_exit"])) == hier]
    pnl = sum(x["pnl"] for x in tr)
    st = pf.s["stats"]
    lines = ["🕷 Fred · rapport de CHIEF du {} (SIMULATION, 1 000 € fictifs au départ)".format(hier),
             "QUANT dial : {} ({})".format(pf.s.get("cadran"), pf.s.get("cadran_info", "")),
             "Trades : {} · gagnants {} · P&L {:+.2f}".format(len(tr), sum(1 for x in tr if x["pnl"] > 0), pnl),
             "Bank : {:,.2f} → {:,.2f}".format(pf.s["capital"] - pnl, pf.s["capital"]),
             "Depuis le début : {:+.2f} % · {} trades · PF {}".format(st["performance_pct"], st["trades"], st["profit_factor"]),
             "Outils : " + ", ".join("{} {}".format(k, v) for k, v in pf.s.get("outils", {}).items())]
    for x in tr:
        lines.append("· {} {} → {:+.2f} ({})".format(x["side"], x.get("grade"), x["pnl"], x["raison"]))
    notify("\n".join(lines))
    pf.s["recap_envoye"] = today
    pf.save()


def live(cfg):
    from .server import serve_background
    serve_background(ROOT)
    notify = telegram()
    print("{} en direct ({}) – SIMULATION avec {} € fictifs, aucun ordre réel.".format(
        cfg["nom"], ", ".join(cfg["paires"]), cfg["capital_fictif"]))
    pf = Portfolio(cfg, os.path.join(DATA, "state.json"))
    while True:
        try:
            cfg = load_cfg()  # relu à chaque tour : les nouveaux réglages s'appliquent sans redémarrer
            pf.cfg = cfg
            run(cfg, pf, notify)
            daily_recap(pf, notify)
        except Exception as e:
            print("  erreur, on réessaie :", e)
        time.sleep(cfg["intervalle_live_s"])


_CACHE = {}


def load_history(pair, start, now, cache):
    """1 min, 5 min et journalier. Avec cache=True, lit cache/ (et le garde en mémoire)."""
    if cache:
        paths = [os.path.join(ROOT, "cache", "{}-{}.json".format(pair, g)) for g in (60, 300, 86400)]
        if all(os.path.exists(p) for p in paths):
            for p in paths:
                if p not in _CACHE:
                    _CACHE[p] = json.load(open(p))
            m1, m5, d1 = (_CACHE[p] for p in paths)
            return ([c for c in m1 if c["t"] >= start - 2 * 3600], [c for c in m5 if c["t"] >= start - 8 * 3600],
                    [c for c in d1 if c["t"] >= start - 260 * 86400])
    return (market.history(pair, 60, start - 2 * 3600, now), market.history(pair, 300, start - 8 * 3600, now),
            market.history(pair, 86400, start - 260 * 86400, now))


def backtest(cfg, days, use_ia=False, cache=False, quiet=False, start=None, end=None, path=None):
    if not use_ia:
        cfg = dict(cfg, cerveau="regles")
    pf = Portfolio(cfg, path or os.path.join(DATA, "backtest.json"), fresh=True)
    pf.quiet = quiet
    csv_path = pf.path.replace(".json", "-journal.csv")
    if os.path.exists(csv_path) and not quiet:
        os.remove(csv_path)
    brain = Brain(cfg, pf.s)
    now = int(time.time())
    start = start or now - days * 86400
    for pair in cfg["paires"]:
        if not quiet:
            print("Backtest {} sur {} jours…".format(pair, days))
        m1, m5, d1 = load_history(pair, start, now, cache)
        if end:
            m1 = [c for c in m1 if c["t"] <= end]
            m5 = [c for c in m5 if c["t"] <= end]
        macro = _CACHE.setdefault("macro", load_macro(os.path.join(ROOT, "cache") if cache else None))
        F, last = simulate(pf, brain, cfg, pair, m1, m5, start, d1=d1, macro=macro)
        for p in list(pf.s["positions"]):
            pf.close(p, m1[-1]["t"], m1[-1]["close"], "fin du backtest")
        snapshot(pf, cfg, pair, F, last)
    finish(pf, cfg) if not quiet else None
    st = pf.stats()
    if not quiet:
        print("\n{} trades · {} gagnants ({} %) · profit factor {} · drawdown max {} % · résultat {:+.2f} % "
              "(capital fictif {:,.2f})".format(st["trades"], st["gagnants"], st["taux_reussite_pct"],
                                                st["profit_factor"], st["drawdown_max_pct"],
                                                st["performance_pct"], pf.s["capital"]))
    return st


def main():
    ap = argparse.ArgumentParser(prog="araignee")
    ap.add_argument("mode", choices=["run", "live", "backtest", "serve"])
    ap.add_argument("--jours", type=int, default=7)
    ap.add_argument("--ia", action="store_true", help="backtest avec Grok (coûte des tokens)")
    ap.add_argument("--cache", action="store_true", help="backtest sur l'historique en cache/")
    a = ap.parse_args()
    cfg = load_cfg()
    if a.mode == "run":
        notify = telegram()
        daily_recap(run(cfg, notify=notify), notify)
    elif a.mode == "live":
        live(cfg)
    elif a.mode == "backtest":
        backtest(cfg, a.jours, a.ia, a.cache)
    else:
        from .server import serve
        serve(ROOT)


if __name__ == "__main__":
    main()
