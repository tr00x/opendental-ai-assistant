"""
main.py — Entry point for the daily dental appointment briefing.

Usage:
    python main.py                    # JSON output for today (default)
    python main.py --date 2026-02-20  # JSON output for a specific date
    python main.py --briefing         # AI briefing for today (requires API credits)
    python main.py --briefing --date 2026-02-20  # AI briefing for a specific date
"""
import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
REQUIRED_ENV_VARS_DB = ["DB_HOST", "DB_USER", "DB_NAME"]
REQUIRED_ENV_VARS_AI = ["ANTHROPIC_API_KEY"]

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
    )
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(ch)


def _validate_env(require_ai: bool = False) -> None:
    missing = [v for v in REQUIRED_ENV_VARS_DB if not os.environ.get(v)]
    if require_ai:
        missing += [v for v in REQUIRED_ENV_VARS_AI if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        print("Check your .env file.")
        sys.exit(1)


def _save_briefing(text: str, target_date: date) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    dated_file = LOG_DIR / f"{target_date.isoformat()}.txt"
    header = (
        f"Daily Dental Briefing — {target_date.isoformat()} "
        f"(generated {datetime.now().strftime('%H:%M:%S')})\n"
        + "=" * 60
        + "\n\n"
    )
    dated_file.write_text(header + text, encoding="utf-8")
    return dated_file


def _print_header(target_date: date) -> None:
    print("=" * 60)
    print("  DAILY DENTAL BRIEFING (AI)")
    print(f"  Date     : {target_date.strftime('%A, %B %d, %Y')}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


def _print_footer(saved_to: Path) -> None:
    print("\n" + "-" * 60)
    print(f"  Saved to: {saved_to}")
    print("-" * 60 + "\n")


def _json_default(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Dental appointment data tool.")
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Date to fetch data for (default: today).",
    )
    parser.add_argument(
        "--briefing",
        action="store_true",
        help="Generate AI briefing via Claude (requires ANTHROPIC_API_KEY with credits).",
    )
    args = parser.parse_args()

    target_date: date
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got '{args.date}'")
            sys.exit(1)
    else:
        target_date = date.today()

    _setup_logging()
    logger = logging.getLogger(__name__)
    _validate_env(require_ai=args.briefing)

    logger.info("Fetching appointments for %s", target_date)

    try:
        data = db.get_appointment_data(target_date)
    except RuntimeError as exc:
        logger.error("Database error: %s", exc)
        print(f"\nERROR fetching appointments: {exc}\n")
        sys.exit(1)

    # Default mode: JSON output, no AI call
    if not args.briefing:
        output = {
            "date": target_date.isoformat(),
            "appointment_count": len(data["appointments"]),
            "appointments": data["appointments"],
            "broken_history": data["broken_history"],
        }
        print(json.dumps(output, indent=2, default=_json_default, ensure_ascii=False))
        return

    # --briefing mode: call Claude AI
    import briefing as briefing_module

    _print_header(target_date)
    print(f"  Appointments: {len(data['appointments'])}")

    try:
        briefing_text = briefing_module.generate_briefing(data)
    except RuntimeError as exc:
        logger.error("Briefing generation error: %s", exc)
        print(f"\nERROR generating briefing: {exc}\n")
        sys.exit(1)

    saved_to = _save_briefing(briefing_text, target_date)
    logger.info("Briefing saved to %s", saved_to)
    _print_footer(saved_to)


if __name__ == "__main__":
    main()
