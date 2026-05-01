#!/bin/bash
# TradeZen VPS setup — DigitalOcean Ubuntu 22.04
# Run as root: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

APP_DIR="/opt/tradezen"
APP_USER="tradezen"

echo "==> Updating packages"
apt-get update -y && apt-get upgrade -y

# ── Node.js 20 ────────────────────────────────────────────────────────────────
echo "==> Installing Node.js 20"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# ── Python 3.12 ───────────────────────────────────────────────────────────────
echo "==> Installing Python 3.12"
apt-get install -y python3.12 python3.12-venv python3-pip

# Make python3 point to 3.12
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# ── Nginx ─────────────────────────────────────────────────────────────────────
echo "==> Installing nginx"
apt-get install -y nginx

# ── lsof (used by launcher to find PIDs by port) ─────────────────────────────
apt-get install -y lsof

# ── PM2 ───────────────────────────────────────────────────────────────────────
echo "==> Installing PM2"
npm install -g pm2

# ── App user & directory ──────────────────────────────────────────────────────
echo "==> Creating app user and directory"
id -u $APP_USER &>/dev/null || useradd -m -s /bin/bash $APP_USER
mkdir -p $APP_DIR
chown -R $APP_USER:$APP_USER $APP_DIR

echo ""
echo "==> Base setup complete. Next steps:"
echo ""
echo "  1. Upload your project to $APP_DIR"
echo "     (from your local machine):"
echo "     rsync -avz --exclude node_modules --exclude __pycache__ \\"
echo "       ./ root@YOUR_DROPLET_IP:$APP_DIR/"
echo ""
echo "  2. SSH into the droplet and run:"
echo "     cd $APP_DIR"
echo "     npm install --production"
echo "     python3 -m pip install -r ai_engine/requirements.txt"
echo ""
echo "  3. Set launcher credentials (edit ecosystem.config.js or use env):"
echo "     export LAUNCHER_USER=admin"
echo "     export LAUNCHER_PASS=YourStrongPassword"
echo ""
echo "  4. Start with PM2:"
echo "     pm2 start ecosystem.config.js --env production"
echo "     pm2 save"
echo "     pm2 startup   # follow the printed command to enable on reboot"
echo ""
echo "  5. Configure nginx:"
echo "     cp deploy/nginx.conf /etc/nginx/sites-available/tradezen"
echo "     ln -s /etc/nginx/sites-available/tradezen /etc/nginx/sites-enabled/"
echo "     rm -f /etc/nginx/sites-enabled/default"
echo "     nginx -t && systemctl reload nginx"
echo ""
echo "  6. Firewall — allow only HTTP + SSH, block everything else:"
echo "     ufw allow OpenSSH"
echo "     ufw allow 'Nginx HTTP'"
echo "     ufw enable"
echo ""
echo "  7. Access the launcher via SSH tunnel (most secure):"
echo "     ssh -L 9999:127.0.0.1:9999 root@YOUR_DROPLET_IP"
echo "     Then open http://localhost:9999 in your browser"
echo ""
echo "  8. Optional — add HTTPS once domain is pointed at the droplet:"
echo "     apt-get install -y certbot python3-certbot-nginx"
echo "     certbot --nginx -d yourdomain.com"
