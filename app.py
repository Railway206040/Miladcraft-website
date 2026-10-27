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
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('builder','hbuilder','developer','owner')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS site_settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '');
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
        CREATE TABLE IF NOT EXISTS members (
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
          avatar_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS academy_tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
          slug TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS post_tags (
          post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          tag_id INTEGER NOT NULL REFERENCES academy_tags(id) ON DELETE CASCADE,
          PRIMARY KEY(post_id, tag_id));
        CREATE TABLE IF NOT EXISTS post_comments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
          body TEXT NOT NULL, reply_text TEXT NOT NULL DEFAULT '', replied_by TEXT NOT NULL DEFAULT '',
          replied_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS post_feedback (
          post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
          vote INTEGER NOT NULL CHECK(vote IN (-1,1)),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(post_id, member_id));
        """)
        image_defaults = {
            "hero_image": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1800&q=85",
            "about_image": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1000&q=85",
            "roleplay_image": "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=1100&q=85",
            "survival_image": "https://images.unsplash.com/photo-1580234811497-9df7fd2f357e?auto=format&fit=crop&w=1100&q=85",
            "gallery_image_1": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=85",
            "gallery_image_2": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=800&q=85",
            "gallery_image_3": "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=800&q=85"
        }
        for key, value in image_defaults.items():
            db.execute("INSERT OR IGNORE INTO site_settings(setting_key,setting_value) VALUES(?,?)", (key, value))
        # Apply bootstrap credentials once per configured username/password pair.
        # The marker prevents this from overwriting a user's later password change on every request.
        db.execute("CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL)")
        username = os.environ.get("BOOTSTRAP_OWNER_USERNAME", "").strip()
        password = os.environ.get("BOOTSTRAP_OWNER_PASSWORD", "")
        if username and password:
            import hashlib
            bootstrap_marker = hashlib.sha256((username + "\\0" + password).encode("utf-8")).hexdigest()
            marker_key = "bootstrap_owner:" + username
            previous_marker = db.execute("SELECT meta_value FROM app_meta WHERE meta_key=?", (marker_key,)).fetchone()
            if not previous_marker or previous_marker["meta_value"] != bootstrap_marker:
                existing = db.execute("SELECT id FROM staff WHERE username=?", (username,)).fetchone()
                if existing:
                    db.execute("UPDATE staff SET password_hash=?, role='developer' WHERE id=?",
                               (generate_password_hash(password), existing["id"]))
                else:
                    db.execute("INSERT INTO staff(username,password_hash,role) VALUES(?,?,?)",
                               (username, generate_password_hash(password), "developer"))
                db.execute("INSERT INTO app_meta(meta_key,meta_value) VALUES(?,?) ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value",
                           (marker_key, bootstrap_marker))

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
        site_images = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM site_settings")}
    return render_template("index.html", posts=posts, site_images=site_images,
                           server_address=SERVER_ADDRESS, telegram_url=TELEGRAM_URL)

@app.route("/robots.txt")
def robots_txt():
    body = "User-agent: *\nAllow: /\nDisallow: /staff\nDisallow: /staff/\nSitemap: " + request.url_root.rstrip("/") + "/sitemap.xml\n"
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

@app.route("/staff/change-password", methods=["POST"])
def change_password():
    if not session.get("staff_id"):
        return redirect(url_for("login"))
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if len(new_password) < 10:
        flash("رمز عبور جدید باید حداقل ۱۰ کاراکتر باشد.", "error")
        return redirect(url_for("dashboard"))
    if new_password != confirm_password:
        flash("تکرار رمز عبور با رمز جدید مطابقت ندارد.", "error")
        return redirect(url_for("dashboard"))
    with connect_db() as db:
        user = db.execute("SELECT id,password_hash FROM staff WHERE id=?", (session["staff_id"],)).fetchone()
        if not user or not check_password_hash(user["password_hash"], current_password):
            flash("رمز عبور فعلی صحیح نیست.", "error")
            return redirect(url_for("dashboard"))
        db.execute("UPDATE staff SET password_hash=? WHERE id=?",
                   (generate_password_hash(new_password), session["staff_id"]))
    session.clear()
    flash("رمز عبور با موفقیت تغییر کرد. لطفاً با رمز جدید وارد شوید.", "success")
    return redirect(url_for("login"))

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
        academy_tags = db.execute("SELECT * FROM academy_tags ORDER BY name COLLATE NOCASE").fetchall() if "blog_manage" in ROLE_PERMISSIONS.get(session["role"], set()) else []
        academy_questions = db.execute("SELECT c.*,m.username,m.display_name,m.avatar_url,p.title AS post_title FROM post_comments c JOIN members m ON m.id=c.member_id JOIN posts p ON p.id=c.post_id ORDER BY CASE WHEN c.reply_text='' THEN 0 ELSE 1 END,c.id DESC LIMIT 100").fetchall() if "blog_manage" in ROLE_PERMISSIONS.get(session["role"], set()) else []
        project_count = len(projects)
        warning_count = len(warnings)
        post_count = len(posts)
    role = session["role"]
    with connect_db() as db:
        site_images = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM site_settings")}
    return render_template("dashboard.html", projects=projects, warnings=warnings, staff=staff, posts=posts,
                           academy_tags=academy_tags, academy_questions=academy_questions,
                           project_count=project_count, warning_count=warning_count, post_count=post_count,
                           site_images=site_images, role_label=ROLES.get(role, role),
                           can_create="projects_create" in ROLE_PERMISSIONS[role],
                           can_warn="warnings_create" in ROLE_PERMISSIONS[role],
                           full_access="full_access" in ROLE_PERMISSIONS[role],
                           can_blog="blog_manage" in ROLE_PERMISSIONS[role])

@app.route("/site-settings/images", methods=["POST"])
@permission_required("full_access")
def update_site_images():
    defaults = {
        "hero_image": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1800&q=85",
        "about_image": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1000&q=85",
        "roleplay_image": "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=1100&q=85",
        "survival_image": "https://images.unsplash.com/photo-1580234811497-9df7fd2f357e?auto=format&fit=crop&w=1100&q=85",
        "gallery_image_1": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=85",
        "gallery_image_2": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=800&q=85",
        "gallery_image_3": "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=800&q=85"
    }
    values = {}
    for key, default in defaults.items():
        value = request.form.get(key, "").strip()
        if value and (not value.startswith("https://") or len(value) > 1500):
            flash("آدرس همه تصاویر باید با https:// شروع شود و معتبر باشد.", "error")
            return redirect(url_for("dashboard"))
        values[key] = value or default
    with connect_db() as db:
        for key, value in values.items():
            db.execute("UPDATE site_settings SET setting_value=? WHERE setting_key=?", (value, key))
    flash("تصاویر صفحه اصلی ذخیره شدند. برای دیدن تغییرات صفحه اصلی را تازه‌سازی کنید.", "success")
    return redirect(url_for("dashboard"))

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
    tag_filter = request.args.get("tag", type=int)
    with connect_db() as db:
        tags = db.execute("SELECT * FROM academy_tags ORDER BY name COLLATE NOCASE").fetchall()
        if tag_filter:
            posts = db.execute("SELECT p.id,p.title,p.summary,p.cover_url,p.author,p.created_at FROM posts p JOIN post_tags pt ON pt.post_id=p.id WHERE p.published=1 AND pt.tag_id=? ORDER BY p.id DESC", (tag_filter,)).fetchall()
        else:
            posts = db.execute("SELECT id,title,summary,cover_url,author,created_at FROM posts WHERE published=1 ORDER BY id DESC").fetchall()
        tags_by_post = {}
        for post in posts:
            tags_by_post[post["id"]] = db.execute("SELECT t.id,t.name FROM academy_tags t JOIN post_tags pt ON pt.tag_id=t.id WHERE pt.post_id=? ORDER BY t.name", (post["id"],)).fetchall()
    return render_template("academy.html", posts=posts, tags=tags, tags_by_post=tags_by_post, selected_tag=tag_filter)

@app.route("/academy/<int:post_id>")
def blog_post(post_id):
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=? AND published=1", (post_id,)).fetchone()
        tags = db.execute("SELECT t.id,t.name FROM academy_tags t JOIN post_tags pt ON pt.tag_id=t.id WHERE pt.post_id=? ORDER BY t.name", (post_id,)).fetchall()
        comments = db.execute("SELECT c.*,m.username,m.display_name,m.avatar_url FROM post_comments c JOIN members m ON m.id=c.member_id WHERE c.post_id=? ORDER BY c.id DESC", (post_id,)).fetchall()
        feedback = db.execute("SELECT vote,COUNT(*) AS total FROM post_feedback WHERE post_id=? GROUP BY vote", (post_id,)).fetchall()
        my_vote = db.execute("SELECT vote FROM post_feedback WHERE post_id=? AND member_id=?", (post_id, session.get("member_id", -1))).fetchone()
    if not post:
        abort(404)
    vote_counts = {row["vote"]: row["total"] for row in feedback}
    return render_template("post.html", post=post, tags=tags, comments=comments,
                           likes=vote_counts.get(1, 0), dislikes=vote_counts.get(-1, 0),
                           my_vote=my_vote["vote"] if my_vote else 0)

@app.route("/academy/<int:post_id>/feedback", methods=["POST"])
def academy_feedback(post_id):
    if not session.get("member_id"):
        flash("برای ثبت نظر مفید بودن آموزش، ابتدا در سایت وارد شوید.", "error")
        return redirect(url_for("account_login", next=url_for("blog_post", post_id=post_id)))
    vote = request.form.get("vote", type=int)
    if vote not in (-1, 1):
        abort(400)
    with connect_db() as db:
        if not db.execute("SELECT id FROM posts WHERE id=? AND published=1", (post_id,)).fetchone():
            abort(404)
        db.execute("INSERT INTO post_feedback(post_id,member_id,vote) VALUES(?,?,?) ON CONFLICT(post_id,member_id) DO UPDATE SET vote=excluded.vote,created_at=CURRENT_TIMESTAMP",
                   (post_id, session["member_id"], vote))
    return redirect(url_for("blog_post", post_id=post_id) + "#article-feedback")

@app.route("/academy/<int:post_id>/comment", methods=["POST"])
def academy_comment(post_id):
    if not session.get("member_id"):
        flash("برای نوشتن دیدگاه یا پرسش، ابتدا وارد حساب کاربری شوید.", "error")
        return redirect(url_for("account_login", next=url_for("blog_post", post_id=post_id)))
    body = bleach.clean(request.form.get("body", "").strip(), tags=[], strip=True)
    if not body or len(body) > 3000:
        flash("متن دیدگاه باید بین ۱ تا ۳۰۰۰ نویسه باشد.", "error")
        return redirect(url_for("blog_post", post_id=post_id) + "#questions")
    with connect_db() as db:
        if not db.execute("SELECT id FROM posts WHERE id=? AND published=1", (post_id,)).fetchone():
            abort(404)
        db.execute("INSERT INTO post_comments(post_id,member_id,body) VALUES(?,?,?)",
                   (post_id, session["member_id"], body))
    flash("دیدگاه یا پرسش شما ثبت شد.", "success")
    return redirect(url_for("blog_post", post_id=post_id) + "#questions")

@app.route("/academy/comments/<int:comment_id>/reply", methods=["POST"])
@permission_required("blog_manage")
def reply_to_comment(comment_id):
    reply_text = bleach.clean(request.form.get("reply_text", "").strip(), tags=[], strip=True)
    if not reply_text or len(reply_text) > 3000:
        flash("پاسخ باید بین ۱ تا ۳۰۰۰ نویسه باشد.", "error")
        return redirect(url_for("dashboard") + "#academy-questions")
    with connect_db() as db:
        comment = db.execute("SELECT post_id FROM post_comments WHERE id=?", (comment_id,)).fetchone()
        if not comment:
            abort(404)
        db.execute("UPDATE post_comments SET reply_text=?,replied_by=?,replied_at=CURRENT_TIMESTAMP WHERE id=?",
                   (reply_text, session["username"], comment_id))
    flash("پاسخ شما ثبت شد.", "success")
    return redirect(url_for("dashboard") + "#academy-questions")

@app.route("/academy/tags/create", methods=["POST"])
@permission_required("blog_manage")
def create_academy_tag():
    import re
    name = bleach.clean(request.form.get("name", "").strip(), tags=[], strip=True)
    if not name or len(name) > 40:
        flash("نام تگ باید بین ۱ تا ۴۰ نویسه باشد.", "error")
    else:
        slug = "tag-" + __import__("hashlib").sha256(name.casefold().encode("utf-8")).hexdigest()[:12]
        try:
            with connect_db() as db:
                db.execute("INSERT INTO academy_tags(name,slug) VALUES(?,?)", (name, slug))
            flash("تگ جدید ساخته شد.", "success")
        except sqlite3.IntegrityError:
            flash("این تگ قبلاً ساخته شده است.", "error")
    return redirect(url_for("dashboard") + "#academy-tags")

@app.route("/account/register", methods=["GET", "POST"])
def account_register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        display_name = bleach.clean(request.form.get("display_name", "").strip(), tags=[], strip=True)[:80]
        if len(username) < 3 or len(username) > 30 or not username.replace("_", "").isalnum() or len(password) < 10:
            flash("نام کاربری باید ۳ تا ۳۰ حرف/عدد یا زیرخط و رمز عبور حداقل ۱۰ کاراکتر باشد.", "error")
        else:
            try:
                with connect_db() as db:
                    db.execute("INSERT INTO members(username,password_hash,display_name) VALUES(?,?,?)",
                               (username, generate_password_hash(password), display_name or username))
                flash("ثبت‌نام انجام شد؛ اکنون وارد حساب شوید.", "success")
                return redirect(url_for("account_login"))
            except sqlite3.IntegrityError:
                flash("این نام کاربری قبلاً ثبت شده است.", "error")
    return render_template("account_register.html")

@app.route("/account/login", methods=["GET", "POST"])
def account_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            member = db.execute("SELECT * FROM members WHERE username=?", (username,)).fetchone()
        if member and check_password_hash(member["password_hash"], password):
            session["member_id"] = member["id"]
            session["member_username"] = member["username"]
            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("account_profile"))
        flash("نام کاربری یا رمز عبور اشتباه است.", "error")
    return render_template("account_login.html")

@app.route("/account/logout", methods=["POST"])
def account_logout():
    session.pop("member_id", None)
    session.pop("member_username", None)
    return redirect(url_for("index"))

@app.route("/account/profile", methods=["GET", "POST"])
def account_profile():
    if not session.get("member_id"):
        return redirect(url_for("account_login"))
    with connect_db() as db:
        member = db.execute("SELECT * FROM members WHERE id=?", (session["member_id"],)).fetchone()
        if not member:
            session.pop("member_id", None)
            session.pop("member_username", None)
            return redirect(url_for("account_login"))
        if request.method == "POST":
            display_name = bleach.clean(request.form.get("display_name", "").strip(), tags=[], strip=True)[:80]
            avatar_url = request.form.get("avatar_url", "").strip()
            if avatar_url and (not avatar_url.startswith("https://") or len(avatar_url) > 1500):
                flash("لینک تصویر پروفایل باید با https:// شروع شود.", "error")
            else:
                db.execute("UPDATE members SET display_name=?,avatar_url=? WHERE id=?",
                           (display_name or member["username"], avatar_url, member["id"]))
                flash("پروفایل ذخیره شد.", "success")
                return redirect(url_for("account_profile"))
        member = db.execute("SELECT * FROM members WHERE id=?", (session["member_id"],)).fetchone()
        comments = db.execute("SELECT c.id,c.body,c.created_at,c.post_id,p.title FROM post_comments c JOIN posts p ON p.id=c.post_id WHERE c.member_id=? ORDER BY c.id DESC LIMIT 20", (session["member_id"],)).fetchall()
    return render_template("account_profile.html", member=member, comments=comments)

@app.route("/academy/editor", methods=["GET", "POST"])
@permission_required("blog_manage")
def blog_editor():
    post_id = request.args.get("id", type=int)
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone() if post_id else None
        tags = db.execute("SELECT * FROM academy_tags ORDER BY name COLLATE NOCASE").fetchall()
        selected_tag_ids = [row["tag_id"] for row in db.execute("SELECT tag_id FROM post_tags WHERE post_id=?", (post_id,)).fetchall()] if post_id else []
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            summary = request.form.get("summary", "").strip()
            cover_url = request.form.get("cover_url", "").strip()
            content = bleach.clean(request.form.get("content", ""), tags=BLOG_TAGS, attributes=BLOG_ATTRS,
                                   protocols=BLOG_PROTOCOLS, strip=True)
            published = 1 if request.form.get("published") == "1" else 0
            selected_tag_ids = list({int(value) for value in request.form.getlist("tag_ids") if value.isdigit()})
            if not title or not bleach.clean(content, tags=[], strip=True).strip():
                flash("عنوان و محتوای مقاله الزامی است.", "error")
            elif post_id and post:
                db.execute("UPDATE posts SET title=?,summary=?,cover_url=?,content=?,published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (title, summary, cover_url, content, published, post_id))
                db.execute("DELETE FROM post_tags WHERE post_id=?", (post_id,))
                for tag_id in selected_tag_ids:
                    if db.execute("SELECT id FROM academy_tags WHERE id=?", (tag_id,)).fetchone():
                        db.execute("INSERT OR IGNORE INTO post_tags(post_id,tag_id) VALUES(?,?)", (post_id, tag_id))
                flash("مقاله به‌روزرسانی شد.", "success")
                return redirect(url_for("dashboard") + "#academy-content")
            else:
                cur = db.execute("INSERT INTO posts(title,summary,cover_url,content,author,published) VALUES(?,?,?,?,?,?)",
                                 (title, summary, cover_url, content, session["username"], published))
                new_post_id = cur.lastrowid
                for tag_id in selected_tag_ids:
                    if db.execute("SELECT id FROM academy_tags WHERE id=?", (tag_id,)).fetchone():
                        db.execute("INSERT OR IGNORE INTO post_tags(post_id,tag_id) VALUES(?,?)", (new_post_id, tag_id))
                flash("مقاله ایجاد شد.", "success")
                return redirect(url_for("dashboard") + "#academy-content")
    return render_template("editor.html", post=post, tags=tags, selected_tag_ids=selected_tag_ids)

@app.route("/academy/<int:post_id>/delete", methods=["POST"])
@permission_required("blog_manage")
def delete_post(post_id):
    with connect_db() as db:
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    flash("مقاله حذف شد.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
