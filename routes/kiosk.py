"""
routes/kiosk.py — Patient-facing kiosk blueprint.

Search endpoints (all return today's appointments only):
    GET /kiosk/search?q=<lastname>
    GET /kiosk/search?dob=MM/DD/YYYY
    GET /kiosk/search?phone=<digits>

Only patient-safe fields returned — no phone, no missed history, no notes.
"""
import os
import re
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file

import db

# Network path to Open Dental image store (set in .env)
_IMAGE_ROOT = Path(os.environ.get("OPENDENT_IMAGE_PATH", r"\\10.0.0.83\OpenDentImages"))

kiosk_bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")

# ---------------------------------------------------------------------------
# Procedure code → plain-English mapping
# ---------------------------------------------------------------------------
_PROC_MAP = [
    ("ImpCrPrep",    "Implant Crown Prep"),
    ("ImpCr",        "Implant Crown"),
    ("PFMSeat",      "Crown Placement"),
    ("PFMPrep",      "Crown Preparation"),
    ("PFM",          "Crown"),
    ("SRPMaxSext",   "Deep Cleaning"),
    ("SRPMandSext",  "Deep Cleaning"),
    ("SRP",          "Deep Cleaning"),
    ("RCT",          "Root Canal"),
    ("Perio",        "Gum Treatment"),
    ("BWX",          "X-Rays"),
    ("FMX",          "Full X-Rays"),
    ("PA",           "X-Ray"),
    ("CompF",        "Filling"),
    ("CompA",        "Filling"),
    ("Comp",         "Filling"),
    ("Ext",          "Extraction"),
    ("Pre-fab",      "Post Placement"),
    ("Core",         "Build-Up"),
    ("Seat",         "Crown Seating"),
    ("Post",         "Post Placement"),
    ("Pro",          "Cleaning"),
    ("Ex",           "Exam"),
    ("Bl",           "Whitening"),
    ("Ven",          "Veneer"),
]

_NON_PERSON = {"PC", "LLC", "INC", "GROUP", "DENTAL", "ASSOCIATES", "CARE"}


def _simplify_proc(raw: str) -> str:
    if not raw:
        return "Dental Visit"
    seen: set[str] = set()
    labels: list[str] = []
    for part in [p.strip().lstrip("#") for p in raw.split(",")]:
        code = part.split("-", 1)[-1] if "-" in part else part
        mapped = next((v for k, v in _PROC_MAP if k.lower() in code.lower()), None)
        label = mapped or "Dental Visit"
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return ", ".join(labels) or "Dental Visit"


def _provider_name(apt: dict) -> str:
    fname = (apt.get("ProvFName") or "").strip()
    lname = (apt.get("ProvLName") or "").strip()
    abbr  = (apt.get("ProvAbbr")  or "").strip()
    if not any(tok in lname.upper() for tok in _NON_PERSON) and fname and lname:
        return f"Dr. {fname} {lname}"
    if abbr.lower().startswith("dr"):
        return abbr
    return "our dental team"


def _fmt_date(d) -> str | None:
    """Format a date/datetime to 'Month DD, YYYY' or None."""
    if d is None:
        return None
    try:
        return d.strftime("%B %d, %Y")
    except AttributeError:
        return str(d)


def _safe_fields(apt: dict, last_visit: str | None = None) -> dict:
    """Return only patient-appropriate fields."""
    dt = apt.get("AptDateTime")
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    time_str = dt.strftime("%I:%M %p").lstrip("0") if dt else ""

    return {
        "pat_num":    apt.get("PatNum"),           # needed for photo URL
        "PatFName":   apt.get("PatFName", ""),
        "PatLName":   apt.get("PatLName", ""),
        "time":       time_str,
        "provider":   _provider_name(apt),
        "room":       apt.get("OperatoryName") or "",
        "procedure":  _simplify_proc(apt.get("ProcDescript", "")),
        "last_visit": last_visit,  # None → "First visit" shown in frontend
    }


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@kiosk_bp.route("/")
def index():
    return render_template("kiosk/index.html")




