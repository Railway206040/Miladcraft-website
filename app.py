from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
try:
    import sqlite3
except ImportError:  # Python Workers use D1 instead of the native SQLite extension.
    sqlite3 = None
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import bleach
from flask import Flask, Response, abort, flash, g, has_request_context, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask.sessions import SecureCookieSessionInterface
from jinja2 import BaseLoader, TemplateNotFound
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from pyodide.ffi import run_sync
    from workers import wsgi
    IS_CLOUDFLARE = True
except ImportError:
    run_sync = None
    wsgi = None
    IS_CLOUDFLARE = False

app = Flask(
    __name__,
    static_folder=None if IS_CLOUDFLARE else "static",
    template_folder=None if IS_CLOUDFLARE else "templates",
)
app.secret_key = os.environ.get("SECRET_KEY", "development-only-change-this-before-deploying")

class CloudflareSessionInterface(SecureCookieSessionInterface):
    def get_signing_serializer(self, application):
        if IS_CLOUDFLARE and has_request_context():
            env = request.environ.get("workers.env")
            secret = getattr(env, "SECRET_KEY", None) if env is not None else None
            if not secret:
                raise RuntimeError("Cloudflare SECRET_KEY secret is not configured")
            original = application.secret_key
            application.secret_key = str(secret)
            try:
                return super().get_signing_serializer(application)
            finally:
                application.secret_key = original
        return super().get_signing_serializer(application)

if IS_CLOUDFLARE:
    app.session_interface = CloudflareSessionInterface()

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
)

SERVER_ADDRESS = "miladcraft.seedloaf.gg"
SERVER_VERSION = "1.21.11"
TELEGRAM_URL = os.environ.get("TELEGRAM_URL", "https://t.me/Milad_craft")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "miladcraft.db")))
SITE_UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(DATA_DIR / "uploads")))
if not IS_CLOUDFLARE:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def worker_env():
    if not IS_CLOUDFLARE:
        return None
    return request.environ.get("workers.env")

def config_value(name, default=""):
    env = worker_env()
    if env is not None:
        value = getattr(env, name, None)
        if value is not None:
            return str(value)
    return os.environ.get(name, default)

def store_upload(key, raw, mime):
    if IS_CLOUDFLARE:
        env = worker_env()
        if env is None or not getattr(env, "UPLOADS", None):
            raise RuntimeError("Cloudflare UPLOADS binding is not configured")
        encoded = base64.b64encode(raw).decode("ascii")
        run_sync(env.UPLOADS.put(key, encoded, {"metadata": {"contentType": mime}}))
    else:
        target = SITE_UPLOAD_DIR / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return "/site-uploads/" + key

def load_upload(key):
    env = worker_env()
    if env is None or not getattr(env, "UPLOADS", None):
        return None
    encoded = run_sync(env.UPLOADS.get(key))
    if encoded is None:
        return None
    return base64.b64decode(str(encoded))

if IS_CLOUDFLARE:
    from templates_bundle import TEMPLATES

    class CloudflareTemplateLoader(BaseLoader):
        def get_source(self, environment, template):
            if template.startswith("/") or ".." in Path(template).parts:
                raise TemplateNotFound(template)
            source = TEMPLATES.get(template)
            if source is None:
                raise TemplateNotFound(template)
            return source, "bundled://" + template, lambda: True

    app.jinja_loader = CloudflareTemplateLoader()

    @app.route("/static/<path:filename>", endpoint="static")
    def cloudflare_static_asset(filename):
        env = request.environ.get("workers.env")
        if env is None or not getattr(env, "ASSETS", None):
            abort(404)
        response = run_sync(env.ASSETS.fetch("https://assets.local/" + filename))
        if response.status == 404:
            abort(404)
        body = run_sync(response.bytes())
        content_type = response.headers.get("content-type") or "application/octet-stream"
        return Response(body, status=response.status, headers={"Content-Type": str(content_type),
                        "Cache-Control": "public, max-age=3600"})

ROLE_LABELS = {
    "player": "بازیکن",
    "builder": "Builder",
    "hbuilder": "H-Builder",
    "helper": "Helper",
    "moderator": "Moderator",
    "admin": "Admin",
    "manager": "Manager",
    "developer": "Developer",
    "owner": "Owner",
}
ROLE_COLORS = {
    "player": "#94a3b8",
    "builder": "#22d3c5",
    "hbuilder": "#a78bfa",
    "helper": "#facc15",
    "moderator": "#fb923c",
    "admin": "#dc2626",
    "manager": "#60a5fa",
    "developer": "#a1a1aa",
    "owner": "#fca5a5",
}
STAFF_ROLES = ("builder", "hbuilder", "helper", "moderator", "admin", "manager", "developer", "owner")
MASTER_ROLES = {"developer", "owner"}
CONTENT_ROLES = {"developer", "owner", "admin", "manager"}
PROJECT_MANAGERS = {"hbuilder", "manager", "admin", "developer", "owner"}
WARNING_ROLES = {"hbuilder", "manager", "admin", "developer", "owner"}
BLOG_TAGS = ["p", "br", "strong", "b", "em", "i", "u", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "a", "img", "hr", "code", "pre", "mark", "table", "thead", "tbody", "tr", "th", "td"]
BLOG_ATTRS = {"a": ["href", "title", "target", "rel"], "img": ["src", "alt", "title", "width"]}
BLOG_PROTOCOLS = ["http", "https", "mailto"]

IMAGE_DEFAULTS = {
    "site_logo": "",
    "hero_image": "/static/images/minecraft-world.svg",
    "about_image": "/static/images/minecraft-forest.svg",
    "roleplay_image": "/static/images/minecraft-village.svg",
    "survival_image": "/static/images/minecraft-forest.svg",
    "gallery_image_2": "/static/images/minecraft-night.svg",
    "gallery_image_3": "/static/images/minecraft-world.svg",
}

def connect_db():
    if IS_CLOUDFLARE:
        from cloudflare_db import D1Connection
        env = worker_env()
        if env is None or not getattr(env, "DB", None):
            raise RuntimeError("Cloudflare DB binding is not configured")
        return D1Connection(env.DB)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db

def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

def _add_column(db, table, name, definition):
    if name not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

