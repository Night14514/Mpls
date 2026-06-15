# Production-Grade Deployment Guide

This guide covers deploying the protected Telegram bot to a single VPS with production-grade security architecture.

## Architecture Overview

The system uses a layered architecture with IP protection:

- **Application Layer**: Thin aiogram routing layer (`handlers/`, `relay/`)
- **Domain Layer**: Business logic compiled to binary modules (`core/`, `services/`)
- **Data Layer**: Database abstraction (`db/`)
- **Security Layer**: Integrity checks, anti-debug (logging-only), secret management

## Protection Features

1. **Compiled Business Logic**: Critical modules compiled with Cython (.so/.pyd)
2. **Integrity Verification**: SHA-256 checksums detect tampering
3. **Anti-Debug**: Lightweight detection with logging (no self-destruct)
4. **Secret Management**: Environment variables only
5. **Stable Runtime**: No experimental VM or self-destruct mechanisms

## Prerequisites

- VPS with Ubuntu 20.04+ or similar Linux distribution
- Python 3.9+
- SQLite (or PostgreSQL if configured)
- 1GB RAM minimum, 2GB recommended
- 20GB disk space

## Deployment Steps

### 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3 python3-pip python3-venv git sqlite3

# Create dedicated user
sudo useradd -m -s /bin/bash botuser
sudo su - botuser
```

### 2. Application Setup

```bash
# Clone repository (adjust URL)
git clone https://github.com/yourusername/telegram-bot.git
cd telegram-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install Cython  # For compilation
```

### 3. Configuration

```bash
# Create environment file
cp .env.example .env

# Edit configuration
nano .env
```

Required `.env` variables:
```bash
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=123456789,987654321
DATABASE_URL=sqlite+aiosqlite:///data/database.db
LOG_LEVEL=INFO

# Optional: Payment providers
STARS_ENABLED=true
CRYPTO_ENABLED=true
CRYPTO_TOKEN=your_crypto_bot_token
CRYPTO_API_URL=https://pay.crypt.bot/api
CRYPTO_POLL_INTERVAL=30
```

### 4. Build Pipeline (Compile Business Logic)

```bash
# Run production build pipeline
python build_production.py

