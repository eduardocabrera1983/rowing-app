#!/bin/bash
# ============================================================
# deploy.sh — Full EC2 deployment script for Rowing App
# Run this on a fresh Ubuntu 22.04+ EC2 instance
# ============================================================
set -euo pipefail

DOMAIN="rowing-data.com"
REPO_URL="https://github.com/eduardocabrera1983/rowing-app.git"
APP_DIR="/opt/rowing-app"

echo "═══════════════════════════════════════════"
echo " Concept2 Rowing App — EC2 Deployment"
echo "═══════════════════════════════════════════"

# ── 1. System updates ──
echo ""
echo "▸ [1/6] Updating system packages ..."
sudo apt-get update -y
sudo apt-get upgrade -y

# ── 2. Install Docker ──
echo ""
echo "▸ [2/6] Installing Docker ..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out/in for group changes."
else
    echo "  Docker already installed."
fi

# Ensure Docker Compose plugin is available
if ! docker compose version &> /dev/null; then
    echo "  Installing Docker Compose plugin ..."
    sudo apt-get install -y docker-compose-plugin
fi

# ── 3. Clone repository ──
echo ""
echo "▸ [3/6] Cloning repository ..."
if [ -d "$APP_DIR" ]; then
    echo "  Directory exists — pulling latest changes ..."
    cd "$APP_DIR"
    sudo git pull origin main
else
    sudo git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
sudo chown -R "$USER":"$USER" "$APP_DIR"

# ── 4. Create .env file ──
echo ""
echo "▸ [4/6] Setting up environment ..."
if [ ! -f "$APP_DIR/.env" ]; then
    echo "  Creating .env file — you need to fill in your Concept2 credentials!"
    cat > "$APP_DIR/.env" << 'ENVEOF'
# Concept2 OAuth2 — get from https://log.concept2.com/developers/keys
C2_CLIENT_ID=your_client_id_here
C2_CLIENT_SECRET=your_client_secret_here
C2_REDIRECT_URI=https://rowing-data.com/auth/callback
C2_SCOPE=user:read,results:read

# Concept2 API
C2_API_BASE_URL=https://log.concept2.com
C2_API_VERSION=v1

# App Settings
APP_SECRET_KEY=$(openssl rand -hex 32)
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=false
LOG_LEVEL=INFO
ENVEOF
    echo ""
    echo "  ╔═══════════════════════════════════════════════════╗"
    echo "  ║  IMPORTANT: Edit .env with your Concept2 keys!   ║"
    echo "  ║  nano /opt/rowing-app/.env                       ║"
    echo "  ╚═══════════════════════════════════════════════════╝"
    echo ""
    read -p "  Press Enter after editing .env (or Ctrl+C to exit) ..."
else
    echo "  .env already exists — keeping current values."
fi

# ── 5. Build & start containers ──
echo ""
echo "▸ [5/6] Building and starting containers ..."
cd "$APP_DIR"
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d

echo "  Waiting for services to start ..."
sleep 10

# Quick health check
if curl -s -o /dev/null -w "%{http_code}" "http://localhost" | grep -q "200\|302"; then
    echo "  ✔ App is responding!"
else
    echo "  ⚠ App may still be starting. Check: docker compose -f docker-compose.prod.yml logs"
fi

# ── 6. SSL setup ──
echo ""
echo "▸ [6/6] SSL Certificate ..."
echo "  Before obtaining SSL, make sure:"
echo "    1. Your domain ($DOMAIN) points to this server's public IP"
echo "    2. Ports 80 and 443 are open in Security Group"
echo ""
read -p "  Enter your email for Let's Encrypt (or 'skip' to do later): " SSL_EMAIL

if [ "$SSL_EMAIL" != "skip" ]; then
    bash "$APP_DIR/scripts/init-ssl.sh" "$SSL_EMAIL"
else
    echo "  Skipping SSL. Run later: bash /opt/rowing-app/scripts/init-ssl.sh your@email.com"
fi

echo ""
echo "═══════════════════════════════════════════"
echo " ✔ Deployment complete!"
echo "═══════════════════════════════════════════"
echo ""
echo " App URL:     http://$DOMAIN  (https after SSL)"
echo " Logs:        cd $APP_DIR && docker compose -f docker-compose.prod.yml logs -f"
echo " Restart:     cd $APP_DIR && docker compose -f docker-compose.prod.yml restart"
echo " Update:      cd $APP_DIR && git pull && docker compose -f docker-compose.prod.yml up -d --build"
echo ""
echo " Don't forget to update your Concept2 OAuth redirect URI to:"
echo "   https://$DOMAIN/auth/callback"
echo ""
