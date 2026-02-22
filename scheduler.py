"""
scheduler.py — Install or remove the 8 AM daily cron job.

Works on Linux and macOS. Not supported on Windows (use Task Scheduler there).

Usage:
    python scheduler.py           # install the cron job
    python scheduler.py --remove  # remove the cron job
    python scheduler.py --status  # print current job status
"""
import argparse
import os
import platform
import sys
from pathlib import Path

CRON_COMMENT = "dental-daily-briefing"


def _check_platform() -> None:
    if platform.system() == "Windows":
        print("ERROR: python-crontab does not support Windows.")
        print("Use Windows Task Scheduler instead — see README.md for instructions.")
        sys.exit(1)


def _get_paths() -> tuple[str, str, str]:
    """Return (python_executable, main_script_path, log_dir_path)."""
    script_dir = Path(__file__).resolve().parent
    python_exec = sys.executable
    main_script = str(script_dir / "main.py")
    log_dir = str(script_dir / "logs")
    return python_exec, main_script, log_dir


def install_cron() -> None:
    """Create or replace the 8:00 AM daily cron job."""
    from crontab import CronTab  # import here so import error is clear on Windows

    python_exec, main_script, log_dir = _get_paths()
    script_dir = str(Path(main_script).parent)

    os.makedirs(log_dir, exist_ok=True)

    cron = CronTab(user=True)

    # Remove any existing job with our comment tag to avoid duplicates
    removed = cron.remove_all(comment=CRON_COMMENT)
    if removed:
        print(f"Removed {removed} existing job(s) before re-installing.")

    # Build the command: cd to the project dir so relative paths work,
    # then run main.py and append output to logs/cron.log
    command = (
        f"cd {script_dir} && "
        f"{python_exec} {main_script} "
        f">> {log_dir}/cron.log 2>&1"
    )

    job = cron.new(command=command, comment=CRON_COMMENT)
    job.setall("0 8 * * *")  # 08:00 every day

    cron.write()
    print(f"Cron job installed — runs every day at 08:00 AM.")
    print(f"Command : {command}")
    print(f"Cron log: {log_dir}/cron.log")


def remove_cron() -> None:
    """Remove all cron jobs tagged with our comment."""
    from crontab import CronTab

    cron = CronTab(user=True)
    removed = cron.remove_all(comment=CRON_COMMENT)
    cron.write()
    if removed:
        print(f"Removed {removed} cron job(s).")
    else:
        print("No cron job found to remove.")


def show_status() -> None:
    """Print the current cron job (if installed)."""
    from crontab import CronTab

    cron = CronTab(user=True)
    jobs = list(cron.find_comment(CRON_COMMENT))
    if jobs:
        print(f"Found {len(jobs)} installed job(s):")
        for job in jobs:
            print(f"  {job}")
    else:
        print("No cron job currently installed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    _check_platform()

    parser = argparse.ArgumentParser(
        description="Manage the daily dental briefing cron job (Linux / macOS only)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--remove", action="store_true", help="Remove the cron job."
    )
    group.add_argument(
        "--status", action="store_true", help="Show the current cron job status."
    )
    args = parser.parse_args()

    if args.remove:
        remove_cron()
    elif args.status:
        show_status()
    else:
        install_cron()


if __name__ == "__main__":
    main()
