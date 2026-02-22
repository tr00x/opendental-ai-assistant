"""
db.py — MySQL database connection and query module for Open Dental appointments.
"""
import os
import logging
from datetime import date
from typing import Any

import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL queries  (MySQL 5.6 syntax, %s placeholders)
# ---------------------------------------------------------------------------

_APPOINTMENTS_QUERY = """
    SELECT
        a.AptNum,
        a.AptDateTime,
        a.PatNum,
        a.ProvNum,
        a.AptStatus,
        a.ProcDescript,
        a.IsNewPatient,
        a.Note,
        a.ClinicNum,
        a.Op             AS OperatoryNum,
        p.FName          AS PatFName,
        p.LName          AS PatLName,
        p.HmPhone,
        p.WirelessPhone,
        p.Birthdate,
        p.Email,
        pr.FName         AS ProvFName,
        pr.LName         AS ProvLName,
        pr.Abbr          AS ProvAbbr,
        o.OpName         AS OperatoryName
    FROM       appointment a
    LEFT JOIN  patient    p  ON a.PatNum  = p.PatNum
    LEFT JOIN  provider   pr ON a.ProvNum = pr.ProvNum
    LEFT JOIN  operatory  o  ON a.Op      = o.OperatoryNum
    WHERE DATE(a.AptDateTime) = CURDATE()
      AND a.AptStatus = 1
    ORDER BY a.AptDateTime ASC, a.Op ASC
"""

_APPOINTMENTS_FOR_DATE_QUERY = """
    SELECT
        a.AptNum,
        a.AptDateTime,
        a.PatNum,
        a.ProvNum,
        a.AptStatus,
        a.ProcDescript,
        a.IsNewPatient,
        a.Note,
        a.ClinicNum,
        a.Op             AS OperatoryNum,
        p.FName          AS PatFName,
        p.LName          AS PatLName,
        p.HmPhone,
        p.WirelessPhone,
        p.Birthdate,
        p.Email,
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
    ORDER BY a.AptDateTime ASC, a.Op ASC
"""

_BROKEN_HISTORY_QUERY = """
    SELECT PatNum, COUNT(*) AS missed_count
    FROM   appointment
    WHERE  AptStatus = 5
      AND  PatNum IN ({placeholders})
    GROUP BY PatNum
"""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_connection() -> mysql.connector.connection.MySQLConnection:
    """Create a MySQL connection from environment variables."""
    try:
        conn = mysql.connector.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ.get("DB_PASSWORD", ""),
            database=os.environ["DB_NAME"],
            connect_timeout=10,
            charset="utf8",
            use_unicode=True,
        )
        logger.info(
            "MySQL connection established: %s@%s/%s",
            os.environ["DB_USER"],
            os.environ["DB_HOST"],
            os.environ["DB_NAME"],
        )
        return conn
    except KeyError as exc:
        raise RuntimeError(f"Missing required environment variable: {exc}") from exc
    except Error as exc:
        raise RuntimeError(f"Failed to connect to MySQL: {exc}") from exc


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fetch_appointments(
    cursor: Any,
    target_date: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch scheduled (AptStatus=1) appointments — today or a given date."""
    if target_date is None:
        cursor.execute(_APPOINTMENTS_QUERY)
    else:
        cursor.execute(_APPOINTMENTS_FOR_DATE_QUERY, (target_date.isoformat(),))
    appointments = _rows_to_dicts(cursor)
    logger.info("Fetched %d appointments", len(appointments))
    return appointments


def _fetch_broken_history(cursor: Any, patient_nums: list[int]) -> dict[int, int]:
    """Return {PatNum: missed_count} for all patients, including those with 0 history."""
    if not patient_nums:
        return {}
    placeholders = ",".join(["%s"] * len(patient_nums))
    cursor.execute(
        _BROKEN_HISTORY_QUERY.format(placeholders=placeholders),
        patient_nums,
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_patient_photo_file(pat_num: int) -> str | None:
    """Return FileName of most recent patient photo doc, or None if no photo."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT FileName
            FROM   document
            WHERE  PatNum      = %s
              AND  DocCategory IN (182, 190)
            ORDER  BY DocNum DESC
            LIMIT  1
            """,
            (pat_num,),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except Error as exc:
        raise RuntimeError(f"Database query failed: {exc}") from exc
    finally:
        conn.close()


def get_last_visits(patient_nums: list[int]) -> dict[int, Any]:
    """Return {PatNum: last_completed_datetime} for patients' most recent completed visit."""
    if not patient_nums:
        return {}
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ",".join(["%s"] * len(patient_nums))
        cursor.execute(
            f"""
            SELECT PatNum, MAX(AptDateTime) AS last_date
            FROM   appointment
            WHERE  PatNum IN ({placeholders})
              AND  AptStatus = 2
              AND  DATE(AptDateTime) < CURDATE()
            GROUP BY PatNum
            """,
            patient_nums,
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Error as exc:
        raise RuntimeError(f"Database query failed: {exc}") from exc
    finally:
        conn.close()


def get_appointment_data(target_date: date | None = None) -> dict[str, Any]:
    """
    Connect and return:
      appointments   — list[dict]  scheduled appointments (AptStatus=1), with all fields
      broken_history — dict[int,int]  PatNum → missed/broken appointment count

    Note: new patient detection uses appointment.IsNewPatient (1/0) directly from
    Open Dental — no subquery needed.
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        appointments = _fetch_appointments(cursor, target_date)
        patient_nums = [apt["PatNum"] for apt in appointments]
        broken_history = _fetch_broken_history(cursor, patient_nums)
        return {
            "appointments": appointments,
            "broken_history": broken_history,
        }
    except Error as exc:
        raise RuntimeError(f"Database query failed: {exc}") from exc
    finally:
        conn.close()
        logger.info("MySQL connection closed")