# This will:
# - Compile critical modules to .so/.pyd files
# - Generate integrity.json with SHA-256 checksums
# - Create production structure in build_output/
# - Backup original .py files to .py.backup
```

Build output structure:
```
build_output/
├── core/                  # Compiled business logic
│   ├── order_engine.so    # Compiled module
│   └── ...
├── services/              # Compiled services
│   ├── order_service.so
│   └── ...
├── integrity.json         # SHA-256 checksums
├── main.py                # Entry point
├── config.py              # Configuration
└── ...                    # Other runtime files
```

### 5. Production Deployment

```bash
# Move build output to production directory
sudo mkdir -p /opt/telegram-bot
sudo cp -r build_output/* /opt/telegram-bot/
sudo chown -R botuser:botuser /opt/telegram-bot

# Create necessary directories
sudo -u botuser mkdir -p /opt/telegram-bot/data
sudo -u botuser mkdir -p /opt/telegram-bot/logs

# Copy environment file
sudo cp .env /opt/telegram-bot/
sudo chown botuser:botuser /opt/telegram-bot/.env
sudo chmod 600 /opt/telegram-bot/.env
```

### 6. Systemd Service Setup

```bash
# Copy systemd service file
sudo cp deploy/telegram-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable telegram-bot

# Start service
sudo systemctl start telegram-bot

# Check status
sudo systemctl status telegram-bot
```

### 7. Monitoring and Logs

```bash
# View real-time logs
sudo journalctl -u telegram-bot -f

# View recent logs
sudo journalctl -u telegram-bot -n 50

# View logs since specific time
sudo journalctl -u telegram-bot --since "1 hour ago"
```

## Security Best Practices

### 1. Secret Management

- **NEVER** commit secrets to git
- Use environment variables for all sensitive data
- Set proper file permissions: `chmod 600 .env`
- Rotate keys periodically
- Use different tokens for development/production

### 2. Firewall Configuration

```bash
# Configure ufw (if using)
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 3. Database Security

```bash
# Set proper permissions on database directory
sudo chmod 750 /opt/telegram-bot/data
sudo chmod 640 /opt/telegram-bot/data/database.db

# Regular backups
sudo crontab -e
# Add: 0 2 * * * sqlite3 /opt/telegram-bot/data/database.db ".backup /opt/backups/db_$(date +\%Y\%m\%d).db"
```

### 4. Updates and Maintenance

```bash
# To update the bot:
# 1. Pull changes
git pull origin main

# 2. Rebuild
python build_production.py

# 3. Deploy
sudo cp -r build_output/* /opt/telegram-bot/
sudo systemctl restart telegram-bot

# 4. Verify status
sudo systemctl status telegram-bot
```

## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status telegram-bot

# View detailed logs
sudo journalctl -u telegram-bot -n 100 --no-pager

# Check configuration
sudo -u botuser python /opt/telegram-bot/main.py --dev
```

### Integrity check failures

```bash
# Integrity checks are logged but don't crash the system
# Check logs for anomalies:
sudo journalctl -u telegram-bot | grep -i integrity

# If modules are corrupted, rebuild:
python build_production.py
sudo cp -r build_output/* /opt/telegram-bot/
sudo systemctl restart telegram-bot
```

### Database connection issues

```bash
# Check database file permissions
ls -la /opt/telegram-bot/data/

# Verify DATABASE_URL in .env
sudo cat /opt/telegram-bot/.env | grep DATABASE_URL

# Test database connection manually
sudo -u botuser python -c "import aiosqlite; asyncio.run(aiosqlite.connect('/opt/telegram-bot/data/database.db'))"
```

## Development vs Production

### Development Mode

```bash
# Run without protections and compilation
python main.py --dev
```

- Uses original Python source files
- No integrity checks
- No anti-debug protections
- Full error output

### Production Mode

```bash
# Run with compiled modules and protections
python main.py
# or via systemd
sudo systemctl start telegram-bot
```

- Uses compiled binary modules
- Integrity verification at startup
- Anti-debug monitoring (logging-only)
- Production-grade error handling

### Legacy Mode

```bash
# Run with old architecture (backward compatibility)
python main.py --legacy
```

- Uses original architecture
- No compilation or new protections
- For emergency fallback only

## Rollback Procedure

If something goes wrong with the compiled version:

```bash
# 1. Stop service
sudo systemctl stop telegram-bot

# 2. Restore from backup
sudo cp -r backup/* /opt/telegram-bot/

# 3. Or run in legacy mode
sudo -u botuser python /opt/telegram-bot/main.py --legacy

# 4. Restart service
sudo systemctl start telegram-bot
```

## Performance Optimization

### 1. Database Optimization

```bash
# SQLite optimization is handled in db/connection.py:
# - WAL mode enabled
# - Foreign keys enabled
# - Busy timeout configured
```

### 2. Resource Monitoring

```bash
# Monitor bot resource usage
htop

# Check specific process
ps aux | grep python

# Memory usage
sudo journalctl -u telegram-bot | grep -i memory
```

### 3. Log Rotation

Create `/etc/logrotate.d/telegram-bot`:
```
/opt/telegram-bot/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 botuser botuser
    sharedscripts
    postrotate
        systemctl reload telegram-bot >/dev/null 2>&1 || true
    endscript
}
```

## Backup Strategy

### 1. Database Backups

```bash
# Automated backup script
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Backup database
sqlite3 /opt/telegram-bot/data/database.db ".backup $BACKUP_DIR/db_$DATE.db"

# Backup configuration
cp /opt/telegram-bot/.env $BACKUP_DIR/env_$DATE.backup

# Keep only last 7 days
find $BACKUP_DIR -name "db_*.db" -mtime +7 -delete
find $BACKUP_DIR -name "env_*.backup" -mtime +7 -delete
```

### 2. Application Backups

```bash
# Backup compiled modules and configuration
tar -czf /opt/backups/bot_$(date +%Y%m%d).tar.gz /opt/telegram-bot/
```

## Support and Maintenance

- Check logs regularly for security anomalies
- Monitor integrity check results
- Keep dependencies updated
- Test disaster recovery procedures
- Document any custom modifications

## Security Monitoring

Regular monitoring commands:

```bash
# Check for security anomalies
sudo journalctl -u telegram-bot | grep -i "security anomaly"

# Check integrity verification
sudo journalctl -u telegram-bot | grep -i integrity

# Check for debugger detection
sudo journalctl -u telegram-bot | grep -i debugger

# Monitor failed login attempts
sudo journalctl -u telegram-bot | grep -i failed
```

## Summary

This deployment provides:

✅ **Production-grade IP protection** through compiled modules
✅ **Stable runtime** without self-destruct behavior  
✅ **Integrity verification** to detect tampering
✅ **Lightweight anti-debug** with logging instead of crashing
✅ **Automated deployment** via systemd
✅ **Easy rollback** procedures
✅ **Comprehensive monitoring** and logging

The system maintains 100% functionality while providing enterprise-level security for your business logic.
