#!/bin/zsh
# Installe la clé API Grok (xAI) depuis le presse-papiers, sans l'afficher :
#   1. copie la clé sur console.x.ai  2. lance : ./set-key.sh
# Elle est enregistrée dans .env (Fred du Mac) et dans les secrets GitHub (Fred en ligne).
cd "$(dirname "$0")"
KEY="$(pbpaste | tr -d '\r\n ')"
if [[ ! "$KEY" =~ '^[A-Za-z0-9_-]{30,200}$' ]]; then
  echo "❌ Le presse-papiers ne contient pas une clé API (copie la clé sur la page API keys, puis relance)."
  exit 1
fi
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
