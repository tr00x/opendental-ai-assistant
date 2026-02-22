"""
test_db.py — Open Dental MySQL diagnostic tests with full JSON output.

Verifies connectivity, inspects the real schema, and queries appointments.
All results are printed as pretty JSON so you can see exactly what the
database returns before wiring it into the briefing system.

Usage:
    python test_db.py                    # test today's appointments
    python test_db.py --date 2025-08-15  # test a specific date
    python test_db.py --days 14          # look back 14 days for recent data
    python test_db.py --json-only        # suppress human-readable headers
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv()

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print("ERROR: mysql-connector-python not installed.")
    print("       Run: pip install mysql-connector-python")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

APT_STATUS_LABELS: dict[int, str] = {
    1: "Scheduled",
    2: "Complete",
    3: "UnschedList",
    4: "ASAP",
    5: "Broken/Missed",
    6: "Unscheduled",
    7: "Planned",
    8: "PtNote",
    9: "PtNoteCompleted",
}


def _json_default(obj: Any) -> str:
    """Make datetime / date objects JSON-serialisable."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=_json_default, ensure_ascii=False)


def _rows_as_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _section(title: str, verbose: bool) -> None:
    if verbose:
        bar = "=" * 60
        print(f"\n{bar}", file=sys.stderr)
        print(f"  {title}", file=sys.stderr)
        print(bar, file=sys.stderr)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect() -> mysql.connector.connection.MySQLConnection:
    cfg = {
        "host": os.environ.get("DB_HOST", "mainserver"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "opendental"),
        "connect_timeout": 10,
    }
    return mysql.connector.connect(**cfg)


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def test_connection(conn: Any) -> dict[str, Any]:
    """Basic server info — confirms the connection works."""
    cur = conn.cursor()
    cur.execute("SELECT VERSION(), DATABASE(), NOW(), @@global.storage_engine")
    row = cur.fetchone()
    return {
        "status": "ok",
        "mysql_version": row[0],
        "database": row[1],
        "server_time": row[2],
        "default_storage_engine": row[3],
    }


def test_table_exists(conn: Any, tables: list[str]) -> dict[str, bool]:
    """Confirm each required table exists in the database."""
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    existing = {row[0].lower() for row in cur.fetchall()}
    return {t: (t.lower() in existing) for t in tables}


def test_schema(conn: Any, table: str) -> list[dict[str, Any]]:
    """Return DESCRIBE output for a table — reveals real column names and types."""
    cur = conn.cursor()
    cur.execute(f"DESCRIBE `{table}`")
    return [
        {
            "field": row[0],
            "type": row[1],
            "null": row[2],
            "key": row[3],
            "default": row[4],
        }
        for row in cur.fetchall()
    ]


def test_row_counts(conn: Any, tables: list[str]) -> dict[str, int]:
    """Row count per table — quick sanity check that tables have data."""
    counts: dict[str, int] = {}
    cur = conn.cursor()
    for table in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            counts[table] = cur.fetchone()[0]
        except MySQLError as exc:
            counts[table] = f"ERROR: {exc}"
    return counts


def test_aptstatus_distribution(conn: Any) -> list[dict[str, Any]]:
    """Count of appointments per AptStatus — helps verify which statuses exist."""
    cur = conn.cursor()
    cur.execute(
        "SELECT AptStatus, COUNT(*) AS cnt "
        "FROM appointment "
        "GROUP BY AptStatus "
        "ORDER BY AptStatus"
    )
    return [
        {
            "AptStatus": row[0],
            "label": APT_STATUS_LABELS.get(row[0], "Unknown"),
            "count": row[1],
        }
        for row in cur.fetchall()
    ]


