#!/bin/bash
# QuickWrite — One-click Alibaba Cloud deployment script
# Run on a fresh Ubuntu 22.04 ECS instance

set -e

echo "========================================"
echo " QuickWrite Deployment"
echo "========================================"

APP_DIR="/home/ubuntu/quickwrite"
GIT_REPO="https://github.com/MilycXu0/quickwrite"

# 1. System updates & packages
echo "[1/6] Installing system packages..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv nginx git

# 2. Clone code
echo "[2/6] Cloning code..."
cd /home/ubuntu
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$GIT_REPO" "$APP_DIR"
fi
cd "$APP_DIR"

# 3. Install Python dependencies
echo "[3/6] Installing Python dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 4. Create directories
echo "[4/6] Setting up directories..."
mkdir -p data knowledge output logs

# 5. Configure .env
echo "[5/6] Configuring environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  PLEASE EDIT .env and set your ANTHROPIC_API_KEY:"
    echo "    nano $APP_DIR/.env"
fi

# 6. Setup systemd service
echo "[6/6] Installing systemd service..."
sudo cp deploy/quickwrite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable quickwrite
sudo systemctl restart quickwrite

echo ""
echo "========================================"
echo " Deployment complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Set API key:  nano $APP_DIR/.env"
echo "  2. Check status:  sudo systemctl status quickwrite"
echo "  3. View logs:     sudo journalctl -u quickwrite -f"
echo "  4. Setup Nginx:   sudo cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/quickwrite"
echo "                    sudo ln -s /etc/nginx/sites-available/quickwrite /etc/nginx/sites-enabled/"
echo "                    sudo nginx -t && sudo systemctl restart nginx"
echo ""
echo "  App running at:  http://YOUR-ECS-IP:8080"
echo "========================================"
