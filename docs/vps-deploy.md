# VPS Deployment Guide

> **Target OS:** Ubuntu 22.04 LTS (2 vCPU / 4 GB RAM minimum)  
> **Result:** HTTPS trading bot accessible at `https://your-domain.com`, managed via UI + Telegram.

---

## Prerequisites

| What | Where to get |
|------|-------------|
| VPS with Ubuntu 22.04 | DigitalOcean / Hetzner / Vultr (~$6–12/month) |
| Domain name | Namecheap / Cloudflare |
| A record pointing to VPS IP | Your DNS provider |
| Bybit / Binance API key pair | Exchange settings → API Management |
| Telegram bot token + chat ID | [@BotFather](https://t.me/BotFather) / [@userinfobot](https://t.me/userinfobot) |

---

## 1. Prepare the VPS

```bash
# Connect
ssh root@YOUR_VPS_IP

# Update system
apt update && apt upgrade -y

# Install Docker + Compose plugin
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | tee /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify
docker compose version   # should print v2.x.x

# Install Caddy
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy -y
```

---

## 2. Firewall

```bash
ufw allow OpenSSH
ufw allow 80/tcp      # HTTP (Caddy → HTTPS redirect)
ufw allow 443/tcp     # HTTPS
ufw enable
ufw status
```

**Do NOT** open port 8000. The API is only reachable internally through Docker.

---

## 3. Clone the repo

```bash
cd /opt
git clone https://github.com/YOUR_USER/trading-claude.git
cd trading-claude
```

---

## 4. Configure secrets

```bash
cp .env.example .env
nano .env          # or: vim .env
```

Fill in every variable. Minimum required:

```env
# REQUIRED
BOT_API_SECRET=<run: openssl rand -hex 32>

# Exchange (leave blank for paper-only mode)
EXCHANGE_NAME=bybit
EXCHANGE_API_KEY=<your-key>
EXCHANGE_API_SECRET=<your-secret>

# Telegram (optional but recommended)
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>

# CORS — add your domain so the browser can talk to the API
ALLOWED_ORIGINS=https://trading.example.com
```

```bash
# Protect the secrets file
chmod 600 .env
```

---

## 5. Configure Caddy

```bash
# Copy the Caddyfile and edit your domain
cp Caddyfile /etc/caddy/Caddyfile
nano /etc/caddy/Caddyfile
# Replace trading.example.com with your actual domain

# Create log directory
mkdir -p /var/log/caddy

# Reload Caddy
systemctl reload caddy
systemctl status caddy    # should show "active (running)"
```

---

## 6. Build and start the containers

```bash
cd /opt/trading-claude

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build
```

First build takes ~3–5 minutes. After that:

```bash
# Check all services are healthy
docker compose ps

# Tail API logs
docker compose logs -f api

# Tail frontend logs
docker compose logs -f frontend
```

---

## 7. Verify HTTPS

```bash
# From your local machine:
curl -I https://trading.example.com/api/health
# Should return: HTTP/2 200  {"status":"ok","version":"3.0.0"}

# Open in browser:
# https://trading.example.com  → React UI
# https://trading.example.com/api/docs  → Swagger (needs X-API-Key)
```

---

## 8. First login

1. Open `https://trading.example.com` in your browser
2. A modal asks for your **API Key** — paste the value of `BOT_API_SECRET` from `.env`
3. Key is saved in `localStorage` — you won't be asked again on this browser

---

## 9. Systemd auto-start (Docker already handles this, but to be explicit)

```bash
# Make sure Docker starts on boot
systemctl enable docker

# Make Caddy start on boot (already enabled by the apt install)
systemctl enable caddy
```

For the compose project itself, create a systemd unit:

```bash
cat > /etc/systemd/system/trading-bot.service << 'EOF'
[Unit]
Description=Trading Bot (Docker Compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/trading-claude
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable trading-bot.service
```

---

## Updating the bot

```bash
cd /opt/trading-claude
git pull

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build api frontend

# Rolling restart (zero downtime for the frontend):
docker compose restart frontend
```

---

## Database backup

The SQLite database lives in the `app-data` Docker volume.

```bash
# Manual backup
docker run --rm \
  -v trading-claude_app-data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/trading-db-$(date +%Y%m%d-%H%M).tar.gz /data

# Automated daily backup via cron:
(crontab -l 2>/dev/null; echo "0 3 * * * cd /opt/trading-claude && \
  docker run --rm \
    -v trading-claude_app-data:/data \
    -v /opt/trading-claude/backups:/backup \
    alpine tar czf /backup/trading-db-\$(date +\%Y\%m\%d).tar.gz /data") | crontab -
```

---

## Monitoring commands

```bash
# Bot status via API
curl -s -H "X-API-Key: $BOT_API_SECRET" \
  https://trading.example.com/api/bot/status | python3 -m json.tool

# System metrics
curl -s -H "X-API-Key: $BOT_API_SECRET" \
  https://trading.example.com/api/system/metrics | python3 -m json.tool

# Recent events
curl -s -H "X-API-Key: $BOT_API_SECRET" \
  "https://trading.example.com/api/bot/events?limit=10" | python3 -m json.tool

# Container resource usage
docker stats --no-stream

# Disk usage breakdown
df -h
docker system df
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `502 Bad Gateway` from Caddy | `docker compose ps` — is frontend healthy? |
| API returns 403 | Wrong API key in browser localStorage — click 🔑 in the UI |
| Bot won't start (live mode) | `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` not set in `.env` |
| Telegram alerts not working | Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` |
| Disk full | Run `docker system prune -f`; check `data/bot.log` rotation |
| Let's Encrypt fails | Domain A record not pointing to VPS IP; port 80 blocked by firewall |

---

## Security checklist

- [ ] `BOT_API_SECRET` is a random 32-byte hex string (not a dictionary word)
- [ ] `.env` has `chmod 600`
- [ ] API port 8000 is NOT open in `ufw` (`ufw status` should not show it)
- [ ] Exchange API key has **trade-only** permissions — no withdrawals
- [ ] Testnet is disabled in `config.yaml` (`testnet: false`) only when you're ready for real money
- [ ] Telegram bot only responds to your `TELEGRAM_CHAT_ID`
- [ ] Regular DB backups are set up (cron above)
