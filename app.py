import os
import sqlite3
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "development-only-change-this-before-deploying")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "miladcraft.db")))

ROLES = {
    "builder": "Builder",
    "hbuilder": "H-Builder",
    "developer": "Developer",
    "owner": "Owner",
}
ROLE_PERMISSIONS = {
    "builder": {"projects_view", "projects_claim"},
    "hbuilder": {"projects_view", "projects_create", "warnings_create"},
    "developer": {"projects_view", "projects_claim", "projects_create", "warnings_create", "full_access"},
    "owner": {"projects_view", "projects_claim", "projects_create", "warnings_create", "full_access"},
}

def connect_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('builder','hbuilder','developer','owner')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_builders INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'Open',
            created_by TEXT NOT NULL,
            claimed_by TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_username TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_url TEXT DEFAULT '',
            issued_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        bootstrap_user = os.environ.get("BOOTSTRAP_OWNER_USERNAME", "").strip()
        bootstrap_password = os.environ.get("BOOTSTRAP_OWNER_PASSWORD", "")
        if bootstrap_user and bootstrap_password:
            exists = db.execute("SELECT id FROM staff WHERE username=?", (bootstrap_user,)).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                    (bootstrap_user, generate_password_hash(bootstrap_password), "owner"),
                )

def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            role = session.get("role")
            if not role:
                return redirect(url_for("login"))
            if permission not in ROLE_PERMISSIONS.get(role, set()):
                flash("شما اجازه دسترسی به این بخش را ندارید.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

@app.before_request
def prepare_database():
    init_db()

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/staff/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM staff WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["staff_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("نام کاربری یا رمز عبور اشتباه است.", "error")
    return render_template("login.html")

@app.route("/staff/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/staff")
def dashboard():
    if not session.get("staff_id"):
        return redirect(url_for("login"))
    with connect_db() as db:
        projects = db.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
        warnings = db.execute("SELECT * FROM warnings ORDER BY id DESC LIMIT 50").fetchall()
        staff = db.execute("SELECT id,username,role,created_at FROM staff ORDER BY id").fetchall() if session["role"] in ("owner", "developer") else []
    return render_template("dashboard.html", projects=projects, warnings=warnings, staff=staff,
                           role_label=ROLES.get(session["role"], session["role"]),
                           can_create="projects_create" in ROLE_PERMISSIONS[session["role"]],
                           can_warn="warnings_create" in ROLE_PERMISSIONS[session["role"]],
                           full_access="full_access" in ROLE_PERMISSIONS[session["role"]])

@app.route("/projects/create", methods=["POST"])
@permission_required("projects_create")
def create_project():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    try:
        required = max(1, min(50, int(request.form.get("required_builders", "1"))))
    except ValueError:
        required = 1
    if not title or not description:
        flash("عنوان و توضیحات پروژه الزامی است.", "error")
    else:
        with connect_db() as db:
            db.execute("INSERT INTO projects(title,description,required_builders,created_by) VALUES(?,?,?,?)",
                       (title, description, required, session["username"]))
        flash("پروژه با موفقیت تعریف شد.", "success")
    return redirect(url_for("dashboard"))

@app.route("/projects/<int:project_id>/claim", methods=["POST"])
@permission_required("projects_claim")
def claim_project(project_id):
    with connect_db() as db:
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            flash("پروژه پیدا نشد.", "error")
        elif project["claimed_by"] and project["claimed_by"] != session["username"]:
            flash("این پروژه قبلاً توسط استف دیگری دریافت شده است.", "error")
        else:
            db.execute("UPDATE projects SET claimed_by=?, status='In progress' WHERE id=?",
                       (session["username"], project_id))
            flash("پروژه به شما واگذار شد.", "success")
    return redirect(url_for("dashboard"))

@app.route("/warnings/create", methods=["POST"])
@permission_required("warnings_create")
def create_warning():
    target = request.form.get("staff_username", "").strip()
    reason = request.form.get("reason", "").strip()
    evidence_url = request.form.get("evidence_url", "").strip()
    with connect_db() as db:
        known = db.execute("SELECT id FROM staff WHERE username=?", (target,)).fetchone()
        if not known or not reason:
            flash("نام کاربری استف باید معتبر باشد و دلیل وارن را وارد کنید.", "error")
        else:
            db.execute("INSERT INTO warnings(staff_username,reason,evidence_url,issued_by) VALUES(?,?,?,?)",
                       (target, reason, evidence_url, session["username"]))
            flash("وارن ثبت شد.", "success")
    return redirect(url_for("dashboard"))

@app.route("/staff/create", methods=["POST"])
@permission_required("full_access")
def create_staff():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "")
    if len(username) < 3 or len(password) < 10 or role not in ROLES:
        flash("نام کاربری باید حداقل ۳ و رمز عبور حداقل ۱۰ کاراکتر باشد؛ نقش را هم بررسی کنید.", "error")
    else:
        try:
            with connect_db() as db:
                db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                           (username, generate_password_hash(password), role))
            flash("حساب استف ساخته شد.", "success")
        except sqlite3.IntegrityError:
            flash("این نام کاربری قبلاً ثبت شده است.", "error")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
