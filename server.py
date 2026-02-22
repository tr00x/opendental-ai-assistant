"""
server.py — Flask web server for the dental appointment dashboard.

Usage:
    python server.py
    Then open http://localhost:5000 in your browser.
"""
import json
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()
import db
from routes.kiosk import kiosk_bp

app = Flask(__name__)
app.register_blueprint(kiosk_bp)


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/appointments")
def appointments():
    date_str = request.args.get("date")
    try:
        target_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    try:
        data = db.get_appointment_data(target_date)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    output = {
        "date": target_date.isoformat(),
        "appointment_count": len(data["appointments"]),
        "appointments": data["appointments"],
        "broken_history": data["broken_history"],
    }
    return app.response_class(
        response=json.dumps(output, default=_json_default, ensure_ascii=False),
        mimetype="application/json",
    )


@app.route("/api/month")
def month_summary():
    """Return appointment counts for every day in a given month."""
    year = int(request.args.get("year", date.today().year))
    month = int(request.args.get("month", date.today().month))

    import mysql.connector, os
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ["DB_NAME"],
        charset="utf8",
        use_unicode=True,
    )
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DATE(AptDateTime) as d, COUNT(*) as cnt
            FROM appointment
            WHERE YEAR(AptDateTime) = %s
              AND MONTH(AptDateTime) = %s
              AND AptStatus = 1
            GROUP BY d
        """, (year, month))
        counts = {str(row[0]): row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    return jsonify(counts)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
