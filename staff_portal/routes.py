"""Role-aware staff portal routes."""
from functools import wraps
import base64
import secrets
import sqlite3
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from .db import connect_db, ensure_schema

portal = Blueprint("staff_portal", __name__, url_prefix="/workspace")
MASTER = {"owner", "developer"}
BUILD_MANAGERS = MASTER | {"hbuilder"}
ROLES = {"owner":"Owner","developer":"Developer","manager":"Manager","admin":"Admin","hbuilder":"H-Builder","moderator":"Moderator","helper":"Helper","builder":"Builder"}
REQUEST_ROLES = {"builder", "hbuilder", "helper", "moderator"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_id"):
            return redirect(url_for("login"))
        ensure_schema()
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if (session.get("role") or "").lower() not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


@portal.before_request
def setup():
    ensure_schema()


@portal.route("/")
@login_required
def home():
    username, role, staff_id = session["username"], session["role"].lower(), session["staff_id"]
    with connect_db() as db:
        projects = db.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 20").fetchall()
        tasks = db.execute("SELECT t.*,p.title AS project_title FROM build_tasks t JOIN projects p ON p.id=t.project_id WHERE t.assigned_to=? ORDER BY t.id DESC LIMIT 20", (username,)).fetchall()
        activity = db.execute("SELECT * FROM staff_activity WHERE staff_id=? ORDER BY id DESC LIMIT 20", (staff_id,)).fetchall()
        profile = db.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
        presence = db.execute("SELECT * FROM staff_presence WHERE username=?", (username,)).fetchone()
        warnings = db.execute("SELECT * FROM warnings WHERE staff_username=? ORDER BY id DESC LIMIT 20", (username,)).fetchall()
        staff = db.execute("SELECT id,username,role FROM staff ORDER BY username").fetchall()
        pending = db.execute("SELECT COUNT(*) FROM staff_applications WHERE status='pending'").fetchone()[0] if role in MASTER else 0
        raw_conversations = db.execute("SELECT c.* FROM staff_conversations c JOIN staff_conversation_members m ON m.conversation_id=c.id WHERE m.staff_id=? ORDER BY CASE WHEN c.kind='group' THEN 0 ELSE 1 END,c.id", (staff_id,)).fetchall()
        conversations = []
        for convo in raw_conversations:
            convo_messages = db.execute("SELECT m.*,s.username AS sender FROM staff_messages m LEFT JOIN staff s ON s.id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id DESC LIMIT 40", (convo["id"],)).fetchall()
            title = convo["title"]
            if convo["kind"] == "private":
                other = db.execute("""SELECT s.username FROM staff_conversation_members m
                    JOIN staff s ON s.id=m.staff_id WHERE m.conversation_id=? AND m.staff_id<>? LIMIT 1""",
                    (convo["id"], staff_id)).fetchone()
                if other:
                    title = "پیام خصوصی با " + other["username"]
            conversations.append({"id":convo["id"],"title":title,"kind":convo["kind"],"messages":list(reversed(convo_messages))})
        online_count = db.execute("SELECT COUNT(*) FROM staff_presence WHERE is_online=1").fetchone()[0]
    return render_template("workspace.html", page="home", role=role, role_label=ROLES.get(role,role.title()), projects=projects, tasks=tasks, activity=activity, warnings=warnings, staff=staff, profile=profile, presence=presence, pending=pending, conversations=conversations, online_count=online_count, status="pending")


@portal.route("/apply", methods=["GET","POST"])
def apply():
    ensure_schema()
    if request.method == "POST":
        data = {key:request.form.get(key,"").strip() for key in ("username","display_name","email","minecraft_username","telegram","discord","experience","motivation","country")}
        role = request.form.get("requested_role","builder").lower()
        try:
            age = int(request.form.get("age","0")); hours = int(request.form.get("daily_hours","0") or 0)
        except ValueError:
            flash("سن و ساعات فعالیت باید عدد باشند.","error"); return redirect(url_for("staff_portal.apply"))
        if role not in REQUEST_ROLES or len(data["username"]) < 3 or not data["display_name"] or not data["minecraft_username"] or not 13 <= age <= 99 or hours not in range(0,25):
            flash("اطلاعات واردشده معتبر نیست یا فیلدهای ضروری خالی هستند.","error"); return redirect(url_for("staff_portal.apply"))
        with connect_db() as db:
            if db.execute("SELECT 1 FROM staff WHERE username=? COLLATE NOCASE",(data["username"],)).fetchone() or db.execute("SELECT 1 FROM staff_applications WHERE username=? COLLATE NOCASE AND status='pending'",(data["username"],)).fetchone():
                flash("این نام کاربری قبلاً ثبت شده یا در انتظار بررسی است.","error"); return redirect(url_for("staff_portal.apply"))
            db.execute("""INSERT INTO staff_applications(username,display_name,email,age,minecraft_username,telegram,discord,experience,motivation,daily_hours,country,requested_role) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["username"],data["display_name"],data["email"],age,data["minecraft_username"],data["telegram"],data["discord"],data["experience"][:5000],data["motivation"][:5000],hours or None,data["country"][:100],role))
        flash("درخواست عضویت ثبت شد و پس از بررسی مدیریت نتیجه اعلام می‌شود.","success")
        return redirect(url_for("staff_portal.apply"))
    return render_template("workspace.html",page="apply",roles=ROLES,request_roles=REQUEST_ROLES)


@portal.route("/applications")
@role_required(*MASTER)
def applications():
    status=request.args.get("status","pending")
    if status not in {"pending","accepted","rejected","all"}: status="pending"
    sql="SELECT * FROM staff_applications"; args=()
    if status!="all": sql+=" WHERE status=?"; args=(status,)
    with connect_db() as db: applications=db.execute(sql+" ORDER BY created_at DESC",args).fetchall()
    return render_template("workspace.html",page="applications",applications=applications,status=status,role=session.get("role","").lower(),role_label=ROLES.get(session.get("role","").lower(),""))


@portal.route("/applications/<int:application_id>/review",methods=["POST"])
@role_required(*MASTER)
def review_application(application_id):
    decision=request.form.get("decision",""); note=request.form.get("review_note","").strip()[:2000]
    if decision not in {"accept","reject"}: abort(400)
    with connect_db() as db:
        app=db.execute("SELECT * FROM staff_applications WHERE id=?",(application_id,)).fetchone()
        if not app: abort(404)
        if app["status"]!="pending": flash("این درخواست قبلاً بررسی شده است.","error"); return redirect(url_for("staff_portal.applications"))
        if decision=="accept":
            initial_password = secrets.token_urlsafe(10)
            try:
                db.execute("INSERT INTO staff(username,password_hash,role,display_name) VALUES(?,?,?,?)",(app["username"],generate_password_hash(initial_password),app["requested_role"],app["display_name"]))
            except sqlite3.IntegrityError:
                flash("ساخت حساب انجام نشد؛ نام کاربری تکراری است یا مهاجرت نقش‌ها اجرا نشده است.","error"); return redirect(url_for("staff_portal.applications"))
            new_id=db.execute("SELECT id FROM staff WHERE username=?",(app["username"],)).fetchone()["id"]
            group=db.execute("SELECT id FROM staff_conversations WHERE kind='group' AND title='همه کارکنان' LIMIT 1").fetchone()
            if group: db.execute("INSERT OR IGNORE INTO staff_conversation_members(conversation_id,staff_id) VALUES(?,?)",(group["id"],new_id))
            db.execute("UPDATE staff_applications SET status='accepted',reviewer_id=?,review_note=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(session["staff_id"],note,application_id))
            db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",(new_id,app["username"],"staff_approved","درخواست عضویت تأیید شد"))
            flash(f"درخواست تأیید شد. رمز اولیه را به‌صورت امن به کاربر تحویل بده: {initial_password}","success")
        else:
            db.execute("UPDATE staff_applications SET status='rejected',reviewer_id=?,review_note=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(session["staff_id"],note,application_id))
            flash("درخواست رد شد.","success")
    return redirect(url_for("staff_portal.applications"))


@portal.route("/projects")
@login_required
def projects():
    with connect_db() as db:
        projects=db.execute("SELECT p.*,COUNT(t.id) task_count,SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) completed_tasks FROM projects p LEFT JOIN build_tasks t ON t.project_id=p.id GROUP BY p.id ORDER BY p.id DESC").fetchall()
        staff=db.execute("SELECT username,role FROM staff ORDER BY username").fetchall()
    return render_template("workspace.html",page="projects",projects=projects,staff=staff,role=session.get("role","").lower(),role_label=ROLES.get(session.get("role","").lower(),""))


@portal.route("/projects/<int:project_id>/tasks/create",methods=["POST"])
@role_required(*BUILD_MANAGERS)
def create_task(project_id):
    title=request.form.get("title","").strip(); description=request.form.get("description","").strip(); assignee=request.form.get("assigned_to","").strip(); due=request.form.get("due_date","").strip() or None
    if not title: flash("عنوان تسک الزامی است.","error"); return redirect(url_for("staff_portal.projects"))
    with connect_db() as db:
        if not db.execute("SELECT id FROM projects WHERE id=?",(project_id,)).fetchone(): abort(404)
        if assignee and not db.execute("SELECT id FROM staff WHERE username=?",(assignee,)).fetchone(): abort(400)
        db.execute("INSERT INTO build_tasks(project_id,title,description,assigned_to,due_date,created_by) VALUES(?,?,?,?,?,?)",(project_id,title,description[:5000],assignee,due,session["username"]))
        if assignee:
            target=db.execute("SELECT id FROM staff WHERE username=?",(assignee,)).fetchone()
            db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",(target["id"],assignee,"task_assigned",title))
    flash("تسک ساخته شد.","success"); return redirect(url_for("staff_portal.projects"))


@portal.route("/tasks/<int:task_id>/status",methods=["POST"])
@login_required
def update_task(task_id):
    status=request.form.get("status","")
    if status not in {"todo","in_progress","review","done"}: abort(400)
    with connect_db() as db:
        task=db.execute("SELECT * FROM build_tasks WHERE id=?",(task_id,)).fetchone()
        if not task: abort(404)
        if task["assigned_to"]!=session.get("username") and session.get("role","").lower() not in BUILD_MANAGERS: abort(403)
        db.execute("UPDATE build_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,task_id))
        db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",(session["staff_id"],session["username"],"task_status",f"{task['title']}: {status}"))
    flash("وضعیت تسک به‌روزرسانی شد.","success"); return redirect(url_for("staff_portal.home"))


@portal.route("/messages/private", methods=["POST"])
@login_required
def start_private_message():
    recipient = request.form.get("recipient", "").strip()
    body = request.form.get("body", "").strip()
    if not recipient or recipient == session.get("username") or not body or len(body) > 4000:
        flash("گیرنده و پیام معتبر وارد کنید.", "error")
        return redirect(url_for("staff_portal.home") + "#messenger")
    with connect_db() as db:
        target = db.execute("SELECT id,username FROM staff WHERE username=? COLLATE NOCASE", (recipient,)).fetchone()
        if not target:
            flash("کارمند موردنظر پیدا نشد.", "error")
            return redirect(url_for("staff_portal.home") + "#messenger")
        existing = db.execute("""SELECT c.id FROM staff_conversations c
            JOIN staff_conversation_members a ON a.conversation_id=c.id AND a.staff_id=?
            JOIN staff_conversation_members b ON b.conversation_id=c.id AND b.staff_id=?
            WHERE c.kind='private' LIMIT 1""", (session["staff_id"], target["id"])).fetchone()
        if existing:
            conversation_id = existing["id"]
        else:
            conversation_id = db.execute("INSERT INTO staff_conversations(kind,title,created_by) VALUES('private',?,?)",
                ("پیام خصوصی با " + target["username"], session["staff_id"])).lastrowid
            db.execute("INSERT INTO staff_conversation_members(conversation_id,staff_id) VALUES(?,?)", (conversation_id, session["staff_id"]))
            db.execute("INSERT INTO staff_conversation_members(conversation_id,staff_id) VALUES(?,?)", (conversation_id, target["id"]))
        db.execute("INSERT INTO staff_messages(conversation_id,sender_id,body) VALUES(?,?,?)",
            (conversation_id, session["staff_id"], body))
        db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",
            (target["id"], target["username"], "private_message", "پیام خصوصی جدید"))
    return redirect(url_for("staff_portal.home") + "#messenger")


@portal.route("/messages/send",methods=["POST"])
@login_required
def send_message():
    body=request.form.get("body","").strip(); conversation_id=request.form.get("conversation_id",type=int)
    if not body or len(body)>4000 or not conversation_id: abort(400)
    with connect_db() as db:
        if not db.execute("SELECT 1 FROM staff_conversation_members WHERE conversation_id=? AND staff_id=?",(conversation_id,session["staff_id"])).fetchone(): abort(403)
        db.execute("INSERT INTO staff_messages(conversation_id,sender_id,body) VALUES(?,?,?)",(conversation_id,session["staff_id"],body))
    return redirect(url_for("staff_portal.home")+"#messenger")


@portal.route("/api/minecraft-event", methods=["POST"])
def minecraft_event():
    import hmac
    import os
    expected = os.environ.get("MINECRAFT_WEBHOOK_TOKEN", "")
    supplied = request.headers.get("X-MiladCraft-Token", "")
    if not expected:
        return {"error": "integration_not_configured"}, 503
    if not supplied or not hmac.compare_digest(supplied, expected):
        abort(401)
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()[:32]
    event = str(payload.get("event", "")).strip().lower()
    if not username or event not in {"join", "quit", "leave"}:
        abort(400)
    with connect_db() as db:
        member = db.execute("SELECT id,username FROM staff WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if not member:
            return {"status": "ignored", "reason": "not_staff"}, 200
        row = db.execute("SELECT * FROM staff_presence WHERE username=?", (member["username"],)).fetchone()
        if event == "join":
            db.execute("""INSERT INTO staff_presence(username,is_online,joined_at,last_seen,total_minutes)
                VALUES(?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)
                ON CONFLICT(username) DO UPDATE SET
                is_online=1, joined_at=CASE WHEN staff_presence.is_online=0 THEN CURRENT_TIMESTAMP ELSE staff_presence.joined_at END,
                last_seen=CURRENT_TIMESTAMP""", (member["username"],))
            event_type, details = "minecraft_join", "ورود به سرور Minecraft"
        else:
            if row and row["is_online"] and row["joined_at"]:
                db.execute("""UPDATE staff_presence SET is_online=0,last_seen=CURRENT_TIMESTAMP,
                    total_minutes=total_minutes+MAX(0,CAST((julianday('now')-julianday(joined_at))*1440 AS INTEGER)),
                    joined_at=NULL WHERE username=?""", (member["username"],))
            else:
                db.execute("""INSERT INTO staff_presence(username,is_online,last_seen,total_minutes) VALUES(?,0,CURRENT_TIMESTAMP,0)
                    ON CONFLICT(username) DO UPDATE SET is_online=0,last_seen=CURRENT_TIMESTAMP,joined_at=NULL""", (member["username"],))
            event_type, details = "minecraft_quit", "خروج از سرور Minecraft"
        db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",
            (member["id"], member["username"], event_type, details))
    return {"status": "ok", "username": member["username"], "event": event}, 200


@portal.route("/warnings/create",methods=["POST"])
@role_required(*BUILD_MANAGERS)
def create_warning():
    target=request.form.get("staff_username","").strip(); reason=request.form.get("reason","").strip(); evidence=request.form.get("evidence_url","").strip()
    uploaded=request.files.get("evidence_file")
    if uploaded and uploaded.filename:
        mime=uploaded.mimetype or ""
        raw=uploaded.read(8_000_001)
        allowed={"image/png","image/jpeg","image/webp","image/gif","video/mp4","video/webm"}
        if mime not in allowed or not raw or len(raw)>8_000_000:
            flash("مدرک باید PNG/JPG/WEBP/GIF یا MP4/WEBM و حداکثر ۸ مگابایت باشد.","error")
            return redirect(url_for("staff_portal.home")+"#warnings")
        evidence="data:"+mime+";base64,"+base64.b64encode(raw).decode("ascii")
    elif evidence and (not evidence.startswith(("https://","http://")) or len(evidence)>1500):
        flash("لینک مدرک باید با HTTP یا HTTPS شروع شود.","error")
        return redirect(url_for("staff_portal.home")+"#warnings")
    role=session.get("role","").lower()
    with connect_db() as db:
        target_row=db.execute("SELECT id,role FROM staff WHERE username=?",(target,)).fetchone()
        if not target_row or not reason: flash("کارمند و دلیل وارن الزامی هستند.","error"); return redirect(url_for("staff_portal.home")+"#warnings")
        if role=="hbuilder" and target_row["role"]!="builder": abort(403)
        db.execute("INSERT INTO warnings(staff_username,reason,evidence_url,issued_by) VALUES(?,?,?,?)",(target,reason[:3000],evidence[:1500],session["username"]))
        db.execute("INSERT INTO staff_activity(staff_id,username,event_type,details) VALUES(?,?,?,?)",(target_row["id"],target,"warning_received",reason[:500]))
    flash("وارن ثبت شد.","success"); return redirect(url_for("staff_portal.home")+"#warnings")
