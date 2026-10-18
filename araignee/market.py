"""Données de marché publiques (Coinbase, sans clé) et indicateurs."""
import json
import time
import urllib.request
from datetime import datetime, timezone

API = "https://api.exchange.coinbase.com/products/{}/candles?granularity={}"
MAX = 300  # bougies par requête chez Coinbase


def _get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agent-araignee"})
            return json.load(urllib.request.urlopen(req, timeout=20))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(rows):
    return [{"t": r[0], "low": r[1], "high": r[2], "open": r[3], "close": r[4], "vol": r[5]} for r in rows]


def candles(pair, gran, start=None, end=None):
    """Bougies clôturées, de la plus ancienne à la plus récente."""
    url = API.format(pair, gran)
    if start is not None:
        url += "&start={}&end={}".format(_iso(start), _iso(end))
    out = sorted(_parse(_get(url)), key=lambda c: c["t"])
    now = time.time()
    return [c for c in out if c["t"] + gran <= now]  # on retire la bougie en cours


def history(pair, gran, start, end=None):
    """Toutes les bougies entre start et end (pagination par blocs de 300)."""
    end = end or int(time.time())
    out, t = {}, int(start)
    while t < end:
        stop = min(t + gran * (MAX - 1), end)
        for c in candles(pair, gran, t, stop):
            out[c["t"]] = c
        t = stop + gran
        time.sleep(0.25)  # politesse envers l'API publique
    return [out[k] for k in sorted(out)]


def ema(values, n):
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def atr(cs, n=14):
    trs = []
    for prev, c in zip(cs[-n - 1:-1], cs[-n:]):
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev["close"]), abs(c["low"] - prev["close"])))
    return sum(trs) / len(trs) if trs else 0.0
