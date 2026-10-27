import hmac
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database as db
from supabase_auth import verify_token

TZ_NAME = os.environ.get("TZ_NAME", "America/Bogota")
LOCAL_TZ = ZoneInfo(TZ_NAME)

app = Flask(__name__)
if os.environ.get("FLASK_ENV") == "production" and not os.environ.get("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY environment variable must be set in production")
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-produccion")
app.permanent_session_lifetime = timedelta(
    hours=int(os.environ.get("SESSION_TTL_HOURS", "24"))
)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

db.init_db()


def service_key_configured():
    return bool(os.environ.get("SERVICE_API_KEY"))


def service_key_ok():
    expected = os.environ.get("SERVICE_API_KEY", "")
    received = request.headers.get("X-Service-Key", "")
    return bool(expected) and hmac.compare_digest(expected, received)


def bearer_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def end_of_day_ts(date_text):
    day = datetime.strptime(date_text, "%Y-%m-%d").date()
    local = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=LOCAL_TZ)
    return int(local.timestamp())


def fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(int(ts), LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def fmt_date(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), LOCAL_TZ).strftime("%Y-%m-%d")


def days_left(ts):
    remaining = int(ts) - db.now_ts()
    return max(0, (remaining + 86399) // 86400)


def serialize_subscriber(row):
    state = db.subscription_state(row)
    return {
        "email": row["email"],
        "status": row["status"],
        "expires_at": row["expires_at"],
        "expires_at_iso": datetime.fromtimestamp(
            int(row["expires_at"]), timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": state == "active",
        "state": state,
        "note": row.get("note"),
        "telegram_chat_id": row.get("telegram_chat_id"),
    }


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def root():
    return redirect(url_for("admin"))


@app.route("/authorize", methods=["POST"])
def authorize():
    if not service_key_configured():
        return jsonify({"active": False, "reason": "service_not_configured"}), 503
    if not service_key_ok():
        return jsonify({"active": False, "reason": "forbidden"}), 401

    payload = request.get_json(silent=True) or {}
    email = db.normalize_email(payload.get("email"))
    if not email:
        return jsonify({"active": False, "reason": "missing_email"}), 400

    token = bearer_token()
    if not token:
        return jsonify({"active": False, "reason": "missing_token"}), 401

    verified = verify_token(token)
    if not verified:
        return jsonify({"active": False, "reason": "invalid_token"}), 401
    if verified != email:
        return jsonify({"active": False, "reason": "email_mismatch"}), 403

    subscriber = db.get_subscriber(email)
    state = db.subscription_state(subscriber)
    if state != "active":
        body = {"active": False, "reason": state, "email": email}
        if subscriber:
            body["expires_at"] = subscriber["expires_at"]
        return jsonify(body), 403

    return jsonify(
        {
            "active": True,
            "reason": "active",
            "email": email,
            "expires_at": subscriber["expires_at"],
            "expires_at_iso": serialize_subscriber(subscriber)["expires_at_iso"],
            "days_left": days_left(subscriber["expires_at"]),
        }
    )


@app.route("/me", methods=["GET"])
def me():
    token = bearer_token()
    if not token:
        return jsonify({"active": False, "reason": "missing_token"}), 401
    email = verify_token(token)
    if not email:
        return jsonify({"active": False, "reason": "invalid_token"}), 401
    subscriber = db.get_subscriber(email)
    if not subscriber:
        return jsonify({"active": False, "reason": "not_subscribed", "email": email}), 403
    body = serialize_subscriber(subscriber)
    return jsonify(body), (200 if body["active"] else 403)


@app.route("/authorize-telegram", methods=["POST"])
def authorize_telegram():
    if not service_key_ok():
        return jsonify({"active": False, "reason": "forbidden"}), 401

    payload = request.get_json(silent=True) or {}
    email = db.normalize_email(payload.get("email"))
    try:
        chat_id = int(payload.get("chat_id"))
    except (TypeError, ValueError):
        return jsonify({"active": False, "reason": "missing_chat_id"}), 400
    if not email:
        return jsonify({"active": False, "reason": "missing_email"}), 400

    subscriber = db.find_by_chat(chat_id)
    if not subscriber:
        return jsonify({"active": False, "reason": "not_linked"}), 403
    if subscriber["email"] != email:
        return jsonify({"active": False, "reason": "email_mismatch"}), 403
    state = db.subscription_state(subscriber)
    if state != "active":
        return jsonify(
            {"active": False, "reason": state, "expires_at": subscriber["expires_at"]}
        ), 403
    return jsonify({"active": True, "reason": "active", "email": email})


@app.route("/link-telegram", methods=["POST"])
def link_telegram():
    if not service_key_ok():
        return jsonify({"ok": False, "reason": "forbidden"}), 401

    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    try:
        chat_id = int(payload.get("chat_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_chat_id"}), 400

    subscriber = db.find_by_link_code(code)
    if not subscriber:
        return jsonify({"ok": False, "reason": "invalid_code"}), 404
    try:
        db.set_telegram_chat(subscriber["email"], chat_id)
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "reason": "chat_already_linked"}), 409
    db.clear_link_code(subscriber["email"])
    return jsonify({"ok": True, "email": subscriber["email"]})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD", "")
        if expected and hmac.compare_digest(password, expected):
            session.permanent = True
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Contraseña incorrecta"
    return render_template("admin_login.html", error=error)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def _build_rows(query):
    now = db.now_ts()
    rows = []
    for row in db.list_subscribers(query):
        rows.append(
            {
                **row,
                "state": db.subscription_state(row),
                "active": db.subscription_state(row) == "active",
                "expiry_label": fmt_ts(row["expires_at"]),
                "expiry_date": fmt_date(row["expires_at"]),
                "days_left": days_left(row["expires_at"]) if row["expires_at"] > now else 0,
            }
        )
    return rows


