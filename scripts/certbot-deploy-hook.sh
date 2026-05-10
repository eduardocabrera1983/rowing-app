#!/bin/sh
# ============================================================
# certbot deploy hook — runs after a successful renewal
# ============================================================
# Mounted into the certbot container at:
#   /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
#
# Certbot calls every script in that directory once a cert is
# successfully renewed. RENEWED_LINEAGE / RENEWED_DOMAINS are
# exported by certbot for context.
#
# Requires the certbot container to have:
#   - docker CLI installed (the compose service does `apk add docker-cli`)
#   - /var/run/docker.sock bind-mounted
set -eu

NGINX_CONTAINER="${NGINX_CONTAINER:-nginx-proxy}"

echo "[deploy-hook] certificate renewed for: ${RENEWED_DOMAINS:-?}"
echo "[deploy-hook] reloading nginx container: ${NGINX_CONTAINER}"

if docker exec "${NGINX_CONTAINER}" nginx -s reload; then
    echo "[deploy-hook] nginx reloaded successfully"
else
    echo "[deploy-hook] WARN: failed to reload nginx — falling back to restart"
    docker restart "${NGINX_CONTAINER}"
fi
