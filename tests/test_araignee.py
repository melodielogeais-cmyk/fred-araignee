"""Tests rapides sur des bougies synthétiques : python3 -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from araignee.__main__ import load_cfg, simulate  # noqa: E402
from araignee.brain import Brain  # noqa: E402
from araignee.portfolio import Portfolio  # noqa: E402
from araignee.spider import Features, setup  # noqa: E402


def bar(t, o, h, l, c, v=1.0):
    return {"t": t, "open": o, "high": h, "low": l, "close": c, "vol": v}


def market_with_sweep():
    """Un range calme à 100, puis une mèche sous le support et une reprise franche."""
    m1 = []
    t0 = 1_700_000_000
    for i in range(600):
        p = 100 + (0.3 if (i // 7) % 2 else -0.3)
        m1.append(bar(t0 + i * 60, p, p + 0.1, p - 0.1, p))
    t = t0 + 600 * 60
    m1.append(bar(t, 99.8, 99.85, 99.55, 99.6, 1))        # descend
    m1.append(bar(t + 60, 99.6, 99.65, 99.4, 99.5, 6))     # mèche sous le support, gros volume
    m1.append(bar(t + 120, 99.5, 100.6, 99.5, 100.5, 5))   # reprise et cassure
    for k in range(3, 120):
        p = 100.5 + k * 0.02
        m1.append(bar(t + k * 60, p, p + 0.05, p - 0.05, p + 0.01))
    m5 = []
    for j in range(0, len(m1) - 4, 5):
        g = m1[j:j + 5]
        m5.append(bar(g[0]["t"], g[0]["open"], max(x["high"] for x in g), min(x["low"] for x in g),
                      g[-1]["close"], sum(x["vol"] for x in g)))
    return m1, m5


class TestAraignee(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg({"cerveau": "regles", "jev_score_min": 3, "sweep_max_pct": 1.0, "stop_max_pct": 3,
                               "quant_actif": False})

    def test_sweep_detecte(self):
        m1, m5 = market_with_sweep()
        F = Features(m1, m5, self.cfg)
        found = [setup(F, i) for i in range(600, 606)]
        sig = next(s for s in found if s)
        self.assertEqual(sig["side"], "long")
        self.assertTrue(sig["checks"]["liquidity sweep"])

    def test_trade_fictif_et_stop(self):
        m1, m5 = market_with_sweep()
        with tempfile.TemporaryDirectory() as d:
            pf = Portfolio(self.cfg, os.path.join(d, "s.json"), fresh=True)
            pf.quiet = True
            simulate(pf, Brain(self.cfg, pf.s), self.cfg, "BTC-EUR", m1, m5, m1[0]["t"])
            self.assertGreaterEqual(len(pf.s["trades"]) + len(pf.s["positions"]), 1)
            for tr in pf.s["trades"]:
                self.assertLessEqual(tr["notional"], self.cfg["capital_fictif"] * self.cfg["levier"] + 1)

    def test_jamais_au_dela_du_levier(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Portfolio(self.cfg, os.path.join(d, "s.json"), fresh=True)
            pf.quiet = True
            sig = {"side": "long", "price": 100.0, "extreme": 99.999, "score": 5, "grade": "A+"}
            pf.open("BTC-EUR", sig, 0, "test", "règles", 0.9)
            p = pf.s["positions"]["BTC-EUR"]
            self.assertLessEqual(p["notional"], self.cfg["capital_fictif"] * self.cfg["levier"] + 1e-6)

    def test_garde_fou_x2(self):
        cfg = dict(self.cfg, mode="x2", risque_par_trade_pct=2, risque_prudent_pct=1,
                   repli_baisse_pct=8, retour_baisse_pct=4)
        with tempfile.TemporaryDirectory() as d:
            pf = Portfolio(cfg, os.path.join(d, "s.json"), fresh=True)
            pf.quiet = True
            self.assertEqual(pf.risk_mode(), 2)
            pf.s["trades"].append({"pnl": -90.0, "t": 0, "t_exit": 0})  # -9 % du capital de départ
            pf.s["capital"] -= 90.0
            self.assertEqual(pf.risk_mode(), 1)
            self.assertEqual(pf.s["mode_actif"], "prudent")
            pf.s["trades"].append({"pnl": 70.0, "t": 0, "t_exit": 0})  # baisse revenue à 2 %
            pf.s["capital"] += 70.0
            self.assertEqual(pf.risk_mode(), 2)


if __name__ == "__main__":
    unittest.main()
