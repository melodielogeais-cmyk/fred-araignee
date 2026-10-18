#!/bin/zsh
# Installe la clé API Grok sans l'afficher : une fenêtre s'ouvre, on y colle la clé, c'est tout.
# Elle est vérifiée, puis enregistrée dans .env (Fred du Mac) et dans les secrets GitHub (Fred en ligne).
cd "$(dirname "$0")"
KEY=$(osascript -e 'text returned of (display dialog "Colle ici ta clé API Grok (elle restera masquée) :" default answer "" with hidden answer with title "Fred 🕷 · clé Grok" buttons {"Annuler","Installer"} default button "Installer")' 2>/dev/null | tr -d '\r\n ')
if [ -z "$KEY" ]; then echo "Annulé."; exit 1; fi
if [[ ! "$KEY" =~ '^[A-Za-z0-9_-]{30,255}$' ]]; then echo "❌ Ce n'est pas une clé API valide."; exit 1; fi
RESP=$(curl -s -w "\n%{http_code}" https://api.x.ai/v1/responses -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" -d '{"model":"grok-4.7","input":"Réponds juste: ok"}')
CODE=$(echo "$RESP" | tail -1)
if [ "$CODE" != "200" ]; then
  echo "❌ Grok refuse la clé (HTTP $CODE) : $(echo "$RESP" | head -1 | cut -c1-200)"
  exit 1
fi
grep -v '^XAI_API_KEY=' .env 2>/dev/null > .env.tmp; echo "XAI_API_KEY=$KEY" >> .env.tmp; mv .env.tmp .env; chmod 600 .env
PREV=$(gh auth status 2>&1 | grep -B1 "Active account: true" | head -1 | sed -E 's/.*account ([^ ]+).*/\1/')
gh auth switch -u melodielogeais-cmyk >/dev/null 2>&1
printf "%s" "$KEY" | gh secret set XAI_API_KEY -R melodielogeais-cmyk/fred-araignee
[ -n "$PREV" ] && gh auth switch -u "$PREV" >/dev/null 2>&1
echo "✅ Clé Grok valide et installée (Mac + en ligne). Elle n'a pas été affichée."
