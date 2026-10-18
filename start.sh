#!/bin/zsh
# Lance l'araignée en continu (simulation) + le tableau de bord sur http://localhost:4010
# Les clés sont lues dans .env par Fred lui-même (jamais exécuté).
cd "$(dirname "$0")"
PYTHONUNBUFFERED=1 python3 -m araignee live
