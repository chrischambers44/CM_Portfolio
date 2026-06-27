# C&M Portfolio Management System

Flask + SQLite property management application for Chambers & Morgan Ltd.

## Features

- Netflix-style login with user profiles
- Property register (rental, personal, company, vehicles)
- Compliance dashboard with traffic-light expiry tracking
- Task manager (replaces AppSheet)
- Inspection visit log
- Expense & mileage tracking
- Contact directory with ratings
- Vehicle compliance tracking
- EstateIQ financial intelligence integration (Netlify)
- Vault placeholder for sensitive credentials

## Setup on ChambersPi

### 1. Clone the repository

```bash
cd /home/chrischambers44/chamberspi
git clone https://github.com/chrischambers44/ChrAsh-Portfolio portfolio
cd portfolio
```

### 2. Build and start Docker

```bash
docker-compose up -d --build
```

### 3. Create the database

```bash
docker exec portfolio python -c "
from app import app, db, create_default_users
with app.app_context():
    db.create_all()
    create_default_users()
"
```

### 4. Import AppSheet data (optional)

Export your AppSheet tables as CSV files and place them in `data/imports/`:

```
data/imports/
├── properties.csv
├── contacts.csv
├── tasks.csv
├── documents.csv
├── visits.csv
└── expenses.csv
```

Then run the migration:

```bash
docker exec portfolio python migrate.py
```

### 5. Configure Cloudflare Tunnel

Add to `/etc/cloudflared/config.yml`:

```yaml
- hostname: portfolio.chrischambers.com
  service: http://localhost:5200
```

Restart cloudflared:
```bash
sudo systemctl restart cloudflared
```

## Default Logins

| User | Password |
|------|----------|
| chris | chambers2026 |
| ash | morgan2026 |

**Change these immediately after first login.**

## Port

5200 (consistent with existing Pi app convention)

## Stack

- Flask 3.0 + SQLAlchemy + Flask-Login
- SQLite (database in `instance/portfolio.db`)
- Docker container
- Cloudflare Tunnel → portfolio.chrischambers.com

## Updating

```bash
git pull
docker-compose up -d --build
```
