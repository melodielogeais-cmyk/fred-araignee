"""L'araignée (crawler) et les agents de lecture : SCAN, JEV, CHIEF.

SCAN  lit la carte 5 min (48 bougies) : range, support, résistance.
JEV   note la confluence sur 5 critères : liquidity sweep, divergence RSI,
      pic de volume, reprise du VWAP, cassure de structure (BOS).
CHIEF donne le biais (LONG / SHORT / WAIT) et décide si le setup « vaut le coup ».
"""


FACTORS = ["liquidity sweep", "rsi divergence", "volume spike", "vwap reclaim", "break of structure"]


class Features:
    """Indicateurs 1 min précalculés une fois pour toute la série (rapide en backtest)."""

    def __init__(self, m1, m5, cfg):
        self.m1, self.m5, self.cfg = m1, m5, cfg
        n = len(m1)
        closes = [c["close"] for c in m1]
        # RSI 14 de Wilder
        self.rsi = [50.0] * n
        g = l = 0.0
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            up, dn = max(d, 0), max(-d, 0)
            if i <= 14:
                g += up / 14
                l += dn / 14
            else:
                g = (g * 13 + up) / 14
                l = (l * 13 + dn) / 14
            if i >= 14:
                self.rsi[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
        # volume moyen (20) et VWAP de la journée UTC
        self.vol_avg = [0.0] * n
        s = 0.0
        for i in range(n):
            s += m1[i]["vol"]
            if i >= 20:
                s -= m1[i - 20]["vol"]
            self.vol_avg[i] = s / min(i + 1, 20)
        self.vwap = [0.0] * n
        pv = vv = 0.0
        day = None
        for i, c in enumerate(m1):
            d = c["t"] // 86400
            if d != day:
                day, pv, vv = d, 0.0, 0.0
            tp = (c["high"] + c["low"] + c["close"]) / 3
            pv += tp * c["vol"]
            vv += c["vol"]
            self.vwap[i] = pv / vv if vv else c["close"]
        # index de la dernière bougie 5 min clôturée pour chaque bougie 1 min
        self.j5 = [0] * n
        j = 0
        for i, c in enumerate(m1):
            while j < len(m5) and m5[j]["t"] + 300 <= c["t"] + 60:
                j += 1
            self.j5[i] = j
        c5 = [x["close"] for x in m5]
        self.ema_fast5 = _ema_series(c5, cfg["chief_ema_rapide"])
        self.ema_slow5 = _ema_series(c5, cfg["chief_ema_lente"])

    def range5(self, i):
        """SCAN : le range des 48 dernières bougies 5 min (hors 20 dernières minutes)."""
        j = self.j5[i]
        k = self.cfg["scan_bougies_5m"]
        zone = self.m5[max(0, j - k - 4):j - 4]
        if len(zone) < k // 2:
            return None
        return min(x["low"] for x in zone), max(x["high"] for x in zone), len(zone)

    def bias(self, i):
        """CHIEF : biais de fond sur le 5 min."""
        j = self.j5[i] - 1
        if j < self.cfg["chief_ema_lente"]:
            return "WAIT"
        f, s = self.ema_fast5[j], self.ema_slow5[j]
        gap = (f - s) / s * 100
        if gap > self.cfg["chief_ecart_min_pct"]:
            return "LONG"
        if gap < -self.cfg["chief_ecart_min_pct"]:
            return "SHORT"
        return "WAIT"


def _ema_series(values, n):
    out, k, e = [], 2 / (n + 1), None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def setup(F, i):
    """Cherche un setup à la bougie i. Renvoie None ou un dict avec la confluence JEV."""
    cfg, m1 = F.cfg, F.m1
    if i < 60:
        return None
    rg = F.range5(i)
    if not rg:
        return None
    support, resistance, read = rg
    win = cfg["sweep_fenetre_1m"]
    seg = m1[i - win + 1:i + 1]
    lo_i = min(range(i - win + 1, i + 1), key=lambda k: m1[k]["low"])
    hi_i = max(range(i - win + 1, i + 1), key=lambda k: m1[k]["high"])
    lo, hi = m1[lo_i]["low"], m1[hi_i]["high"]
    down = (support - lo) / support * 100
    up = (hi - resistance) / resistance * 100
    close = m1[i]["close"]

    if cfg["sweep_min_pct"] <= down <= cfg["sweep_max_pct"] and close > support:
        side, level, depth, ext_i = "long", support, down, lo_i
    elif cfg["autoriser_short"] and cfg["sweep_min_pct"] <= up <= cfg["sweep_max_pct"] and close < resistance:
        side, level, depth, ext_i = "short", resistance, up, hi_i
    else:
        return None
    long = side == "long"
    ext = m1[ext_i]["low"] if long else m1[ext_i]["high"]

    # 2. divergence RSI : nouveau plus bas du prix, mais RSI plus haut qu'au plus bas précédent
    back = m1[max(0, ext_i - cfg["divergence_recul_1m"]):max(0, ext_i - 3)]
    div = False
    rsi_prev = rsi_now = F.rsi[ext_i]
    if back:
        base = max(0, ext_i - cfg["divergence_recul_1m"])
        if long:
            k = min(range(len(back)), key=lambda x: back[x]["low"])
            rsi_prev = F.rsi[base + k]
            div = ext <= back[k]["low"] * 1.0005 and rsi_now > rsi_prev + 2
        else:
            k = max(range(len(back)), key=lambda x: back[x]["high"])
            rsi_prev = F.rsi[base + k]
            div = ext >= back[k]["high"] * 0.9995 and rsi_now < rsi_prev - 2

    # 3. pic de volume sur la mèche
    spike = max(c["vol"] for c in seg) / (F.vol_avg[i - win] or 1e-9)

    # 4. reprise du VWAP
    vwap = F.vwap[i]
    reclaim = close > vwap if long else close < vwap

    # 5. cassure de structure : clôture au-delà du dernier sommet (ou creux) mineur
    pivot = m1[max(0, ext_i - cfg["bos_recul_1m"]):ext_i + 1]
    if long:
        ref = max(c["high"] for c in pivot)
        bos = close > ref
    else:
        ref = min(c["low"] for c in pivot)
        bos = close < ref

    checks = {
        "liquidity sweep": True,
        "rsi divergence": div,
        "volume spike": spike >= cfg["volume_pic_x"],
        "vwap reclaim": reclaim,
        "break of structure": bos,
    }
    score = sum(checks.values())
    grade = {5: "A+", 4: "A", 3: "B"}.get(score, "C")
    bias = F.bias(i)
    aligned = (bias == "LONG" and long) or (bias == "SHORT" and not long) or bias == "WAIT"
    worth = score / 5 * (1.0 if aligned else 0.6)
    return {
        "t": m1[i]["t"], "side": side, "price": close, "level": round(level, 2),
        "depth": round(depth, 3), "extreme": ext, "score": score, "grade": grade, "checks": checks,
        "details": {"liquidity sweep": "{:.2f}%".format(depth),
                    "rsi divergence": "{:.1f} → {:.1f}".format(rsi_prev, rsi_now),
                    "volume spike": "{:.2f}×".format(spike),
                    "vwap reclaim": "{:,.2f}".format(vwap),
                    "break of structure": "{:,.2f}".format(ref)},
        "bias": bias, "aligned": aligned, "worth": round(worth, 2), "candles_read": read,
    }


def scan_note(F, i):
    """La note de SCAN quand rien ne se passe."""
    rg = F.range5(i)
    if not rg:
        return "reading the 5m map"
    s, r, _ = rg
    c = F.m1[i]["close"]
    if c > r:
        return "range broke up"
    if c < s:
        return "range broke down"
    pos = (c - s) / (r - s) if r > s else 0.5
    return "sweep under support" if pos < 0.25 else "near resistance" if pos > 0.75 else "mid-range, waiting"


def crawler_note(sig):
    where = "under support" if sig["side"] == "long" else "over resistance"
    return "sweep {:.2f}% {} · {} of 5 on 5m · {}".format(sig["depth"], where, sig["score"], sig["side"])


def context(F, i):
    """Résumé du marché envoyé au cerveau (Grok)."""
    m1, m5, j = F.m1, F.m5, F.j5[i]
    price = m1[i]["close"]

    def chg(n):
        return round((price / m5[j - n]["close"] - 1) * 100, 2) if j >= n else None

    return {"prix": price, "variation_1h_pct": chg(12), "variation_4h_pct": chg(48),
            "rsi_1m": round(F.rsi[i], 1), "vwap": round(F.vwap[i], 2), "biais_chief": F.bias(i),
            "dernieres_bougies_5m_ohlc": [[round(x["open"]), round(x["high"]), round(x["low"]), round(x["close"])]
                                          for x in m5[max(0, j - 8):j]]}
