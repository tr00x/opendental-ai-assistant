# Open Dental AI Assistant

AI-powered daily appointment briefing and dashboard for Open Dental — pulls schedules from MySQL and generates morning briefings via Claude.

---

## What it does

- Connects to your Open Dental MySQL database
- Pulls today's scheduled appointments (patients, procedures, broken history, new patients)
- Generates a warm professional morning briefing via Claude AI
- Serves a web dashboard and kiosk view via Flask

---

## Requirements

- Python 3.10+
- Network access to your Open Dental MySQL server
- Anthropic API key

---

## Setup

### 1. Install dependencies

```bash
pip install anthropic flask mysql-connector-python python-dotenv python-crontab
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
DB_HOST=mainserver
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=opendental
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

---

## Usage

### CLI

```bash
# JSON output for today
python main.py

# JSON output for a specific date
python main.py --date 2025-08-15

# AI briefing for today (uses Anthropic API credits)
python main.py --briefing

# AI briefing for a specific date
python main.py --briefing --date 2025-08-15
```

### Web dashboard

```bash
python server.py
# Open http://localhost:5000
```

---

## Diagnostic tests

`test_db.py` connects to your database, inspects the schema, and dumps results as JSON — useful before running the full briefing.

```bash
# Basic run — queries today's appointments
python test_db.py

# Query a specific date
python test_db.py --date 2025-08-15

# Look back 14 days for recent data
python test_db.py --days 14

# Pure JSON output
python test_db.py --json-only > results.json
```

---

## Scheduling

### Linux / macOS

```bash
# Install 8:00 AM daily cron job
python scheduler.py

# Check status
python scheduler.py --status

# Remove
python scheduler.py --remove
```

### Windows

Use **Task Scheduler**:
1. *Create Basic Task* → Trigger: Daily at 8:00 AM
2. Action: Start a program
   - Program: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\path\to\project\`

---

## Output files

| File | Contents |
|---|---|
| `logs/YYYY-MM-DD.txt` | Full AI briefing for that day |
| `logs/app.log` | Operational logs (connection, token usage, errors) |
| `logs/cron.log` | stdout/stderr from scheduled runs |

---

## AptStatus reference

| Value | Meaning |
|---|---|
| 1 | Scheduled ← queried by the briefing |
| 2 | Complete |
| 5 | Broken / Missed ← used for broken-history flag |
| 6 | Unscheduled |
