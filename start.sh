#!/bin/zsh
# Lance l'araignée en continu (simulation) + le tableau de bord sur http://localhost:4010
# Les clés sont lues dans .env s'il existe.
cd "$(dirname "$0")"
[ -f .env ] && set -a && source .env && set +a
PYTHONUNBUFFERED=1 python3 -m araignee live
