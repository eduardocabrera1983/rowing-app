#!/bin/bash
# ============================================================
# init-ssl.sh — Obtain Let's Encrypt SSL certificate
# Run AFTER docker compose is up with HTTP-only nginx config
# ============================================================
set -e

DOMAIN="rowing-data.com"
EMAIL="${1:?Usage: ./scripts/init-ssl.sh your@email.com}"

echo "▸ Requesting SSL certificate for $DOMAIN ..."

docker compose -f docker-compose.prod.yml run --rm certbot \
    certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN"

echo "▸ Certificate obtained! Switching nginx to SSL config ..."
cp nginx/default-ssl.conf nginx/default.conf

echo "▸ Reloading nginx ..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

echo "✔ SSL is live! Visit https://$DOMAIN"
