# 🕷 Agent araignée : GROKBOT + JEV (simulation)

Reproduction de l'agent montré par @0xGrimmer_ sur X (15/10/2026) : **6 agents + 1 crawler**, qui lisent la carte 5 min et tradent sur le 1 min.
Le crawler laisse **une note d'une ligne avant chaque trade**.

> ⚠️ **Simulation uniquement.** L'argent est fictif, aucun courtier n'est connecté et aucun ordre réel n'est passé. Ce n'est pas un conseil en investissement.

## Les agents

| Agent | Rôle | Dans le code |
|---|---|---|
| **CHIEF** | Biais (LONG / SHORT / WAIT). Ne prend jamais de position. Feu vert si `worth ≥ 0.60` et `conf ≥ 0.55` | `brain.py` (Grok) + `spider.py` (biais EMA 5 min) |
| **SCAN** | Lit les 48 dernières bougies 5 min : range, support, résistance | `spider.py → Features.range5` |
| **VET** | « Is the move real » : profondeur du carnet d'ordres à ±0,3 % (« bids 2.2× asks under price ») | `brain.py → vet_book` (en direct seulement) |
| **SIZE** | Taille calculée sur le stop (risque fixe), plafonnée à 12× isolé, et vérifie « stop far from liq » | `portfolio.py → open` |
| **FILLS** | Exécution simulée, avec glissement et frais | `portfolio.py` |
| **RISK** | Stop derrière la mèche, stop suiveur après +x % (« trail after +0.4% »), « no size up after a red ticket » | `portfolio.py → update` |
| **Crawler / JEV** | Confluence sur 5 critères : liquidity sweep, rsi divergence, volume spike, vwap reclaim, break of structure. 5/5 = setup A+ | `spider.py → setup` |

## Lancer en local
```bash
./set-key.sh                      # copier la clé Grok, puis lancer : elle est vérifiée et installée sans être affichée
./start.sh                        # agent en continu + tableau de bord http://localhost:4010
python3 -m araignee backtest --jours 30     # rejoue 30 jours (règles seules, gratuit)
python3 -m araignee backtest --jours 3 --ia # rejoue avec Grok (coûte des tokens)
python3 -m unittest discover tests
```

## Mise en ligne
**Option 1 : GitHub Actions + Netlify ou Vercel (gratuit, déjà configuré).** `.github/workflows/araignee.yml` tourne toutes les heures. Chaque passage rejoue minute par minute les bougies écoulées depuis le passage précédent, sauvegarde `data/state.json` et met à jour `site/`. Netlify ou Vercel publie **uniquement** `site/` (voir `netlify.toml` et `vercel.json`).
`.github/workflows/autotune.yml` lance l'amélioration continue chaque dimanche.
- Secrets à ajouter dans le dépôt (Settings → Secrets → Actions) : `XAI_API_KEY`, et en option `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID`.

**Option 2 : serveur ou VPS (temps réel, avec VET sur le carnet d'ordres).**
```bash
cp .env.example .env && nano .env   # clés + DASHBOARD_PASSWORD
docker compose up -d --build        # tableau de bord sur le port 4010
```
L'option 2 fonctionne aussi sur Railway, Render ou Fly.io : il suffit de déployer le Dockerfile et de définir les variables d'environnement.

## Réglages
Tout est dans `config.json` : levier, risque par trade, seuils de CHIEF et JEV, stop suiveur, limites par jour.
`tools/optimise.py` cherche de meilleurs réglages sur une période d'entraînement, puis les vérifie à l'aveugle sur une période de test.

## Limites honnêtes
- Le clip d'origine montre **une seule session de 3 h** à 12× de levier. Ça ne prouve pas que la méthode marche dans la durée.
- Un backtest n'est pas une garantie : les frais, le glissement et les périodes de marché différentes changent tout.
- Le crawler rejoue les bougies une fois par heure (GitHub Actions). VET, la lecture du carnet d'ordres, ne fonctionne qu'en mode `live` (option 2).