def init_db():
    with connect_db() as db:
        notification_table = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='notifications'").fetchone()
        if notification_table and "CHECK(recipient_type IN ('member','staff'))" in (notification_table["sql"] or "") and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_notifications'").fetchone():
            db.execute("ALTER TABLE notifications RENAME TO legacy_notifications")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_comments'").fetchone():
            if "account_id" not in _columns(db, "post_comments") and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_post_comments'").fetchone():
                db.execute("ALTER TABLE post_comments RENAME TO legacy_post_comments")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_feedback'").fetchone():
            if "account_id" not in _columns(db, "post_feedback") and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_post_feedback'").fetchone():
                db.execute("ALTER TABLE post_feedback RENAME TO legacy_post_feedback")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL COLLATE NOCASE UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'player',
          display_name TEXT NOT NULL DEFAULT '',
          avatar_url TEXT NOT NULL DEFAULT '',
          bio TEXT NOT NULL DEFAULT '',
          minecraft_username TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '',
          telegram TEXT NOT NULL DEFAULT '',
          discord TEXT NOT NULL DEFAULT '',
          age INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_login TEXT,
          is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS site_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, recipient_type TEXT NOT NULL DEFAULT 'account', recipient_id INTEGER NOT NULL,
          title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', target_url TEXT NOT NULL DEFAULT '/',
          is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS news (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL, cover_url TEXT NOT NULL DEFAULT '', author TEXT NOT NULL,
          published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
          required_builders INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'Open',
          created_by TEXT NOT NULL, claimed_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS project_members (
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(project_id, account_id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', assigned_to INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
          status TEXT NOT NULL DEFAULT 'todo', created_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS warnings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, staff_username TEXT NOT NULL, reason TEXT NOT NULL,
          evidence_url TEXT NOT NULL DEFAULT '', evidence_data TEXT NOT NULL DEFAULT '',
          issued_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS staff_activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
          username TEXT NOT NULL, event_type TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS staff_presence (
          username TEXT PRIMARY KEY COLLATE NOCASE, is_online INTEGER NOT NULL DEFAULT 0,
          joined_at TEXT, last_seen TEXT, total_minutes INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS conversations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('group','private')),
          title TEXT NOT NULL, created_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS conversation_members (
          conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          PRIMARY KEY(conversation_id, account_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
          sender_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS posts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL, cover_url TEXT NOT NULL DEFAULT '', author TEXT NOT NULL,
          published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS academy_tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS post_tags (
          post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          tag_id INTEGER NOT NULL REFERENCES academy_tags(id) ON DELETE CASCADE,
          PRIMARY KEY(post_id, tag_id)
        );
        CREATE TABLE IF NOT EXISTS post_comments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, body TEXT NOT NULL,
          reply_text TEXT NOT NULL DEFAULT '', replied_by TEXT NOT NULL DEFAULT '', replied_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS post_feedback (
          post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
          account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          vote INTEGER NOT NULL CHECK(vote IN (-1,1)), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(post_id, account_id)
        );
        CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status, id DESC);
        CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_to, status);
        CREATE INDEX IF NOT EXISTS idx_activity_account ON staff_activity(account_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_account ON notifications(recipient_id, is_read, id DESC);
        """)
        _add_column(db, "warnings", "evidence_data", "TEXT NOT NULL DEFAULT ''")
        _add_column(db, "notifications", "recipient_type", "TEXT NOT NULL DEFAULT 'account'")
        _add_column(db, "accounts", "bio", "TEXT NOT NULL DEFAULT ''")
        # Import the old split account tables only once; later deployments must preserve role changes.
        if not db.execute("SELECT 1 FROM app_meta WHERE meta_key='migration:legacy_accounts_v1'").fetchone():
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'").fetchone():
                old_cols = _columns(db, "members")
                if {"username", "password_hash"}.issubset(old_cols):
                    for row in db.execute("SELECT * FROM members").fetchall():
                        display = row["display_name"] if "display_name" in old_cols else row["username"]
                        avatar = row["avatar_url"] if "avatar_url" in old_cols else ""
                        created = row["created_at"] if "created_at" in old_cols else None
                        db.execute("""INSERT OR IGNORE INTO accounts(username,password_hash,role,display_name,avatar_url,created_at)
                            VALUES(?,?,'player',?,?,COALESCE(?,CURRENT_TIMESTAMP))""",
                            (row["username"], row["password_hash"], display or row["username"], avatar or "", created))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='staff'").fetchone():
                old_cols = _columns(db, "staff")
                if {"username", "password_hash", "role"}.issubset(old_cols):
                    for row in db.execute("SELECT * FROM staff").fetchall():
                        display = row["display_name"] if "display_name" in old_cols else row["username"]
                        avatar = row["avatar_url"] if "avatar_url" in old_cols else ""
                        created = row["created_at"] if "created_at" in old_cols else None
                        role = row["role"] if row["role"] in STAFF_ROLES else "builder"
                        db.execute("""INSERT INTO accounts(username,password_hash,role,display_name,avatar_url,created_at)
                            VALUES(?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))
                            ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role,
                            display_name=CASE WHEN excluded.display_name='' THEN accounts.display_name ELSE excluded.display_name END,
                            avatar_url=CASE WHEN excluded.avatar_url='' THEN accounts.avatar_url ELSE excluded.avatar_url END""",
                            (row["username"], row["password_hash"], role, display or row["username"], avatar or "", created))

            db.execute("INSERT INTO app_meta(meta_key,meta_value) VALUES('migration:legacy_accounts_v1','done')")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_post_comments'").fetchone():
            for old in db.execute("SELECT * FROM legacy_post_comments").fetchall():
                member = db.execute("SELECT username FROM members WHERE id=?", (old["member_id"],)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'").fetchone() else None
                account = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (member["username"],)).fetchone() if member else None
                if account:
                    db.execute("INSERT OR IGNORE INTO post_comments(id,post_id,account_id,body,reply_text,replied_by,replied_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (old["id"],old["post_id"],account["id"],old["body"],old["reply_text"],old["replied_by"],old["replied_at"],old["created_at"]))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_post_feedback'").fetchone():
            for old in db.execute("SELECT * FROM legacy_post_feedback").fetchall():
                member = db.execute("SELECT username FROM members WHERE id=?", (old["member_id"],)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'").fetchone() else None
                account = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (member["username"],)).fetchone() if member else None
                if account:
                    db.execute("INSERT OR IGNORE INTO post_feedback(post_id,account_id,vote,created_at) VALUES(?,?,?,?)",
                        (old["post_id"],account["id"],old["vote"],old["created_at"]))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_notifications'").fetchone():
            for old in db.execute("SELECT * FROM legacy_notifications").fetchall():
                if old["recipient_type"] in ("member","staff"):
                    legacy_table = "members" if old["recipient_type"] == "member" else "staff"
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (legacy_table,)).fetchone():
                        legacy_account = db.execute("SELECT username FROM " + legacy_table + " WHERE id=?", (old["recipient_id"],)).fetchone()
                        target_account = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (legacy_account["username"],)).fetchone() if legacy_account else None
                        if target_account:
                            db.execute("""INSERT OR IGNORE INTO notifications(id,recipient_type,recipient_id,title,body,target_url,is_read,created_at)
                                VALUES(?, 'account', ?, ?, ?, ?, ?, ?)""",
                                (old["id"],target_account["id"],old["title"],old["body"],old["target_url"],old["is_read"],old["created_at"]))
        # Migrate old project claims to the new many-builder membership table.
        if "claimed_by" in _columns(db, "projects"):
            for row in db.execute("SELECT id,claimed_by FROM projects WHERE claimed_by IS NOT NULL AND claimed_by<>''").fetchall():
                account = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (row["claimed_by"],)).fetchone()
                if account:
                    db.execute("INSERT OR IGNORE INTO project_members(project_id,account_id) VALUES(?,?)", (row["id"], account["id"]))
        for key, value in IMAGE_DEFAULTS.items():
            db.execute("INSERT OR IGNORE INTO site_settings(setting_key,setting_value) VALUES(?,?)", (key, value))
        # Migrate only known built-in remote defaults to local artwork; keep staff-customized URLs intact.
        legacy_image_defaults = {
            "hero_image": [
                "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1800&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_The_Bogged_1920x1080.jpg",
            ],
            "about_image": [
                "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1000&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_The_Creaking_1920x1080.jpg",
            ],
            "roleplay_image": [
                "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=1100&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_Trial_Chambers_1920x1080.jpg",
            ],
            "survival_image": [
                "https://images.unsplash.com/photo-1580234811497-9df7fd2f357e?auto=format&fit=crop&w=1100&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_BambooJungle_1920x1080.jpg",
            ],
            "gallery_image_2": [
                "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=800&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_Trial_Chambers_1920x1080.jpg",
            ],
            "gallery_image_3": [
                "https://images.unsplash.com/photo-1493711662062-fa5416f8d4db?auto=format&fit=crop&w=800&q=85",
                "https://www.minecraft.net/content/dam/games/minecraft/key-art/MCV_The_Bogged_1920x1080.jpg",
            ],
        }
        for key, old_values in legacy_image_defaults.items():
            if key in IMAGE_DEFAULTS:
                for old_value in old_values:
                    db.execute(
                        "UPDATE site_settings SET setting_value=? WHERE setting_key=? AND setting_value=?",
                        (IMAGE_DEFAULTS[key], key, old_value),
                    )
        group = db.execute("SELECT id FROM conversations WHERE kind='group' AND title='گروه کارکنان' LIMIT 1").fetchone()
        if not group:
            group_id = db.execute("INSERT INTO conversations(kind,title) VALUES('group','گروه کارکنان')").lastrowid
        else:
            group_id = group["id"]
        # Bootstrap an initial Owner only when configured; do not overwrite an existing account password.
        username = os.environ.get("BOOTSTRAP_OWNER_USERNAME", "").strip()
        password = os.environ.get("BOOTSTRAP_OWNER_PASSWORD", "")
        if username and password and len(password) >= 10:
            found = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            if not found:
                db.execute("INSERT INTO accounts(username,password_hash,role,display_name) VALUES(?,?, 'owner',?)",
                           (username, generate_password_hash(password), username))
            elif found:
                db.execute("UPDATE accounts SET role='owner' WHERE id=?", (found["id"],))
        group = db.execute("SELECT id FROM conversations WHERE kind='group' AND title='گروه کارکنان' LIMIT 1").fetchone()
        if group:
            for row in db.execute("SELECT id FROM accounts WHERE role<>'player'").fetchall():
                db.execute("INSERT OR IGNORE INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (group["id"],row["id"]))

def log_activity(account, event_type, details=""):
    if not account:
        return
    with connect_db() as db:
        db.execute("INSERT INTO staff_activity(account_id,username,event_type,details) VALUES(?,?,?,?)",
                   (account["id"], account["username"], event_type, str(details)[:1000]))

def ensure_bootstrap_owner():
    username = config_value("BOOTSTRAP_OWNER_USERNAME", "").strip()
    password = config_value("BOOTSTRAP_OWNER_PASSWORD", "")
    if not username or not password or len(password) < 10:
        return
    with connect_db() as db:
        found = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if found:
            return
        db.execute(
            "INSERT INTO accounts(username,password_hash,role,display_name) VALUES(?,?,'owner',?)",
            (username, generate_password_hash(password), username),
        )
        group = db.execute("SELECT id FROM conversations WHERE kind='group' AND title='گروه کارکنان' LIMIT 1").fetchone()
        account = db.execute("SELECT id FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if group and account:
            db.execute("INSERT OR IGNORE INTO conversation_members(conversation_id,account_id) VALUES(?,?)",
                       (group["id"], account["id"]))

def safe_next(value, fallback):
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return fallback

def account_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "account", None):
            flash("برای ادامه ابتدا وارد حساب شوید.", "error")
            return redirect(url_for("account_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account = getattr(g, "account", None)
        if not account:
            flash("ابتدا وارد حساب شوید.", "error")
            return redirect(url_for("account_login"))
        if account["role"] == "player":
            flash("این بخش مخصوص کارکنان سرور است.", "error")
            return redirect(url_for("account_profile"))
        return view(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            account = getattr(g, "account", None)
            if not account:
                flash("ابتدا وارد حساب شوید.", "error")
                return redirect(url_for("account_login", next=request.path))
            if account["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator

def clean_text(value, limit=3000):
    return bleach.clean((value or "").strip(), tags=[], strip=True)[:limit]

@app.before_request
def prepare_request():
    if IS_CLOUDFLARE:
        app.config["SESSION_COOKIE_SECURE"] = config_value("COOKIE_SECURE", "true").lower() == "true"
        ensure_bootstrap_owner()
    g.account = None
    account_id = session.get("account_id")
    if account_id:
        with connect_db() as db:
            g.account = db.execute("SELECT * FROM accounts WHERE id=? AND is_active=1", (account_id,)).fetchone()
        if not g.account:
            session.clear()
    if request.method == "POST" and request.endpoint != "minecraft_event" and not app.config.get("TESTING"):
        token = session.get("_csrf_token", "")
        supplied = request.form.get("_csrf_token", "")
        if not token or not supplied or not hmac.compare_digest(token, supplied):
            abort(400, description="درخواست معتبر نیست؛ صفحه را تازه‌سازی کنید و دوباره تلاش کنید.")

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self' https://api.mcsrvstat.us"
    return response

@app.context_processor
def common_template_values():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    with connect_db() as db:
        site_images = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM site_settings")}
    account = getattr(g, "account", None)
    role = account["role"] if account else "player"
    return {
        "server_address": SERVER_ADDRESS, "server_version": SERVER_VERSION,
        "telegram_url": config_value("TELEGRAM_URL", TELEGRAM_URL),
        "site_images": site_images, "current_account": account, "role_labels": ROLE_LABELS,
        "role_colors": ROLE_COLORS, "current_role_label": ROLE_LABELS.get(role, role),
        "csrf_token": lambda: session.get("_csrf_token", ""),
        "csrf_field": lambda: Markup('<input type="hidden" name="_csrf_token" value="%s">' % session.get("_csrf_token", "")),
    }

@app.route("/healthz")
def health_check():
    try:
        with connect_db() as db:
            db.execute("SELECT COUNT(*) FROM accounts").fetchone()
        return jsonify(status="ok"), 200
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify(status="unavailable"), 503

@app.route("/")
def index():
    with connect_db() as db:
        latest_news = db.execute("SELECT * FROM news WHERE published=1 ORDER BY id DESC LIMIT 3").fetchall()
        latest_posts = db.execute("SELECT * FROM posts WHERE published=1 ORDER BY id DESC LIMIT 3").fetchall()
    return render_template("index.html", latest_news=latest_news, latest_posts=latest_posts)

@app.route("/robots.txt")
def robots_txt():
    return "User-agent: *\nAllow: /\nDisallow: /staff\nDisallow: /account/profile\nSitemap: " + request.url_root.rstrip("/") + "/sitemap.xml\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.route("/sitemap.xml")
def sitemap_xml():
    paths = [url_for("index"), url_for("news_page"), url_for("academy")]
    with connect_db() as db:
        paths += [url_for("news_detail", news_id=r["id"]) for r in db.execute("SELECT id FROM news WHERE published=1")]
        paths += [url_for("blog_post", post_id=r["id"]) for r in db.execute("SELECT id FROM posts WHERE published=1")]
    from xml.sax.saxutils import escape
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join("<url><loc>" + escape(request.url_root.rstrip("/") + path) + "</loc></url>" for path in paths)
    body += "</urlset>"
    return body, 200, {"Content-Type": "application/xml; charset=utf-8"}

@app.route("/api/server-status")
def server_status():
    try:
        if IS_CLOUDFLARE:
            from js import fetch as js_fetch
            response = run_sync(js_fetch("https://api.mcsrvstat.us/3/" + SERVER_ADDRESS,
                                         {"headers": {"User-Agent": "MiladCraft-Website/2.0"}}))
            if not response.ok:
                raise RuntimeError("Minecraft status provider returned an error")
            data = json.loads(run_sync(response.text()))
        else:
            req = Request("https://api.mcsrvstat.us/3/" + SERVER_ADDRESS, headers={"User-Agent": "MiladCraft-Website/2.0"})
            with urlopen(req, timeout=3.5) as response:
                data = json.loads(response.read().decode("utf-8"))
        online = bool(data.get("online"))
        return jsonify({"online": online, "host": SERVER_ADDRESS,
                        "players_online": data.get("players", {}).get("online", 0) if online else 0,
                        "players_max": data.get("players", {}).get("max", 0) if online else 0,
                        "version": data.get("version", "") if online else ""})
    except Exception:
        # A status-provider failure must never take down the website on Workers.
        app.logger.exception("Minecraft status lookup failed")
        return jsonify({"online": None, "host": SERVER_ADDRESS, "players_online": 0, "players_max": 0, "version": "", "error": "status_unavailable"})

@app.route("/account")
def account_portal():
    return render_template("account_portal.html")

@app.route("/account/register", methods=["GET", "POST"])
def account_register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        display = clean_text(request.form.get("display_name", ""), 80) or username
        minecraft = clean_text(request.form.get("minecraft_username", ""), 32)
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash("نام کاربری باید ۳ تا ۳۰ نویسه و شامل حروف انگلیسی، عدد یا زیرخط باشد.", "error")
        elif len(password) < 10:
            flash("رمز عبور باید حداقل ۱۰ نویسه باشد.", "error")
        elif password != confirm:
            flash("تکرار رمز عبور مطابقت ندارد.", "error")
        else:
            try:
                with connect_db() as db:
                    db.execute("""INSERT INTO accounts(username,password_hash,role,display_name,minecraft_username)
                        VALUES(?,?,'player',?,?)""",
                        (username, generate_password_hash(password), display, minecraft))
                flash("حساب بازیکن ساخته شد؛ حالا وارد شوید.", "success")
                return redirect(url_for("account_login"))
            except Exception as exc:
                if "UNIQUE constraint" in str(exc):
                    flash("این نام کاربری قبلاً ثبت شده است.", "error")
                else:
                    raise
    return render_template("account_register.html")

@app.route("/account/login", methods=["GET", "POST"])
def account_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            account = db.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE AND is_active=1", (username,)).fetchone()
            if account and check_password_hash(account["password_hash"], password):
                db.execute("UPDATE accounts SET last_login=CURRENT_TIMESTAMP WHERE id=?", (account["id"],))
                session.clear()
                session.permanent = True
                session["account_id"] = account["id"]
                target = safe_next(request.args.get("next", ""), url_for("account_profile"))
                flash("با موفقیت وارد شدید.", "success")
                return redirect(target)
        flash("نام کاربری یا رمز عبور اشتباه است.", "error")
    return render_template("account_login.html")

@app.route("/account/logout", methods=["POST"])
def account_logout():
    session.clear()
    flash("از حساب خارج شدید.", "success")
    return redirect(url_for("index"))

@app.route("/account/profile", methods=["GET", "POST"])
@account_required
def account_profile():
    if request.method == "POST":
        display = clean_text(request.form.get("display_name", ""), 80) or g.account["username"]
        bio = clean_text(request.form.get("bio", ""), 500)
        minecraft = clean_text(request.form.get("minecraft_username", ""), 32)
        telegram = clean_text(request.form.get("telegram", ""), 50)
        discord = clean_text(request.form.get("discord", ""), 80)
        avatar = g.account["avatar_url"]
        uploaded = request.files.get("avatar_file")
        if uploaded and uploaded.filename:
            mime = uploaded.mimetype or ""
            raw = uploaded.read(1_500_001)
            if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"} or not raw or len(raw) > 1_500_000:
                flash("تصویر باید PNG/JPG/WEBP/GIF و حداکثر ۱٫۵ مگابایت باشد.", "error")
                return redirect(url_for("account_profile"))
            extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[mime]
            avatar = store_upload("avatars/" + secrets.token_hex(16) + extension, raw, mime)
        with connect_db() as db:
            db.execute("""UPDATE accounts SET display_name=?,bio=?,minecraft_username=?,telegram=?,discord=?,avatar_url=? WHERE id=?""",
                       (display, bio, minecraft, telegram, discord, avatar, g.account["id"]))
        flash("پروفایل ذخیره شد.", "success")
        return redirect(url_for("account_profile"))
    with connect_db() as db:
        comments = db.execute("SELECT c.*,p.title,p.id AS article_id FROM post_comments c JOIN posts p ON p.id=c.post_id WHERE c.account_id=? ORDER BY c.id DESC LIMIT 20", (g.account["id"],)).fetchall()
        notifications = db.execute("SELECT * FROM notifications WHERE recipient_id=? ORDER BY id DESC LIMIT 30", (g.account["id"],)).fetchall()
        unread_count = db.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND is_read=0", (g.account["id"],)).fetchone()[0]
        activity = db.execute("SELECT * FROM staff_activity WHERE account_id=? ORDER BY id DESC LIMIT 20", (g.account["id"],)).fetchall() if g.account["role"] != "player" else []
        presence = db.execute("SELECT * FROM staff_presence WHERE username=? COLLATE NOCASE", (g.account["username"],)).fetchone()
        warnings = db.execute("SELECT * FROM warnings WHERE staff_username=? COLLATE NOCASE ORDER BY id DESC LIMIT 30", (g.account["username"],)).fetchall() if g.account["role"] != "player" else []
    return render_template("account_profile.html", comments=comments, notifications=notifications, unread_count=unread_count, activity=activity, presence=presence, warnings=warnings)

@app.route("/staff/login")
def staff_login():
    return redirect(url_for("account_login"))

@app.route("/staff/logout", methods=["POST"])
def staff_logout():
    return account_logout()

@app.route("/staff/profile")
def staff_profile():
    if g.account and g.account["role"] != "player":
        return redirect(url_for("account_profile"))
    return redirect(url_for("account_login"))

@app.route("/staff")
@staff_required
def staff_dashboard():
    role = g.account["role"]
    allowed_sections = {"projects", "warnings", "activity", "messenger", "staff-accounts", "news-management", "academy-content", "site-settings"}
    requested_section = request.args.get("section", "").strip()
    active_section = requested_section if requested_section in allowed_sections else ""
    if active_section == "staff-accounts" and role not in MASTER_ROLES:
        abort(403)
    if active_section in {"news-management", "academy-content", "site-settings", "academy-questions", "academy-tags"} and role not in CONTENT_ROLES:
        abort(403)
    with connect_db() as db:
        projects = db.execute("""SELECT p.*,COUNT(DISTINCT pm.account_id) AS assigned_count,
            COUNT(DISTINCT t.id) AS task_count,
            COUNT(DISTINCT CASE WHEN t.status='done' THEN t.id END) AS completed_tasks
            FROM projects p LEFT JOIN project_members pm ON pm.project_id=p.id
            LEFT JOIN tasks t ON t.project_id=p.id GROUP BY p.id ORDER BY p.id DESC LIMIT 100""").fetchall()
        my_tasks = db.execute("""SELECT t.*,p.title AS project_title,a.username AS assignee_name
            FROM tasks t LEFT JOIN projects p ON p.id=t.project_id LEFT JOIN accounts a ON a.id=t.assigned_to
            WHERE t.assigned_to=? OR (? IN ('developer','owner','manager','admin','hbuilder') AND t.assigned_to IS NULL)
            ORDER BY CASE t.status WHEN 'todo' THEN 0 WHEN 'doing' THEN 1 ELSE 2 END,t.id DESC LIMIT 50""", (g.account["id"], role)).fetchall()
        warnings = db.execute("SELECT * FROM warnings WHERE staff_username=? COLLATE NOCASE ORDER BY id DESC LIMIT 20", (g.account["username"],)).fetchall()
        recent_warnings = db.execute("SELECT * FROM warnings ORDER BY id DESC LIMIT 30").fetchall() if role in WARNING_ROLES else []
        staff = db.execute("SELECT * FROM accounts WHERE role<>'player' ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'developer' THEN 1 ELSE 2 END,username").fetchall()
        members = db.execute("SELECT id,username,display_name,created_at FROM accounts WHERE role='player' ORDER BY id DESC LIMIT 200").fetchall() if role in MASTER_ROLES else []
        activity = db.execute("SELECT * FROM staff_activity ORDER BY id DESC LIMIT 40").fetchall() if role in MASTER_ROLES | {"manager","admin","hbuilder"} else db.execute("SELECT * FROM staff_activity WHERE account_id=? ORDER BY id DESC LIMIT 20", (g.account["id"],)).fetchall()
        news_items = db.execute("SELECT * FROM news ORDER BY id DESC LIMIT 30").fetchall() if role in CONTENT_ROLES else []
        posts = db.execute("SELECT * FROM posts ORDER BY id DESC LIMIT 30").fetchall() if role in CONTENT_ROLES else []
        tags = db.execute("SELECT * FROM academy_tags ORDER BY name").fetchall() if role in CONTENT_ROLES else []
        comments = db.execute("""SELECT c.*,a.username,a.display_name,p.title AS post_title FROM post_comments c
            JOIN accounts a ON a.id=c.account_id JOIN posts p ON p.id=c.post_id ORDER BY c.id DESC LIMIT 50""").fetchall() if role in CONTENT_ROLES else []
        conversations = db.execute("""SELECT c.* FROM conversations c JOIN conversation_members cm ON cm.conversation_id=c.id
            WHERE cm.account_id=? ORDER BY CASE c.kind WHEN 'group' THEN 0 ELSE 1 END,c.id""", (g.account["id"],)).fetchall()
        conversation_data = []
        for convo in conversations:
            messages = db.execute("""SELECT m.*,a.username AS sender_username,a.display_name AS sender_name FROM messages m
                LEFT JOIN accounts a ON a.id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id DESC LIMIT 30""", (convo["id"],)).fetchall()
            title = convo["title"]
            if convo["kind"] == "private":
                other = db.execute("""SELECT a.username FROM conversation_members cm JOIN accounts a ON a.id=cm.account_id
                    WHERE cm.conversation_id=? AND cm.account_id<>? LIMIT 1""", (convo["id"],g.account["id"])).fetchone()
                if other:
                    title = "پیام خصوصی با " + other["username"]
            conversation_data.append({"id":convo["id"],"kind":convo["kind"],"title":title,"messages":list(reversed(messages))})
        unread_count = db.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND is_read=0", (g.account["id"],)).fetchone()[0]
        online_count = db.execute("SELECT COUNT(*) FROM staff_presence WHERE is_online=1").fetchone()[0]
        builders = db.execute("SELECT id,username,display_name,role FROM accounts WHERE role='builder' ORDER BY username").fetchall()
        project_builders = db.execute("""SELECT pm.project_id,a.id,a.username,a.display_name FROM project_members pm
            JOIN accounts a ON a.id=pm.account_id WHERE a.role='builder' ORDER BY a.username""").fetchall()
        joined_project_ids = {r["project_id"] for r in db.execute("SELECT project_id FROM project_members WHERE account_id=?", (g.account["id"],)).fetchall()}
        site_images = {r["setting_key"]:r["setting_value"] for r in db.execute("SELECT setting_key,setting_value FROM site_settings")}
    template_name = "dashboard.html" if active_section else "staff_home.html"
    return render_template(template_name, active_section=active_section, projects=projects, my_tasks=my_tasks, warnings=warnings,
        recent_warnings=recent_warnings, staff=staff, members=members, activity=activity,
        news_items=news_items, posts=posts, tags=tags, comments=comments,
        conversations=conversation_data, unread_count=unread_count, online_count=online_count, builders=builders, project_builders=project_builders,
        joined_project_ids=joined_project_ids, site_images=site_images, role_label=ROLE_LABELS.get(role,role), can_manage_projects=role in PROJECT_MANAGERS,
        can_warn=role in WARNING_ROLES, can_manage_staff=role in MASTER_ROLES, can_manage_content=role in CONTENT_ROLES)

@app.route("/staff/change-password", methods=["POST"])
@account_required
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if len(new) < 10 or new != confirm:
        flash("رمز جدید باید حداقل ۱۰ نویسه باشد و با تکرار آن مطابقت داشته باشد.", "error")
        return redirect(url_for("account_profile"))
    if not check_password_hash(g.account["password_hash"], current):
        flash("رمز فعلی درست نیست.", "error")
        return redirect(url_for("account_profile"))
    with connect_db() as db:
        db.execute("UPDATE accounts SET password_hash=? WHERE id=?", (generate_password_hash(new), g.account["id"]))
    session.clear()
    flash("رمز تغییر کرد؛ دوباره وارد شوید.", "success")
    return redirect(url_for("account_login"))

@app.route("/projects/create", methods=["POST"])
@staff_required
def create_project():
    if g.account["role"] not in PROJECT_MANAGERS:
        abort(403)
    title = clean_text(request.form.get("title", ""), 160)
    description = clean_text(request.form.get("description", ""), 5000)
    try:
        required = max(1, min(50, int(request.form.get("required_builders", "1"))))
    except ValueError:
        required = 1
    if not title or not description:
        flash("عنوان و توضیحات پروژه الزامی است.", "error")
        return redirect(url_for("staff_dashboard", section="projects"))
    with connect_db() as db:
        db.execute("INSERT INTO projects(title,description,required_builders,status,created_by) VALUES(?,?,?,'Open',?)",
                   (title,description,required,g.account["username"]))
    log_activity(g.account,"project_created",title)
    flash("پروژه ساخته شد.", "success")
    return redirect(url_for("staff_dashboard", section="projects"))

@app.route("/projects/<int:project_id>/join", methods=["POST"])
@staff_required
def join_project(project_id):
    if g.account["role"] not in {"builder"} | MASTER_ROLES:
        abort(403)
    with connect_db() as db:
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            abort(404)
        if project["status"] in {"Completed","Closed","Cancelled"}:
            flash("این پروژه بسته شده است.", "error")
        else:
            already = db.execute("SELECT 1 FROM project_members WHERE project_id=? AND account_id=?", (project_id,g.account["id"])).fetchone()
            count = db.execute("SELECT COUNT(*) FROM project_members WHERE project_id=?", (project_id,)).fetchone()[0]
            if already:
                flash("از قبل عضو این پروژه هستید.", "info")
            elif count >= project["required_builders"]:
                db.execute("UPDATE projects SET status='Full' WHERE id=?", (project_id,))
                flash("ظرفیت پروژه تکمیل شده است.", "error")
            else:
                db.execute("INSERT INTO project_members(project_id,account_id) VALUES(?,?)", (project_id,g.account["id"]))
                count += 1
                db.execute("UPDATE projects SET status=? WHERE id=?", ("Full" if count >= project["required_builders"] else "In progress",project_id))
                flash("به پروژه پیوستید.", "success")
    log_activity(g.account,"project_joined",project["title"])
    return redirect(url_for("staff_dashboard", section="projects"))

@app.route("/projects/<int:project_id>/tasks/create", methods=["POST"])
@staff_required
def create_task(project_id):
    if g.account["role"] not in PROJECT_MANAGERS:
        abort(403)
    title = clean_text(request.form.get("title",""),160)
    description = clean_text(request.form.get("description",""),2000)
    assignee_raw = request.form.get("assigned_to","").strip()
    assignee_id = int(assignee_raw) if assignee_raw.isdigit() else None
    with connect_db() as db:
        project = db.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            abort(404)
        if assignee_id and not db.execute("SELECT id FROM project_members WHERE project_id=? AND account_id=?", (project_id,assignee_id)).fetchone():
            flash("مسئول تسک باید عضو همین پروژه باشد.", "error")
            return redirect(url_for("staff_dashboard", section="tasks"))
        if title:
            db.execute("INSERT INTO tasks(project_id,title,description,assigned_to,created_by) VALUES(?,?,?,?,?)",
                       (project_id,title,description,assignee_id,g.account["id"]))
            flash("تسک ساخته شد.", "success")
        else:
            flash("عنوان تسک الزامی است.", "error")
    return redirect(url_for("staff_dashboard", section="tasks"))

@app.route("/tasks/<int:task_id>/status", methods=["POST"])
@staff_required
def update_task_status(task_id):
    status = request.form.get("status","")
    if status not in {"todo","doing","done"}:
        abort(400)
    with connect_db() as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            abort(404)
        allowed = task["assigned_to"] == g.account["id"] or g.account["role"] in PROJECT_MANAGERS | MASTER_ROLES
        if not allowed:
            abort(403)
        db.execute("UPDATE tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status,task_id))
    log_activity(g.account,"task_status",f"#{task_id}: {status}")
    flash("وضعیت تسک به‌روزرسانی شد.", "success")
    return redirect(url_for("staff_dashboard", section="tasks"))

@app.route("/warnings/create", methods=["POST"])
@staff_required
def create_warning():
    if g.account["role"] not in WARNING_ROLES:
        abort(403)
    target = request.form.get("staff_username","").strip()
    reason = clean_text(request.form.get("reason",""),2000)
    evidence_url = request.form.get("evidence_url","").strip()
    evidence_data = ""
    upload = request.files.get("evidence_file")
    if upload and upload.filename:
        mime = upload.mimetype or ""
        raw = upload.read(8_000_001)
        if mime not in {"image/png","image/jpeg","image/webp","image/gif","video/mp4","video/webm"} or not raw or len(raw)>8_000_000:
            flash("مدرک باید تصویر یا ویدئوی MP4/WEBM و حداکثر ۸ مگابایت باشد.", "error")
            return redirect(url_for("staff_dashboard", section="warnings"))
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
                     "video/mp4": ".mp4", "video/webm": ".webm"}[mime]
        evidence_data = store_upload("warnings/" + secrets.token_hex(16) + extension, raw, mime)
    elif evidence_url and (not evidence_url.startswith("https://") or len(evidence_url)>1500):
        flash("لینک مدرک باید با HTTPS شروع شود.", "error")
        return redirect(url_for("staff_dashboard", section="warnings"))
    with connect_db() as db:
        target_account = db.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE AND role<>'player'",(target,)).fetchone()
        if not target_account:
            flash("کارمند موردنظر پیدا نشد.", "error")
        elif g.account["role"] == "hbuilder" and target_account["role"] != "builder":
            flash("H-Builder فقط می‌تواند برای Builder اخطار ثبت کند.", "error")
        elif not reason:
            flash("دلیل اخطار الزامی است.", "error")
        else:
            db.execute("INSERT INTO warnings(staff_username,reason,evidence_url,evidence_data,issued_by) VALUES(?,?,?,?,?)",
                       (target_account["username"],reason,evidence_url,evidence_data,g.account["username"]))
            db.execute("INSERT INTO notifications(recipient_type,recipient_id,title,body,target_url) VALUES('account',?,?,?,?)",
                       (target_account["id"],"اخطار جدید",reason[:500],url_for("account_profile")+"#warnings"))
            flash("اخطار ثبت شد.", "success")
    log_activity(g.account,"warning_created",target)
    return redirect(url_for("staff_dashboard", section="warnings"))

@app.route("/staff/promote-member", methods=["POST"])
@roles_required("developer","owner")
def promote_member():
    username = request.form.get("username","").strip()
    role = request.form.get("role","")
    if role not in STAFF_ROLES:
        flash("نقش انتخاب‌شده معتبر نیست.", "error")
        return redirect(url_for("staff_dashboard", section="staff-accounts"))
    with connect_db() as db:
        target = db.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if not target:
            flash("حساب بازیکن پیدا نشد.", "error")
        elif target["id"] == g.account["id"] and role != "owner":
            flash("نقش حساب خود را از این بخش تغییر ندهید.", "error")
        else:
            db.execute("UPDATE accounts SET role=? WHERE id=?", (role,target["id"]))
            group = db.execute("SELECT id FROM conversations WHERE kind='group' AND title='گروه کارکنان' LIMIT 1").fetchone()
            if group:
                db.execute("INSERT OR IGNORE INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (group["id"],target["id"]))
            db.execute("INSERT INTO notifications(recipient_type,recipient_id,title,body,target_url) VALUES('account',?,?,?,?)",
                       (target["id"],"دسترسی کارکنان فعال شد","نقش جدید شما: "+ROLE_LABELS[role],url_for("staff_dashboard")))
            flash(f"دسترسی {ROLE_LABELS[role]} برای {target['username']} فعال شد.", "success")
    return redirect(url_for("staff_dashboard", section="staff-accounts"))

@app.route("/staff/role/<int:account_id>", methods=["POST"])
@roles_required("developer","owner")
def change_staff_role(account_id):
    role = request.form.get("role","")
    if role not in STAFF_ROLES:
        abort(400)
    with connect_db() as db:
        target = db.execute("SELECT * FROM accounts WHERE id=? AND role<>'player'", (account_id,)).fetchone()
        if not target:
            abort(404)
        if target["role"] in MASTER_ROLES and g.account["role"] not in MASTER_ROLES:
            abort(403)
        db.execute("UPDATE accounts SET role=? WHERE id=?", (role,account_id))
    flash("نقش کارکنان به‌روزرسانی شد.", "success")
    return redirect(url_for("staff_dashboard", section="staff-accounts"))

@app.route("/site-uploads/<path:filename>")
def serve_site_upload(filename):
    if IS_CLOUDFLARE:
        raw = load_upload(filename)
        if raw is None:
            abort(404)
        import mimetypes
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return Response(raw, mimetype=mime, headers={"Cache-Control": "public, max-age=3600"})
    return send_from_directory(SITE_UPLOAD_DIR, filename)

@app.route("/site-settings/images", methods=["POST"])
@roles_required("developer","owner")
def update_site_images():
    # Uploads are stored locally so the homepage does not depend on third-party image hosts.
    upload_dir = SITE_UPLOAD_DIR
    if not IS_CLOUDFLARE:
        upload_dir.mkdir(parents=True, exist_ok=True)
    allowed = {
        "image/png": (".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
        "image/jpeg": (".jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
        "image/webp": (".webp", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
        "image/gif": (".gif", lambda b: b.startswith((b"GIF87a", b"GIF89a"))),
    }
    keys = list(IMAGE_DEFAULTS.keys())
    updates = {}
    for key in keys:
        upload = request.files.get(key)
        if not upload or not upload.filename:
            continue
        mime = (upload.mimetype or "").lower()
        if mime not in allowed:
            flash("فرمت تصویر مجاز نیست. PNG، JPG، WEBP یا GIF انتخاب کن.", "error")
            return redirect(url_for("staff_dashboard", section="site-settings"))
        raw = upload.read(5 * 1024 * 1024 + 1)
        if not raw or len(raw) > 5 * 1024 * 1024 or not allowed[mime][1](raw):
            flash("تصویر نامعتبر است یا حجم آن از ۵ مگابایت بیشتر است.", "error")
            return redirect(url_for("staff_dashboard", section="site-settings"))
        filename = key + "-" + secrets.token_hex(12) + allowed[mime][0]
        if IS_CLOUDFLARE:
            updates[key] = store_upload(filename, raw, mime)
        else:
            target = upload_dir / filename
            target.write_bytes(raw)
            updates[key] = "/site-uploads/" + filename
    if not updates:
        flash("حداقل یک تصویر برای بارگذاری انتخاب کن.", "error")
        return redirect(url_for("staff_dashboard", section="site-settings"))
    with connect_db() as db:
        for key, value in updates.items():
            db.execute("UPDATE site_settings SET setting_value=? WHERE setting_key=?", (value, key))
    flash("تصاویر جدید بارگذاری و ذخیره شدند.", "success")
    return redirect(url_for("staff_dashboard", section="site-settings"))
@app.route("/messages/private", methods=["POST"])
@staff_required
def start_private_message():
    recipient = request.form.get("recipient","").strip()
    body = clean_text(request.form.get("body",""),4000)
    if not recipient or not body:
        flash("گیرنده و متن پیام الزامی است.", "error")
        return redirect(url_for("staff_dashboard", section="messenger"))
    with connect_db() as db:
        target = db.execute("SELECT id,username FROM accounts WHERE username=? COLLATE NOCASE AND role<>'player'", (recipient,)).fetchone()
        if not target or target["id"] == g.account["id"]:
            flash("گیرنده معتبر نیست.", "error")
            return redirect(url_for("staff_dashboard", section="messenger"))
        convo = db.execute("""SELECT c.id FROM conversations c
            JOIN conversation_members a ON a.conversation_id=c.id AND a.account_id=?
            JOIN conversation_members b ON b.conversation_id=c.id AND b.account_id=?
            WHERE c.kind='private' LIMIT 1""", (g.account["id"],target["id"])).fetchone()
        if convo:
            convo_id = convo["id"]
        else:
            convo_id = db.execute("INSERT INTO conversations(kind,title,created_by) VALUES('private',?,?)",
                ("پیام خصوصی",g.account["id"])).lastrowid
            db.execute("INSERT INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (convo_id,g.account["id"]))
            db.execute("INSERT INTO conversation_members(conversation_id,account_id) VALUES(?,?)", (convo_id,target["id"]))
        db.execute("INSERT INTO messages(conversation_id,sender_id,body) VALUES(?,?,?)", (convo_id,g.account["id"],body))
    flash("پیام ارسال شد.", "success")
    return redirect(url_for("staff_dashboard", section="messenger"))

@app.route("/messages/<int:conversation_id>/send", methods=["POST"])
@staff_required
def send_message(conversation_id):
    body = clean_text(request.form.get("body",""),4000)
    with connect_db() as db:
        member = db.execute("SELECT 1 FROM conversation_members WHERE conversation_id=? AND account_id=?", (conversation_id,g.account["id"])).fetchone()
        if not member:
            abort(403)
        if not body:
            flash("متن پیام خالی است.", "error")
        else:
            db.execute("INSERT INTO messages(conversation_id,sender_id,body) VALUES(?,?,?)", (conversation_id,g.account["id"],body))
            flash("پیام ارسال شد.", "success")
    return redirect(url_for("staff_dashboard", section="messenger"))

@app.route("/api/minecraft-event", methods=["POST"])
def minecraft_event():
    expected = config_value("MINECRAFT_WEBHOOK_TOKEN", "")
    supplied = request.headers.get("X-MiladCraft-Token","")
    if not expected:
        return jsonify(error="integration_not_configured"),503
    if not supplied or not hmac.compare_digest(supplied,expected):
        abort(401)
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username","")).strip()[:32]
    event = str(payload.get("event","")).lower().strip()
    if not username or event not in {"join","quit","leave"}:
        abort(400)
    with connect_db() as db:
        account = db.execute("SELECT * FROM accounts WHERE username=? COLLATE NOCASE AND role<>'player'", (username,)).fetchone()
        if not account:
            return jsonify(status="ignored",reason="not_staff"),200
        presence = db.execute("SELECT * FROM staff_presence WHERE username=? COLLATE NOCASE", (account["username"],)).fetchone()
        if event == "join":
            db.execute("""INSERT INTO staff_presence(username,is_online,joined_at,last_seen,total_minutes)
                VALUES(?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)
                ON CONFLICT(username) DO UPDATE SET is_online=1,
                joined_at=CASE WHEN staff_presence.is_online=0 THEN CURRENT_TIMESTAMP ELSE staff_presence.joined_at END,
                last_seen=CURRENT_TIMESTAMP""", (account["username"],))
        else:
            if presence and presence["is_online"] and presence["joined_at"]:
                db.execute("""UPDATE staff_presence SET is_online=0,last_seen=CURRENT_TIMESTAMP,
                    total_minutes=total_minutes+MAX(0,CAST((julianday('now')-julianday(joined_at))*1440 AS INTEGER)),joined_at=NULL
                    WHERE username=? COLLATE NOCASE""", (account["username"],))
            else:
                db.execute("""INSERT INTO staff_presence(username,is_online,last_seen,total_minutes) VALUES(?,0,CURRENT_TIMESTAMP,0)
                    ON CONFLICT(username) DO UPDATE SET is_online=0,last_seen=CURRENT_TIMESTAMP,joined_at=NULL""", (account["username"],))
        db.execute("INSERT INTO staff_activity(account_id,username,event_type,details) VALUES(?,?,?,?)",
                   (account["id"],account["username"],"minecraft_"+("join" if event=="join" else "quit"),"Minecraft "+event))
    return jsonify(status="ok",username=account["username"],event=event)

@app.route("/news")
def news_page():
    with connect_db() as db:
        news_items = db.execute("SELECT * FROM news WHERE published=1 ORDER BY id DESC").fetchall()
    return render_template("news.html",news_items=news_items)

@app.route("/news/<int:news_id>")
def news_detail(news_id):
    with connect_db() as db:
        item = db.execute("SELECT * FROM news WHERE id=? AND published=1", (news_id,)).fetchone()
    if not item:
        abort(404)
    return render_template("news_detail.html",item=item)

@app.route("/news/editor", methods=["GET", "POST"])
@staff_required
def news_editor():
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    news_id = request.args.get("id", type=int)
    with connect_db() as db:
        item = db.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone() if news_id else None
        if news_id and not item:
            abort(404)
        if request.method == "POST":
            title = clean_text(request.form.get("title", ""), 180)
            summary = clean_text(request.form.get("summary", ""), 500)
            cover = request.form.get("cover_url", "").strip()
            content = bleach.clean(request.form.get("content", ""), tags=BLOG_TAGS, attributes=BLOG_ATTRS, protocols=BLOG_PROTOCOLS, strip=True)
            published = 1 if request.form.get("published") == "1" else 0
            if not title or not bleach.clean(content, tags=[], strip=True).strip():
                flash("عنوان و محتوای خبر الزامی است.", "error")
            elif cover and not cover.startswith("https://"):
                flash("آدرس کاور باید HTTPS باشد.", "error")
            elif item:
                db.execute("UPDATE news SET title=?,summary=?,content=?,cover_url=?,published=? WHERE id=?", (title, summary, content, cover, published, news_id))
                flash("خبر به‌روزرسانی شد.", "success")
                return redirect(url_for("staff_dashboard", section="news-management"))
            else:
                db.execute("INSERT INTO news(title,summary,content,cover_url,author,published) VALUES(?,?,?,?,?,?)", (title, summary, content, cover, g.account["username"], published))
                flash("خبر ذخیره شد.", "success")
                return redirect(url_for("staff_dashboard", section="news-management"))
    return render_template("editor.html", post=item, tags=[], selected_tag_ids=[], mode="news")

@app.route("/news/<int:news_id>/delete", methods=["POST"])
@staff_required
def delete_news(news_id):
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    with connect_db() as db:
        item = db.execute("SELECT id FROM news WHERE id=?", (news_id,)).fetchone()
        if not item:
            abort(404)
        db.execute("DELETE FROM news WHERE id=?", (news_id,))
    flash("خبر حذف شد.", "success")
    return redirect(url_for("staff_dashboard", section="news-management"))

@app.route("/news/create", methods=["POST"])
@staff_required
def create_news():
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    title = clean_text(request.form.get("title",""),180)
    summary = clean_text(request.form.get("summary",""),500)
    content = bleach.clean(request.form.get("content",""),tags=BLOG_TAGS,attributes=BLOG_ATTRS,protocols=BLOG_PROTOCOLS,strip=True)
    cover = request.form.get("cover_url","").strip()
    published = 1 if request.form.get("published") == "1" else 0
    if not title or not bleach.clean(content,tags=[],strip=True).strip():
        flash("عنوان و محتوای خبر الزامی است.", "error")
    elif cover and not cover.startswith("https://"):
        flash("لینک تصویر باید با HTTPS شروع شود.", "error")
    else:
        with connect_db() as db:
            db.execute("INSERT INTO news(title,summary,content,cover_url,author,published) VALUES(?,?,?,?,?,?)",
                       (title,summary,content,cover,g.account["username"],published))
        flash("خبر ذخیره شد.", "success")
    return redirect(url_for("staff_dashboard", section="news-management"))

@app.route("/academy")
def academy():
    query = request.args.get("q","").strip()[:100]
    tag_slug = request.args.get("tag","").strip()[:80]
    with connect_db() as db:
        tags = db.execute("SELECT * FROM academy_tags ORDER BY name COLLATE NOCASE").fetchall()
        sql = "SELECT DISTINCT p.* FROM posts p LEFT JOIN post_tags pt ON pt.post_id=p.id LEFT JOIN academy_tags t ON t.id=pt.tag_id WHERE p.published=1"
        args = []
        if query:
            sql += " AND (p.title LIKE ? OR p.summary LIKE ? OR p.content LIKE ? OR p.author LIKE ?)"
            args.extend([f"%{query}%"]*4)
        if tag_slug:
            sql += " AND t.slug=?"
            args.append(tag_slug)
        sql += " ORDER BY p.id DESC"
        posts = db.execute(sql,args).fetchall()
    return render_template("academy.html",posts=posts,tags=tags,query=query,tag_slug=tag_slug)

@app.route("/academy/<int:post_id>")
def blog_post(post_id):
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=? AND (published=1 OR ?)", (post_id, int(bool(g.account and g.account["role"] in CONTENT_ROLES)))).fetchone()
        if not post:
            abort(404)
        tags = db.execute("SELECT t.* FROM academy_tags t JOIN post_tags pt ON pt.tag_id=t.id WHERE pt.post_id=? ORDER BY t.name", (post_id,)).fetchall()
        comments = db.execute("SELECT c.*,a.username,a.display_name,a.avatar_url FROM post_comments c JOIN accounts a ON a.id=c.account_id WHERE c.post_id=? ORDER BY c.id DESC", (post_id,)).fetchall()
        feedback = db.execute("SELECT vote,COUNT(*) AS count FROM post_feedback WHERE post_id=? GROUP BY vote", (post_id,)).fetchall()
        my_vote = db.execute("SELECT vote FROM post_feedback WHERE post_id=? AND account_id=?", (post_id,g.account["id"])).fetchone() if g.account else None
    return render_template("post.html",post=post,tags=tags,comments=comments,feedback=feedback,my_vote=my_vote)

@app.route("/academy/<int:post_id>/feedback", methods=["POST"])
@account_required
def academy_feedback(post_id):
    try:
        vote = int(request.form.get("vote","0"))
    except ValueError:
        vote = 0
    if vote not in {-1,1}:
        abort(400)
    with connect_db() as db:
        if not db.execute("SELECT id FROM posts WHERE id=? AND published=1", (post_id,)).fetchone():
            abort(404)
        db.execute("""INSERT INTO post_feedback(post_id,account_id,vote) VALUES(?,?,?)
            ON CONFLICT(post_id,account_id) DO UPDATE SET vote=excluded.vote,created_at=CURRENT_TIMESTAMP""",
            (post_id,g.account["id"],vote))
    return redirect(url_for("blog_post",post_id=post_id)+"#article-feedback")

@app.route("/academy/<int:post_id>/comment", methods=["POST"])
@account_required
def academy_comment(post_id):
    body = clean_text(request.form.get("body",""),3000)
    if not body:
        flash("متن دیدگاه الزامی است.", "error")
    else:
        with connect_db() as db:
            if not db.execute("SELECT id FROM posts WHERE id=? AND published=1", (post_id,)).fetchone():
                abort(404)
            cur = db.execute("INSERT INTO post_comments(post_id,account_id,body) VALUES(?,?,?)", (post_id,g.account["id"],body))
            if g.account["role"] != "player":
                pass
            else:
                for manager in db.execute("SELECT id FROM accounts WHERE role IN ('owner','developer','admin','manager')").fetchall():
                    db.execute("INSERT INTO notifications(recipient_type,recipient_id,title,body,target_url) VALUES('account',?,?,?,?)",
                        (manager["id"],"دیدگاه جدید",body[:400],url_for("blog_post",post_id=post_id)+"#questions"))
            flash("دیدگاه ثبت شد.", "success")
    return redirect(url_for("blog_post",post_id=post_id)+"#questions")

@app.route("/academy/comments/<int:comment_id>/reply", methods=["POST"])
@staff_required
def reply_to_comment(comment_id):
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    reply = clean_text(request.form.get("reply_text",""),3000)
    if not reply:
        flash("متن پاسخ الزامی است.", "error")
    else:
        with connect_db() as db:
            comment = db.execute("SELECT * FROM post_comments WHERE id=?", (comment_id,)).fetchone()
            if not comment:
                abort(404)
            db.execute("UPDATE post_comments SET reply_text=?,replied_by=?,replied_at=CURRENT_TIMESTAMP WHERE id=?",
                       (reply,g.account["username"],comment_id))
            db.execute("INSERT INTO notifications(recipient_type,recipient_id,title,body,target_url) VALUES('account',?,?,?,?)",
                       (comment["account_id"],"پاسخ جدید به دیدگاه",reply[:500],url_for("blog_post",post_id=comment["post_id"])+"#questions"))
        flash("پاسخ ثبت شد.", "success")
    return redirect(url_for("staff_dashboard", section="academy-content"))

@app.route("/academy/tags/create", methods=["POST"])
@staff_required
def create_academy_tag():
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    name = clean_text(request.form.get("name",""),40)
    slug = "tag-"+hashlib.sha256(name.casefold().encode()).hexdigest()[:12]
    if not name:
        flash("نام برچسب الزامی است.", "error")
    else:
        try:
            with connect_db() as db:
                db.execute("INSERT INTO academy_tags(name,slug) VALUES(?,?)", (name,slug))
            flash("برچسب ساخته شد.", "success")
        except Exception as exc:
            if sqlite3 is not None and isinstance(exc, sqlite3.IntegrityError):
                flash("این برچسب از قبل وجود دارد.", "error")
            elif "UNIQUE constraint" in str(exc):
                flash("این برچسب از قبل وجود دارد.", "error")
            else:
                raise
    return redirect(url_for("staff_dashboard", section="academy-content"))

@app.route("/academy/editor", methods=["GET","POST"])
@staff_required
def blog_editor():
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    post_id = request.args.get("id",type=int)
    with connect_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone() if post_id else None
        tags = db.execute("SELECT * FROM academy_tags ORDER BY name").fetchall()
        selected_tag_ids = [r["tag_id"] for r in db.execute("SELECT tag_id FROM post_tags WHERE post_id=?", (post_id,)).fetchall()] if post_id else []
        if request.method == "POST":
            title = clean_text(request.form.get("title",""),180)
            summary = clean_text(request.form.get("summary",""),500)
            cover = request.form.get("cover_url","").strip()
            content = bleach.clean(request.form.get("content",""),tags=BLOG_TAGS,attributes=BLOG_ATTRS,protocols=BLOG_PROTOCOLS,strip=True)
            published = 1 if request.form.get("published") == "1" else 0
            try:
                selected_tag_ids = list({int(x) for x in request.form.getlist("tag_ids") if x.isdigit()})
            except ValueError:
                selected_tag_ids = []
            if not title or not bleach.clean(content,tags=[],strip=True).strip():
                flash("عنوان و محتوای مطلب الزامی است.", "error")
            elif cover and not cover.startswith("https://"):
                flash("آدرس کاور باید HTTPS باشد.", "error")
            elif post_id and post:
                db.execute("UPDATE posts SET title=?,summary=?,cover_url=?,content=?,published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (title,summary,cover,content,published,post_id))
                db.execute("DELETE FROM post_tags WHERE post_id=?", (post_id,))
                for tag_id in selected_tag_ids:
                    db.execute("INSERT OR IGNORE INTO post_tags(post_id,tag_id) SELECT ?,id FROM academy_tags WHERE id=?", (post_id,tag_id))
                flash("مطلب به‌روزرسانی شد.", "success")
                return redirect(url_for("staff_dashboard", section="academy-content"))
            else:
                new_id = db.execute("INSERT INTO posts(title,summary,content,cover_url,author,published) VALUES(?,?,?,?,?,?)",
                    (title,summary,content,cover,g.account["username"],published)).lastrowid
                for tag_id in selected_tag_ids:
                    db.execute("INSERT OR IGNORE INTO post_tags(post_id,tag_id) SELECT ?,id FROM academy_tags WHERE id=?", (new_id,tag_id))
                flash("مطلب ساخته شد.", "success")
                return redirect(url_for("staff_dashboard", section="academy-content"))
    return render_template("editor.html",post=post,tags=tags,selected_tag_ids=selected_tag_ids,mode="academy")

@app.route("/academy/<int:post_id>/delete", methods=["POST"])
@staff_required
def delete_post(post_id):
    if g.account["role"] not in CONTENT_ROLES:
        abort(403)
    with connect_db() as db:
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    flash("مطلب حذف شد.", "success")
    return redirect(url_for("staff_dashboard", section="academy-content"))

@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@account_required
def notification_read(notification_id):
    with connect_db() as db:
        item = db.execute("SELECT target_url FROM notifications WHERE id=? AND recipient_id=?", (notification_id,g.account["id"])).fetchone()
        if item:
            db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND recipient_id=?", (notification_id,g.account["id"]))
    return redirect(item["target_url"] if item else url_for("account_profile"))

@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="اجازه دسترسی به این بخش را ندارید."),403

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="صفحه موردنظر پیدا نشد."),404

@app.errorhandler(400)
def bad_request(error):
    message = getattr(error,"description","درخواست نامعتبر است.")
    return render_template("error.html",code=400,message=message),400

if not IS_CLOUDFLARE:
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","8080")),debug=False)
