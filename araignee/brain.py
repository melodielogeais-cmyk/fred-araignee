"""VET (le mouvement est-il réel ?) et CHIEF (on y va ?), avec Grok comme cerveau.

Fournisseurs : "grok" (xAI, XAI_API_KEY), "claude" (ANTHROPIC_API_KEY) ou "regles" (gratuit).
Sans clé, au-delà du budget du jour ou en cas d'erreur : repli sur les règles.
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

from .spider import crawler_note

SYSTEM = (
    "Tu es CHIEF, le chef d'une équipe d'agents de trading SIMULÉ (argent fictif) sur {pair}, "
    "graphique 1 min, carte 5 min. Le crawler a repéré un sweep de liquidité ; JEV a noté la confluence "
    "sur 5 critères (liquidity sweep, rsi divergence, volume spike, vwap reclaim, break of structure) ; "
    "VET a lu le carnet d'ordres quand il est disponible. Si VET indique « book not read (replay) » ou "
    "« book unavailable », c'est normal (passage rejoué) : ce n'est ni un signal positif ni négatif, ne le cite pas "
    "et juge sur la confluence JEV, le biais et le contexte. Décide : go ou skip. Sois exigeant, mais un setup "
    "noté 4 ou 5 sur 5 et aligné avec le biais mérite un go sauf contre-indication claire dans le contexte. "
    "Réponds UNIQUEMENT en JSON : "
    '{{"decision":"go"|"skip","confiance":0-100,"note":"une ligne sèche en anglais de trader, '
    'moins de 12 mots, style: sweep 0.24% under support · 5 of 5 on 5m"}}'
)


def vet_book(pair, side):
    """VET : profondeur du carnet d'ordres à ±0,3 % (en direct uniquement)."""
    url = "https://api.exchange.coinbase.com/products/{}/book?level=2".format(pair)
    req = urllib.request.Request(url, headers={"User-Agent": "agent-araignee"})
    book = json.load(urllib.request.urlopen(req, timeout=15))
    mid = (float(book["bids"][0][0]) + float(book["asks"][0][0])) / 2
    bids = sum(float(q) for p, q, _ in book["bids"] if float(p) >= mid * 0.997)
    asks = sum(float(q) for p, q, _ in book["asks"] if float(p) <= mid * 1.003)
    ratio = (bids / asks if side == "long" else asks / bids) if min(bids, asks) > 0 else 1.0
    score = round(ratio / (1 + ratio), 2)
    txt = "bids {:.1f}× asks under price".format(bids / asks) if side == "long" else \
        "asks {:.1f}× bids over price".format(asks / bids)
    return score, txt


class Brain:
    def __init__(self, cfg, state, live=False):
        self.cfg = cfg
        self.state = state
        self.live = live
        self.provider = cfg["cerveau"]

    def _budget(self, t):
        day = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        calls = self.state.setdefault("appels_ia", {})
        return calls.get(day, 0) < self.cfg["appels_ia_max_par_jour"], day

    def decide(self, pair, sig, ctx):
        """Renvoie (go, note, source, confiance 0-1, vet)."""
        c = self.cfg
        vet = {"score": None, "texte": "book not read (replay)"}
        if self.live and time.time() - sig["t"] < 240:
            try:
                vet["score"], vet["texte"] = vet_book(pair, sig["side"])
            except Exception as e:
                vet["texte"] = "book unavailable"
        conf = vet["score"] if vet["score"] is not None else c["vet_defaut"]
        if c["chief_suivre_biais"] and not sig["aligned"]:
            return False, "skip · against chief bias " + sig["bias"], "règles", conf, vet
        rules_go = sig["score"] >= c["jev_score_min"] and sig["worth"] >= c["chief_worth_min"] \
            and conf >= c["chief_conf_min"]
        fallback = (rules_go, crawler_note(sig), "règles", conf, vet)
        if self.provider == "regles" or sig["score"] < c["jev_score_min_ia"]:
            return fallback
        # le même setup dure souvent plusieurs minutes : on réutilise la décision au lieu de rappeler l'IA
        prev = self.state.get("derniere_decision_ia", {}).get(pair)
        if prev and prev["side"] == sig["side"] and abs(prev["level"] - sig["level"]) <= sig["level"] * 0.0005 \
                and 0 <= sig["t"] - prev["t"] <= c.get("ia_reutilisation_min", 15) * 60:
            return prev["go"], prev["note"], self.provider, prev["conf"], vet
        ok, day = self._budget(sig["t"])
        if not ok:
            return fallback
        facts = {k: sig[k] for k in ("side", "price", "level", "depth", "score", "grade", "bias", "worth")}
        facts["jev_confluence"] = {k: [bool(sig["checks"][k]), sig["details"][k]] for k in sig["checks"]}
        facts["vet"] = vet
        facts["heure_utc"] = datetime.fromtimestamp(sig["t"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        facts["contexte"] = ctx
        try:
            text = self._grok(pair, facts) if self.provider == "grok" else self._claude(pair, facts)
        except Exception as e:
            print("  (cerveau {} indisponible : {})".format(self.provider, e))
            self.state.setdefault("outils", {})["cerveau"] = "DEGRADED : " + str(e)[:80]
            return fallback
        calls = self.state.setdefault("appels_ia", {})
        calls[day] = calls.get(day, 0) + 1
        data = _parse(text)
        if not data:
            return fallback
        conf_ia = max(0, min(100, float(data.get("confiance") or 0))) / 100
        go = data.get("decision") == "go" and conf_ia >= c["chief_conf_min"] and sig["worth"] >= c["chief_worth_min"]
        note = str(data.get("note") or crawler_note(sig)).splitlines()[0][:120]
        self.state.setdefault("derniere_decision_ia", {})[pair] = {
            "t": sig["t"], "side": sig["side"], "level": sig["level"], "go": go, "note": note,
            "conf": round(conf_ia, 2)}
        return go, note, self.provider, round(conf_ia, 2), vet

    def _grok(self, pair, facts):
        key = os.environ.get("XAI_API_KEY")
        if not key:
            raise RuntimeError("XAI_API_KEY absente")
        body = {"model": self.cfg["modele_grok"],
                "input": [{"role": "system", "content": SYSTEM.format(pair=pair)},
                          {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]}
        resp = _post("https://api.x.ai/v1/responses", body, {"Authorization": "Bearer " + key})
        if resp.get("output_text"):
            return resp["output_text"]
        return "".join(c.get("text", "") for o in resp.get("output", []) if o.get("type") == "message"
                       for c in o.get("content", []))

    def _claude(self, pair, facts):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY absente")
        body = {"model": self.cfg["modele_claude"], "max_tokens": 200, "system": SYSTEM.format(pair=pair),
                "messages": [{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]}
        resp = _post("https://api.anthropic.com/v1/messages", body,
                     {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return resp["content"][0]["text"]


def _post(url, body, headers):
    headers = dict(headers, **{"content-type": "application/json", "User-Agent": "agent-araignee"})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=60))


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None
