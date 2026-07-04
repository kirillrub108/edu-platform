#!/usr/bin/env bash
# One-time TLS bootstrap for the Edllm prod stack.
#
# Chicken-and-egg: nginx's :443 server references the Let's Encrypt cert, so it
# won't start before a cert exists — but certbot's http-01 challenge needs nginx
# running on :80. We break the cycle by issuing a throwaway self-signed cert so
# nginx can boot, then replacing it with the real cert via the webroot
# challenge, then reloading nginx.
#
# Run ONCE on the VM, from the directory holding docker-compose.prod.yml, after
# the DNS A record for $DOMAIN points at this VM and .env.prod exists.
#
#   DOMAIN=edllm.ru EMAIL=you@example.com ./deploy/init-letsencrypt.sh
#
# Renewal afterwards is handled by deploy/systemd/certbot-renew.{service,timer}.
set -euo pipefail

DOMAIN="${DOMAIN:-edllm.ru}"
EMAIL="${EMAIL:?Set EMAIL=you@example.com for Let's Encrypt expiry notices}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
# Path INSIDE the certbot/nginx containers (the letsencrypt volume).
LIVE="/etc/letsencrypt/live/${DOMAIN}"
# Set STAGING=1 while testing to avoid Let's Encrypt rate limits.
STAGING_FLAG=""
if [ "${STAGING:-0}" = "1" ]; then
  STAGING_FLAG="--staging"
  echo ">> Using Let's Encrypt STAGING environment"
fi

echo ">> [1/4] Creating a temporary self-signed cert so nginx can start..."
$COMPOSE --profile certbot run --rm --entrypoint sh certbot -c "\
  mkdir -p '${LIVE}' && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout '${LIVE}/privkey.pem' \
    -out '${LIVE}/fullchain.pem' \
    -subj '/CN=${DOMAIN}'"

echo ">> [2/4] Starting nginx (and its deps) with the dummy cert..."
$COMPOSE up -d nginx

echo ">> [3/4] Requesting the real certificate via the webroot challenge..."
# --force-renewal overwrites the dummy. The webroot path matches nginx's
# /.well-known/acme-challenge/ root in nginx/prod.conf.
$COMPOSE --profile certbot run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email "${EMAIL}" --agree-tos --no-eff-email \
  --force-renewal ${STAGING_FLAG} \
  -d "${DOMAIN}"

echo ">> [4/4] Reloading nginx to pick up the real certificate..."
$COMPOSE exec -T nginx nginx -s reload

echo ">> Done. https://${DOMAIN} is now serving a real certificate."
