import os
import sqlite3
from functools import wraps
from pathlib import Path
from urllib.request import Request, urlopen
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
import bleach

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "development-only-change-this-before-deploying")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "miladcraft.db")))
SERVER_ADDRESS = "miladcraft.seedloaf.gg"
TELEGRAM_URL = os.environ.get("TELEGRAM_URL", "https://t.me/Milad_craft")
ROLES = {"builder": "Builder", "hbuilder": "H-Builder", "developer": "Developer", "owner": "Owner"}
ROLE_PERMISSIONS = {
    "builder": {"projects_view", "projects_claim"},
    "hbuilder": {"projects_view", "projects_create", "warnings_create"},
    "developer": {"projects_view", "projects_claim", "projects_create", "warnings_create", "full_access", "blog_manage"},
    "owner": {"projects_view", "projects_claim", "projects_create", "warnings_create", "full_access", "blog_manage"},
}
BLOG_TAGS = ["p", "br", "strong", "b", "em", "i", "u", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "a", "img", "hr", "code", "pre"]
BLOG_ATTRS = {"a": ["href", "title", "target", "rel"], "img": ["src", "alt", "title", "width"]}
BLOG_PROTOCOLS = ["http", "https", "mailto"]

def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('builder','hbuilder','developer','owner')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
          required_builders INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'Open',
          created_by TEXT NOT NULL, claimed_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS warnings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, staff_username TEXT NOT NULL, reason TEXT NOT NULL,
          evidence_url TEXT DEFAULT '', issued_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS posts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, summary TEXT DEFAULT '',
          content TEXT NOT NULL, cover_url TEXT DEFAULT '', author TEXT NOT NULL,
          published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        username = os.environ.get("BOOTSTRAP_OWNER_USERNAME", "").strip()
        password = os.environ.get("BOOTSTRAP_OWNER_PASSWORD", "")
        if username and password and not db.execute("SELECT id FROM staff WHERE username=?", (username,)).fetchone():
            db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                       (username, generate_password_hash(password), "owner"))

def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("staff_id"):
                return redirect(url_for("login"))
            if permission not in ROLE_PERMISSIONS.get(session.get("role"), set()):
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
    response.headers["Content-Security-Policy"] = "default-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com https://images.unsplash.com https://api.mcsrvstat.us; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; connect-src 'self' https://api.mcsrvstat.us"
    return response

@app.context_processor
def common_template_values():
    return {"server_address": SERVER_ADDRESS, "telegram_url": TELEGRAM_URL}

@app.route("/")
def index():
    with connect_db() as db:
        posts = db.execute("SELECT id,title,summary,cover_url,author,created_at FROM posts WHERE published=1 ORDER BY id DESC LIMIT 3").fetchall()
    return render_template("index.html", posts=posts, server_address=SERVER_ADDRESS, telegram_url=TELEGRAM_URL)