def test_upcoming_scheduled_dates(conn: Any, limit: int = 10) -> list[str]:
    """List the next N distinct dates that have scheduled (status=1) appointments.

    Useful for finding a real date to pass to --date when testing.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT DATE(AptDateTime) AS d "
        "FROM appointment "
        "WHERE AptStatus = 1 AND AptDateTime >= NOW() "
        "ORDER BY d ASC "
        "LIMIT %s",
        (limit,),
    )
    return [row[0].isoformat() if row[0] else None for row in cur.fetchall()]


def test_appointments_for_date(
    conn: Any, target_date: date
) -> list[dict[str, Any]]:
    """
    Full JOIN query — exactly what the briefing system uses.
    Returns every scheduled appointment for target_date with patient,
    provider, and operatory details.
    """
    query = """
        SELECT
            a.AptNum,
            a.AptDateTime,
            a.PatNum,
            a.ProvNum,
            a.AptStatus,
            a.ProcDescript,
            a.Op             AS OperatoryNum,
            p.FName          AS PatFName,
            p.LName          AS PatLName,
            p.HmPhone,
            p.WirelessPhone,
            p.Birthdate,
            pr.FName         AS ProvFName,
            pr.LName         AS ProvLName,
            pr.Abbr          AS ProvAbbr,
            o.OpName         AS OperatoryName
        FROM       appointment a
        LEFT JOIN  patient    p  ON a.PatNum  = p.PatNum
        LEFT JOIN  provider   pr ON a.ProvNum = pr.ProvNum
        LEFT JOIN  operatory  o  ON a.Op      = o.OperatoryNum
        WHERE DATE(a.AptDateTime) = %s
          AND a.AptStatus = 1
        ORDER BY a.AptDateTime ASC
    """
    cur = conn.cursor()
    cur.execute(query, (target_date.isoformat(),))
    return _rows_as_dicts(cur)


def test_recent_appointments(conn: Any, days: int = 7) -> list[dict[str, Any]]:
    """
    Recent appointments across all statuses — confirms data is reachable
    and shows real field values for the last N days.
    """
    query = """
        SELECT
            a.AptNum,
            a.AptDateTime,
            a.AptStatus,
            a.ProcDescript,
            a.Op        AS OperatoryNum,
            p.FName     AS PatFName,
            p.LName     AS PatLName,
            pr.Abbr     AS ProvAbbr,
            o.OpName    AS OperatoryName
        FROM       appointment a
        LEFT JOIN  patient    p  ON a.PatNum  = p.PatNum
        LEFT JOIN  provider   pr ON a.ProvNum = pr.ProvNum
        LEFT JOIN  operatory  o  ON a.Op      = o.OperatoryNum
        WHERE a.AptDateTime >= DATE_SUB(NOW(), INTERVAL %s DAY)
        ORDER BY a.AptDateTime DESC
        LIMIT 25
    """
    cur = conn.cursor()
    cur.execute(query, (days,))
    return _rows_as_dicts(cur)


def test_broken_history(conn: Any, patient_nums: list[int]) -> list[dict[str, Any]]:
    """Broken/missed appointment counts for a list of patients."""
    if not patient_nums:
        return []
    placeholders = ",".join(["%s"] * len(patient_nums))
    query = (
        "SELECT PatNum, COUNT(*) AS missed_count "
        f"FROM appointment WHERE AptStatus = 5 AND PatNum IN ({placeholders}) "
        "GROUP BY PatNum ORDER BY missed_count DESC"
    )
    cur = conn.cursor()
    cur.execute(query, patient_nums)
    return [{"PatNum": row[0], "missed_count": row[1]} for row in cur.fetchall()]


def test_new_patients(conn: Any, patient_nums: list[int], target_date: date) -> list[int]:
    """Which of these patients have their first appointment on target_date?"""
    if not patient_nums:
        return []
    placeholders = ",".join(["%s"] * len(patient_nums))
    query = (
        f"SELECT PatNum FROM appointment WHERE PatNum IN ({placeholders}) "
        "GROUP BY PatNum HAVING MIN(DATE(AptDateTime)) = %s"
    )
    cur = conn.cursor()
    cur.execute(query, patient_nums + [target_date.isoformat()])
    return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

REQUIRED_TABLES = ["appointment", "patient", "provider", "operatory"]
SCHEMA_TABLES = ["appointment", "patient", "provider", "operatory"]


def run_all_tests(target_date: date, lookback_days: int, verbose: bool) -> dict[str, Any]:
    results: dict[str, Any] = {}

    # -- 1. Connect --
    _section("1. Connecting to MySQL", verbose)
    try:
        conn = _connect()
    except MySQLError as exc:
        return {"error": f"Connection failed: {exc}"}

    try:
        # -- 2. Server info --
        _section("2. Server info", verbose)
        results["connection"] = test_connection(conn)

        # -- 3. Table existence --
        _section("3. Required tables", verbose)
        results["tables_present"] = test_table_exists(conn, REQUIRED_TABLES)

        # -- 4. Row counts --
        _section("4. Row counts", verbose)
        results["row_counts"] = test_row_counts(conn, REQUIRED_TABLES)

        # -- 5. Schema inspection --
        _section("5. Schema (DESCRIBE)", verbose)
        results["schemas"] = {t: test_schema(conn, t) for t in SCHEMA_TABLES}

        # -- 6. AptStatus distribution --
        _section("6. AptStatus distribution", verbose)
        results["aptstatus_distribution"] = test_aptstatus_distribution(conn)

        # -- 7. Upcoming scheduled dates (helps pick a test date) --
        _section("7. Upcoming dates with scheduled appointments", verbose)
        results["upcoming_scheduled_dates"] = test_upcoming_scheduled_dates(conn)

        # -- 8. Today/target date full JOIN query --
        _section(f"8. Scheduled appointments for {target_date} (full JOIN)", verbose)
        appointments = test_appointments_for_date(conn, target_date)
        results["appointments_for_date"] = {
            "date": target_date.isoformat(),
            "count": len(appointments),
            "rows": appointments,
        }

        # -- 9. Broken history for today's patients --
        _section("9. Broken appointment history (today's patients)", verbose)
        patient_nums = [apt["PatNum"] for apt in appointments]
        results["broken_history"] = test_broken_history(conn, patient_nums)

        # -- 10. New patients today --
        _section("10. New patients (first-ever appointment today)", verbose)
        results["new_patients"] = test_new_patients(conn, patient_nums, target_date)

        # -- 11. Recent appointments (any status) --
        _section(f"11. Recent appointments (last {lookback_days} days, any status)", verbose)
        results["recent_appointments"] = {
            "lookback_days": lookback_days,
            "rows": test_recent_appointments(conn, lookback_days),
        }

    finally:
        conn.close()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Open Dental MySQL diagnostics and print results as JSON."
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Date to query appointments for (default: today).",
        default=None,
    )
    parser.add_argument(
        "--days",
        metavar="N",
        type=int,
        default=7,
        help="Lookback window in days for the recent-appointments test (default: 7).",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Suppress section headers — only emit JSON to stdout.",
    )
    args = parser.parse_args()

    target_date: date
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: --date must be in YYYY-MM-DD format, got '{args.date}'")
            sys.exit(1)
    else:
        target_date = date.today()

    verbose = not args.json_only

    if verbose:
        print(
            f"\nOpen Dental DB Diagnostic  |  target date: {target_date}  |  lookback: {args.days}d",
            file=sys.stderr,
        )

    results = run_all_tests(
        target_date=target_date,
        lookback_days=args.days,
        verbose=verbose,
    )

    # JSON goes to stdout so it can be piped / redirected independently
    print(dump(results))

    if verbose:
        apt_count = results.get("appointments_for_date", {}).get("count", 0)
        upcoming = results.get("upcoming_scheduled_dates", [])
        print(f"\nDone. Appointments on {target_date}: {apt_count}", file=sys.stderr)
        if apt_count == 0 and upcoming:
            print(
                f"Tip: no appointments today. Try: python test_db.py --date {upcoming[0]}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