@kiosk_bp.route("/photo-debug")
def photo_debug():
    import os
    filename  = "GarciaBenjamin15388.jpg"
    folder    = "GarciaBenjamin"
    letter    = "G"
    try:
        root_ls   = os.listdir(str(_IMAGE_ROOT))
    except Exception as e:
        root_ls = str(e)
    try:
        letter_ls = os.listdir(str(_IMAGE_ROOT / letter))
    except Exception as e:
        letter_ls = str(e)
    try:
        pat_ls = os.listdir(str(_IMAGE_ROOT / letter / folder))
    except Exception as e:
        pat_ls = str(e)
    p1 = _IMAGE_ROOT / letter / folder / filename
    p2 = _IMAGE_ROOT / "A to Z Folders" / folder / filename
    return jsonify({
        "root":        root_ls,
        "G_folder":    letter_ls,
        "GarciaBen":   pat_ls,
        "path1":       str(p1),
        "path1_exists": p1.exists(),
        "path2":       str(p2),
        "path2_exists": p2.exists(),
    })


@kiosk_bp.route("/photo/<int:pat_num>")
def patient_photo(pat_num):
    """Serve patient photo from Open Dental image store."""
    try:
        filename = db.get_patient_photo_file(pat_num)
    except RuntimeError:
        filename = None

    if not filename:
        return "", 404

    # Derive folder from filename: strip extension, then trailing digits
    # e.g. "GarciaBenjamin15388.jpg" → folder "GarciaBenjamin"
    name_part = re.sub(r"\.\w+$", "", filename)          # → "GarciaBenjamin15388"
    folder    = re.sub(r"\d+$",   "", name_part)         # → "GarciaBenjamin"
    letter    = folder[0].upper() if folder else "_"     # → "G"

    # Try both layouts Open Dental uses
    image_path = _IMAGE_ROOT / letter / folder / filename
    if not image_path.exists():
        image_path = _IMAGE_ROOT / "A to Z Folders" / folder / filename

    if not image_path.exists():
        return "", 404

    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png",  "gif":  "image/gif"}.get(ext, "image/jpeg")

    return send_file(image_path, mimetype=mime)


@kiosk_bp.route("/search")
def search():
    q     = (request.args.get("q")     or "").strip()
    dob   = (request.args.get("dob")   or "").strip()
    phone = (request.args.get("phone") or "").strip()

    if not q and not dob and not phone:
        return jsonify({"error": "Provide q, dob, or phone"}), 400

    try:
        data = db.get_appointment_data(date.today())
    except RuntimeError:
        return jsonify({"error": "db_unavailable"}), 500

    apts = data["appointments"]

    # ── Filter by chosen search method ──
    if q:
        q_lower = q.lower()
        matches = [a for a in apts if a.get("PatLName", "").lower().startswith(q_lower)]

    elif dob:
        try:
            parts = dob.split("/")
            if len(parts) != 3:
                raise ValueError
            dob_date = date(int(parts[2]), int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return jsonify({"error": "dob_invalid"}), 400

        matches = []
        for a in apts:
            bd = a.get("Birthdate")
            if bd is None:
                continue
            if hasattr(bd, "year") and bd.year < 1900:
                continue
            if hasattr(bd, "date"):
                bd = bd.date()
            if bd == dob_date:
                matches.append(a)

    else:  # phone
        digits = _only_digits(phone)
        if len(digits) < 7:
            return jsonify({"error": "phone_short"}), 400

        matches = [
            a for a in apts
            if _only_digits(a.get("WirelessPhone", "")).endswith(digits)
            or _only_digits(a.get("HmPhone", "")).endswith(digits)
        ]

    # ── Fetch last completed visit for each matched patient ──
    pat_nums = list({a["PatNum"] for a in matches})
    try:
        last_visits = db.get_last_visits(pat_nums)
    except RuntimeError:
        last_visits = {}   # graceful degradation

    results = [
        _safe_fields(a, last_visit=_fmt_date(last_visits.get(a["PatNum"])))
        for a in matches
    ]

    return jsonify({"results": results})