@app.route("/admin")
@login_required
def admin():
    query = request.args.get("q", "")
    return render_template(
        "admin.html",
        rows=_build_rows(query),
        query=query,
        now=db.now_ts(),
        tz=TZ_NAME,
        message=request.args.get("message"),
        error=request.args.get("error"),
    )


@app.route("/admin/add", methods=["POST"])
@login_required
def admin_add():
    email = db.normalize_email(request.form.get("email"))
    date_text = request.form.get("expires", "")
    note = request.form.get("note", "").strip() or None
    if not email or "@" not in email:
        return redirect(url_for("admin", error="Correo invalido"))
    try:
        expires_at = end_of_day_ts(date_text)
    except ValueError:
        return redirect(url_for("admin", error="Fecha invalida"))
    db.upsert_subscriber(email, expires_at, note)
    return redirect(url_for("admin", message=f"Guardado: {email}"))


@app.route("/admin/bulk", methods=["POST"])
@login_required
def admin_bulk():
    raw = request.form.get("emails", "")
    date_text = request.form.get("expires", "")
    note = request.form.get("note", "").strip() or None
    if not date_text:
        return redirect(url_for("admin", error="Fecha invalida"))
    try:
        expires_at = end_of_day_ts(date_text)
    except ValueError:
        return redirect(url_for("admin", error="Fecha invalida"))

    valid = []
    invalid = []
    seen = set()
    for item in re.split(r"[\s,;]+", raw.strip()):
        email = db.normalize_email(item)
        if not email:
            continue
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            invalid.append(email)
            continue
        if email in seen:
            continue
        seen.add(email)
        valid.append(email)

    if not valid:
        return redirect(url_for("admin", error="No hay correos validos en la lista"))

    saved = db.bulk_upsert_subscribers(valid, expires_at, note)
    params = {
        "message": f"Carga masiva: {saved} suscriptores guardados hasta {fmt_date(expires_at)}"
    }
    if invalid:
        muestra = ", ".join(invalid[:5])
        extra = f" y {len(invalid) - 5} mas" if len(invalid) > 5 else ""
        params["error"] = (
            f"{len(invalid)} correos omitidos por invalidos: {muestra}{extra}"
        )
    return redirect(url_for("admin", **params))


@app.route("/admin/expiry", methods=["POST"])
@login_required
def admin_expiry():
    email = db.normalize_email(request.form.get("email"))
    try:
        expires_at = end_of_day_ts(request.form.get("expires", ""))
    except ValueError:
        return redirect(url_for("admin", error="Fecha invalida"))
    db.set_expiry(email, expires_at)
    return redirect(url_for("admin", message=f"Vencimiento actualizado: {email}"))


@app.route("/admin/extend", methods=["POST"])
@login_required
def admin_extend():
    email = db.normalize_email(request.form.get("email"))
    try:
        days = int(request.form.get("days", "30"))
    except ValueError:
        days = 30
    subscriber = db.get_subscriber(email)
    if not subscriber:
        return redirect(url_for("admin", error="Suscriptor no encontrado"))
    base = max(db.now_ts(), int(subscriber["expires_at"]))
    db.set_expiry(email, base + days * 86400)
    return redirect(url_for("admin", message=f"Sumados {days} dias a {email}"))


@app.route("/admin/status", methods=["POST"])
@login_required
def admin_status():
    email = db.normalize_email(request.form.get("email"))
    status = request.form.get("status", "ACTIVE")
    db.set_status(email, status)
    return redirect(url_for("admin", message=f"Estado {status}: {email}"))


@app.route("/admin/delete", methods=["POST"])
@login_required
def admin_delete():
    email = db.normalize_email(request.form.get("email"))
    db.delete_subscriber(email)
    return redirect(url_for("admin", message=f"Eliminado: {email}"))


@app.route("/admin/link-code", methods=["POST"])
@login_required
def admin_link_code():
    email = db.normalize_email(request.form.get("email"))
    if not db.get_subscriber(email):
        return redirect(url_for("admin", error="Suscriptor no encontrado"))
    code = db.new_link_code(email)
    return redirect(url_for("admin", message=f"Codigo de Telegram para {email}: {code}"))


@app.route("/admin/chat", methods=["POST"])
@login_required
def admin_chat():
    email = db.normalize_email(request.form.get("email"))
    raw = request.form.get("chat_id", "").strip()
    if not raw:
        db.set_telegram_chat(email, None)
        return redirect(url_for("admin", message=f"Telegram desvinculado: {email}"))
    try:
        chat_id = int(raw)
    except ValueError:
        return redirect(url_for("admin", error="chat_id invalido"))
    try:
        db.set_telegram_chat(email, chat_id)
    except sqlite3.IntegrityError:
        return redirect(url_for("admin", error="Ese chat ya esta vinculado a otro suscriptor"))
    return redirect(url_for("admin", message=f"Telegram vinculado: {email}"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
