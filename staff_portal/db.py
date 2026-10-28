"""Additive SQLite schema for the staff workspace; existing site data is preserved."""
import os
import sqlite3
from pathlib import Path


def connect_db():
    path = Path(os.environ.get("DB_PATH", str(Path(os.environ.get("DATA_DIR", "data")) / "miladcraft.db")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def ensure_schema():
    with connect_db() as db:
        # Migrate the original four-role CHECK constraint without dropping accounts.
        staff_info = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='staff'").fetchone()
        if staff_info and "'hbuilder','developer','owner'" in (staff_info["sql"] or "").replace(" ", ""):
            columns = {row["name"] for row in db.execute("PRAGMA table_info(staff)")}
            display = "display_name" if "display_name" in columns else "''"
            avatar = "avatar_url" if "avatar_url" in columns else "''"
            db.execute("ALTER TABLE staff RENAME TO staff_legacy_role_check")
            db.execute("""CREATE TABLE staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('builder','hbuilder','developer','owner','manager','admin','moderator','helper')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                display_name TEXT NOT NULL DEFAULT '', avatar_url TEXT NOT NULL DEFAULT '')""")
            db.execute(f"INSERT INTO staff(id,username,password_hash,role,created_at,display_name,avatar_url) SELECT id,username,password_hash,role,created_at,{display},{avatar} FROM staff_legacy_role_check")
            db.execute("DROP TABLE staff_legacy_role_check")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS staff_applications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, display_name TEXT NOT NULL,
          email TEXT NOT NULL DEFAULT '', age INTEGER, minecraft_username TEXT NOT NULL,
          telegram TEXT NOT NULL DEFAULT '', discord TEXT NOT NULL DEFAULT '',
          experience TEXT NOT NULL DEFAULT '', motivation TEXT NOT NULL DEFAULT '',
          daily_hours INTEGER, country TEXT NOT NULL DEFAULT '', requested_role TEXT NOT NULL DEFAULT 'builder',
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
          reviewer_id INTEGER, review_note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, reviewed_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_staff_applications_status ON staff_applications(status,created_at DESC);
        CREATE TABLE IF NOT EXISTS build_tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', assigned_to TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','review','done')),
          due_date TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_build_tasks_assignee ON build_tasks(assigned_to,status);
        CREATE TABLE IF NOT EXISTS project_members (
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          staff_id INTEGER NOT NULL, joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(project_id,staff_id));
        CREATE TABLE IF NOT EXISTS staff_activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER NOT NULL, username TEXT NOT NULL,
          event_type TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_staff_activity_user_time ON staff_activity(staff_id,occurred_at DESC);
        CREATE TABLE IF NOT EXISTS staff_presence (
          username TEXT PRIMARY KEY, is_online INTEGER NOT NULL DEFAULT 0,
          joined_at TEXT, last_seen TEXT, total_minutes INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS staff_conversations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('group','private')),
          title TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS staff_conversation_members (
          conversation_id INTEGER NOT NULL REFERENCES staff_conversations(id) ON DELETE CASCADE,
          staff_id INTEGER NOT NULL, PRIMARY KEY(conversation_id,staff_id));
        CREATE TABLE IF NOT EXISTS staff_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL REFERENCES staff_conversations(id) ON DELETE CASCADE,
          sender_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_staff_messages_conversation ON staff_messages(conversation_id,id DESC);
        """)
        group = db.execute("SELECT id FROM staff_conversations WHERE kind='group' AND title='همه کارکنان' LIMIT 1").fetchone()
        if group is None:
            group_id = db.execute("INSERT INTO staff_conversations(kind,title,created_by) VALUES('group','همه کارکنان',0)").lastrowid
        else:
            group_id = group["id"]
        for staff in db.execute("SELECT id FROM staff").fetchall():
            db.execute("INSERT OR IGNORE INTO staff_conversation_members(conversation_id,staff_id) VALUES(?,?)", (group_id, staff["id"]))
        # Preserve legacy single-builder claims when enabling multi-builder projects.
        db.execute("""INSERT OR IGNORE INTO project_members(project_id,staff_id)
            SELECT p.id,s.id FROM projects p JOIN staff s ON s.username=p.claimed_by
            WHERE p.claimed_by IS NOT NULL AND p.claimed_by<>''""")