@app.route("/robots.txt")
def robots_txt():
    body = "User-agent: *\\nAllow: /\\nDisallow: /staff\\nDisallow: /staff/\\nSitemap: " + request.url_root.rstrip("/") + "/sitemap.xml\\n"
    return app.response_class(body, mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    base = request.url_root.rstrip("/")
    urls = [base + "/", base + url_for("academy")]
    with connect_db() as db:
        rows = db.execute("SELECT id FROM posts WHERE published=1 ORDER BY id DESC").fetchall()
    urls.extend(base + url_for("blog_post", post_id=row["id"]) for row in rows)
    entries = "".join("<url><loc>" + url + "</loc></url>" for url in urls)
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + "</urlset>"
    return app.response_class(xml, mimetype="application/xml")

@app.route("/api/server-status")
def server_status():
    try:
        req = Request("https://api.mcsrvstat.us/3/" + SERVER_ADDRESS, headers={"User-Agent": "MiladCraft-Website/1.0"})
        with urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
        online = bool(data.get("online"))
        return jsonify({"online": online, "host": SERVER_ADDRESS,
                        "players_online": data.get("players", {}).get("online", 0) if online else 0,
                        "players_max": data.get("players", {}).get("max", 0) if online else 0,
                        "version": data.get("version", "") if online else ""})
    except Exception:
        return jsonify({"online": None, "host": SERVER_ADDRESS, "players_online": 0, "players_max": 0, "version": "", "error": "status_unavailable"}), 200

@app.route("/staff/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM staff WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(staff_id=user["id"], username=user["username"], role=user["role"])
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
        posts = db.execute("SELECT id,title,published,created_at FROM posts ORDER BY id DESC").fetchall() if "blog_manage" in ROLE_PERMISSIONS.get(session["role"], set()) else []
    role = session["role"]
    return render_template("dashboard.html", projects=projects, warnings=warnings, staff=staff, posts=posts,
                           role_label=ROLES.get(role, role), can_create="projects_create" in ROLE_PERMISSIONS[role],
                           can_warn="warnings_create" in ROLE_PERMISSIONS[role],
                           full_access="full_access" in ROLE_PERMISSIONS[role],
                           can_blog="blog_manage" in ROLE_PERMISSIONS[role])

@app.route("/projects/create", methods=["POST"])
@permission_required("projects_create")
def create_project():
    title, description = request.form.get("title", "").strip(), request.form.get("description", "").strip()
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
    target, reason = request.form.get("staff_username", "").strip(), request.form.get("reason", "").strip()
    evidence_url = request.form.get("evidence_url", "").strip()
    with connect_db() as db:
        if not db.execute("SELECT id FROM staff WHERE username=?", (target,)).fetchone() or not reason:
            flash("نام کاربری استف باید معتبر باشد و دلیل وارن را وارد کنید.", "error")
        else:
            db.execute("INSERT INTO warnings(staff_username,reason,evidence_url,issued_by) VALUES(?,?,?,?)",
                       (target, reason, evidence_url, session["username"]))
            flash("وارن ثبت شد.", "success")
    return redirect(url_for("dashboard"))

@app.route("/staff/create", methods=["POST"])
@permission_required("full_access")
def create_staff():
    username, password, role = request.form.get("username", "").strip(), request.form.get("password", ""), request.form.get("role", "")
    if len(username) < 3 or len(password) < 10 or role not in ROLES:
        flash("نام کاربری باید حداقل ۳ و رمز عبور حداقل ۱۰ کاراکتر باشد؛ نقش را هم بررسی کنید.", "error")
    else:
        try:
            with connect_db() as db:
                db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)", (username, generate_password_hash(password), role))
            flash("حساب استف ساخته شد.", "success")
        except sqlite3.IntegrityError:
            flash("این نام کاربری قبلاً ثبت شده است.", "error")
    return redirect(url_for("dashboard"))

@app.route("/academy")
def academy():
    with connect_db() as db:
        posts = db.execute("SELECT id,title,summary,cover_url,author,created_at FROM posts WHERE published=1 ORDER BY id DESC").fetchall()
    return render_template("academy.html", posts=posts)

@app.route("/academy/<int:post_id>")
def blog_post(post_id):
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=? AND published=1", (post_id,)).fetchone()
    if not post:
        abort(404)
    return render_template("post.html", post=post)

@app.route("/academy/editor", methods=["GET", "POST"])
@permission_required("blog_manage")
def blog_editor():
    post_id = request.args.get("id", type=int)
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone() if post_id else None
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            summary = request.form.get("summary", "").strip()
            cover_url = request.form.get("cover_url", "").strip()
            content = bleach.clean(request.form.get("content", ""), tags=BLOG_TAGS, attributes=BLOG_ATTRS,
                                   protocols=BLOG_PROTOCOLS, strip=True)
            published = 1 if request.form.get("published") == "1" else 0
            if not title or not bleach.clean(content, tags=[], strip=True).strip():
                flash("عنوان و محتوای مقاله الزامی است.", "error")
            elif post_id and post:
                db.execute("UPDATE posts SET title=?,summary=?,cover_url=?,content=?,published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (title, summary, cover_url, content, published, post_id))
                flash("مقاله به‌روزرسانی شد.", "success")
                return redirect(url_for("dashboard"))
            else:
                db.execute("INSERT INTO posts(title,summary,cover_url,content,author,published) VALUES(?,?,?,?,?,?)",
                           (title, summary, cover_url, content, session["username"], published))
                flash("مقاله ایجاد شد.", "success")
                return redirect(url_for("dashboard"))
    return render_template("editor.html", post=post)

@app.route("/academy/<int:post_id>/delete", methods=["POST"])
@permission_required("blog_manage")
def delete_post(post_id):
    with connect_db() as db:
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    flash("مقاله حذف شد.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
