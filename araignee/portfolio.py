"""Portefeuille FICTIF (agents SIZE, FILLS, RISK). Aucune connexion à un courtier, aucun ordre réel.

SIZE  : taille calculée sur le risque (stop) et plafonnée par le levier (perp isolé).
FILLS : exécution simulée avec glissement et frais.
RISK  : stop derrière la mèche, stop suiveur après +x %, pas de hausse de taille après une perte.
"""
import csv
import json
import os
from datetime import datetime, timezone


def day_of(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


class Portfolio:
    def __init__(self, cfg, path, fresh=False):
        self.cfg = cfg
        self.path = path
        self.quiet = False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if fresh or not os.path.exists(path):
            cap = cfg["capital_fictif"]
            self.s = {"capital": cap, "depart": cap, "positions": {}, "trades": [], "notes": [],
                      "equity": [], "dernier_t": {}, "prix": {}, "cooldown": {}, "appels_ia": {},
                      "derniere_perte": False}
        else:
            with open(path, encoding="utf-8") as f:
                self.s = json.load(f)

    def save(self):
        self.s["notes"] = self.s["notes"][-400:]
        self.s["equity"] = self.s["equity"][-2000:]
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.s, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)

    def note(self, pair, t, text, kind="info", notify=None, agent="crawler"):
        self.s["notes"].append({"t": t, "pair": pair, "note": text, "type": kind, "agent": agent})
        if not self.quiet:
            print("  🕷  {} {} « {} »".format(datetime.fromtimestamp(t).strftime("%d/%m %H:%M"), pair, text))
        if notify:
            notify("🕷 {} · {}".format(pair, text))

    # --- RISK : peut-on prendre un trade ? ---
    def can_trade(self, pair, t):
        if pair in self.s["positions"] or t < self.s["cooldown"].get(pair, 0):
            return False
        if len(self.s["positions"]) >= self.cfg["positions_max_simultanees"]:
            return False
        today = [x for x in self.s["trades"][-50:] if day_of(x["t"]) == day_of(t)]
        if len(today) >= self.cfg["trades_max_par_jour"]:
            return False
        return sum(x["pnl"] for x in today) > -self.s["depart"] * self.cfg["perte_max_jour_pct"] / 100

    # --- SIZE + FILLS : ouverture ---
    def open(self, pair, sig, t, note, source, confiance, notify=None):
        c = self.cfg
        long = sig["side"] == "long"
        slip = c["glissement_pct"] / 100
        price = sig["price"] * (1 + slip if long else 1 - slip)
        buf = price * c["stop_marge_pct"] / 100
        stop = sig["extreme"] - buf if long else sig["extreme"] + buf
        mini = price * c["stop_min_pct"] / 100  # un stop trop serré gonfle la taille, et les frais avec
        if abs(price - stop) < mini:
            stop = price - mini if long else price + mini
        dist = abs(price - stop) / price
        if dist <= 0 or dist * 100 > c["stop_max_pct"]:
            return False
        risk_pct = c["risque_par_trade_pct"] * (c["taille_apres_perte"] if self.s.get("derniere_perte") else 1)
        risk_pct *= min(1.0, self.s.get("cadran", 1.0))  # QUANT : le cadran est le premier multiplicateur
        notional = min(self.s["capital"] * risk_pct / 100 / dist, self.s["capital"] * c["levier"])
        size = notional / price
        lev = c["levier"]
        liq = price * (1 - 1 / lev + 0.005) if long else price * (1 + 1 / lev - 0.005)
        if (long and stop <= liq) or (not long and stop >= liq):  # « stop far from liq »
            return False
        r = abs(price - stop)
        tp = price + c["ratio_gain_risque"] * r * (1 if long else -1)
        self.s["positions"][pair] = {
            "pair": pair, "side": sig["side"], "entry": price, "stop": stop, "stop_initial": stop, "tp": tp,
            "size": size, "notional": round(notional, 2), "levier_effectif": round(notional / self.s["capital"], 1),
            "liq": liq, "t": t, "note": note, "score": sig["score"], "grade": sig.get("grade"),
            "source": source, "confiance": confiance, "best": price, "trail": False}
        self.note(pair, t, note, "entree", notify)
        return True

    # --- RISK : gestion de la position à chaque bougie ---
    def update(self, pair, candle, notify=None):
        p = self.s["positions"].get(pair)
        if not p:
            return
        c = self.cfg
        long = p["side"] == "long"
        # 1) la bougie touche-t-elle le stop actuel ? (prudent : le stop passe avant l'objectif)
        if (long and candle["low"] <= p["stop"]) or (not long and candle["high"] >= p["stop"]):
            why = "trail" if p["trail"] else "stop"
            return self.close(pair, candle["t"], p["stop"], why, notify)
        if (long and candle["high"] >= p["tp"]) or (not long and candle["low"] <= p["tp"]):
            return self.close(pair, candle["t"], p["tp"], "objectif", notify)
        # 2) stop suiveur après +x %
        p["best"] = max(p["best"], candle["high"]) if long else min(p["best"], candle["low"])
        gain = (p["best"] / p["entry"] - 1) * 100 * (1 if long else -1)
        if gain >= c["trail_apres_pct"]:
            d = c["trail_distance_pct"] / 100
            new = p["best"] * (1 - d) if long else p["best"] * (1 + d)
            if c["trail_mini_break_even"]:
                new = max(new, p["entry"]) if long else min(new, p["entry"])
            if (long and new > p["stop"]) or (not long and new < p["stop"]):
                p["stop"], p["trail"] = new, True
        if candle["t"] - p["t"] >= c["duree_max_trade_min"] * 60:
            self.close(pair, candle["t"], candle["close"], "temps écoulé", notify)

    def close(self, pair, t, price, why, notify=None):
        p = self.s["positions"].pop(pair)
        long = p["side"] == "long"
        slip = self.cfg["glissement_pct"] / 100
        if why in ("stop", "trail", "temps écoulé", "fin du backtest"):
            price = price * (1 - slip if long else 1 + slip)
        exit_fee = self.cfg["frais_objectif_pct"] if why == "objectif" else self.cfg["frais_stop_pct"]
        fees = (p["entry"] * self.cfg["frais_entree_pct"] + price * exit_fee) * p["size"] / 100
        pnl = (price - p["entry"]) * p["size"] * (1 if long else -1) - fees
        self.s["capital"] += pnl
        self.s["derniere_perte"] = pnl <= 0
        trade = dict(p, exit=price, t_exit=t, pnl=round(pnl, 2), raison=why)
        self.s["trades"].append(trade)
        self.s["equity"].append([t, round(self.s["capital"], 2)])
        self.s["cooldown"][pair] = t + self.cfg["pause_apres_trade_min"] * 60
        txt = "{:+.2f} booked · session {:+.1f}%".format(pnl, (self.s["capital"] / self.s["depart"] - 1) * 100)
        if pnl <= 0:
            txt = "{:+.2f} cut ({}) · no size up after a red ticket".format(pnl, why)
        self.note(pair, t, txt, "sortie", notify)
        self._csv(trade)

    def _csv(self, tr):
        if self.quiet:
            return
        path = self.path.replace(".json", "-journal.csv")
        new = not os.path.exists(path)
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            if new:
                w.writerow(["ouverture", "fermeture", "paire", "sens", "setup", "entrée", "sortie", "notionnel",
                            "levier", "pnl", "raison", "cerveau", "confiance", "note"])
            w.writerow([fmt(tr["t"]), fmt(tr["t_exit"]), tr["pair"], tr["side"], tr.get("grade"),
                        round(tr["entry"], 2), round(tr["exit"], 2), tr["notional"], tr["levier_effectif"],
                        tr["pnl"], tr["raison"], tr["source"], tr["confiance"], tr["note"]])

    def stats(self):
        tr = self.s["trades"]
        wins = [x["pnl"] for x in tr if x["pnl"] > 0]
        losses = [x["pnl"] for x in tr if x["pnl"] <= 0]
        peak, dd, eq = self.s["depart"], 0.0, self.s["depart"]
        for x in tr:
            eq += x["pnl"]
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak * 100)
        days = {}
        for x in tr:
            d = days.setdefault(day_of(x["t_exit"]), {"jour": day_of(x["t_exit"]), "trades": 0, "gagnants": 0, "pnl": 0.0})
            d["trades"] += 1
            d["gagnants"] += x["pnl"] > 0
            d["pnl"] = round(d["pnl"] + x["pnl"], 2)
        return {
            "trades": len(tr), "gagnants": len(wins), "perdants": len(losses),
            "taux_reussite_pct": round(len(wins) / len(tr) * 100, 1) if tr else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "drawdown_max_pct": round(dd, 2),
            "performance_pct": round((self.s["capital"] / self.s["depart"] - 1) * 100, 2),
            "par_jour": sorted(days.values(), key=lambda d: d["jour"]),
        }
