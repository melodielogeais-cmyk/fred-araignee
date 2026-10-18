#!/bin/zsh
# Installe la clé API Grok (xAI) depuis le presse-papiers, sans l'afficher :
#   1. lance : ./set-key.sh   2. dans les 3 minutes, copie la clé sur console.x.ai
# Elle est enregistrée dans .env (Fred du Mac) et dans les secrets GitHub (Fred en ligne).
cd "$(dirname "$0")"
echo "⏳ Copie maintenant ta clé Grok (icône copier sur la page API keys). J'attends 3 minutes…"
KEY=""
for i in $(seq 1 180); do
  C="$(pbpaste | tr -d '\r\n ')"
  if [[ "$C" =~ '^[A-Za-z0-9_-]{30,200}$' ]]; then KEY="$C"; break; fi
  sleep 1
done
if [ -z "$KEY" ]; then
  echo "❌ Aucune clé copiée en 3 minutes. Relance le script, puis copie la clé."
  exit 1
fi
printf "" | pbcopy  # on vide le presse-papiers : la clé n'y traîne pas
CODE=$(curl -s -o /dev/null -w "%{http_code}" https://api.x.ai/v1/models -H "Authorization: Bearer $KEY")
if [ "$CODE" != "200" ]; then
  echo "❌ L'API Grok refuse cette clé (HTTP $CODE). Crée une clé « API » sur console.x.ai (pas une clé Cursor/agent) et vérifie le crédit."
  exit 1
fi
grep -v '^XAI_API_KEY=' .env 2>/dev/null > .env.tmp; echo "XAI_API_KEY=$KEY" >> .env.tmp; mv .env.tmp .env; chmod 600 .env
PREV=$(gh auth status 2>&1 | grep -B1 "Active account: true" | head -1 | sed -E 's/.*account ([^ ]+).*/\1/')
gh auth switch -u melodielogeais-cmyk >/dev/null 2>&1
printf "%s" "$KEY" | gh secret set XAI_API_KEY -R melodielogeais-cmyk/fred-araignee
[ -n "$PREV" ] && gh auth switch -u "$PREV" >/dev/null 2>&1
echo "✅ Clé Grok valide, enregistrée dans .env et dans les secrets GitHub (non affichée)."
