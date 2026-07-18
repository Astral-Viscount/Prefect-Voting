from flask import Flask, render_template, session, redirect, request, jsonify, g, abort, flash
import sqlite3
import os
from dotenv import load_dotenv
from google.oauth2 import id_token
from google.auth.transport import requests
from functools import wraps
import json
import secrets as secrets_lib
from pathlib import Path
from datetime import datetime
from werkzeug.utils import secure_filename

# replaces any old env variable with the new one
load_dotenv(override=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "SECRET_KEY is missing"
        "Please generate a new one by running the secret_token.py file from /utils folder and add it to .env"
    )

# XSS defense
app.config["SESSION_COOKIE_HTTPONLY"] = True 
# CSRF defense
app.config["SESSION_COOKIE_SAMESITE"] = "Lax" 
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 8

""" Initial approach
ADMIN_EMAILS = set()

for e in os.getenv("ADMIN_EMAILS", "").split(","):
    if e.strip():
        e = e.strip().lower()
    ADMIN_EMAILS.add(e)
"""

# More efficient as it uses a set comprehension
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

SCHOOL_DOMAIN = os.getenv("SCHOOL_DOMAIN", "@burnside.school.nz").lower()
# print(f"debug: school domain = {SCHOOL_DOMAIN!r}")

DATABASE = "voting.db"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# Candidate info
UPLOAD_FOLDER = os.path.join("static", "uploads", "candidates")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
ALLOWED_AUDIO_EXT = {"webm", "mp3", "wav", "ogg"}
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024 # 32 MB


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()

def verify_google_token(token):

    try:
        id_info = id_token.verify_oauth2_token(
        token,
        requests.Request(),
        GOOGLE_CLIENT_ID
        )
    except Exception:
        return None

    email = id_info["email"].lower()

    is_school_account = email.endswith(SCHOOL_DOMAIN)
    is_allowlisted_admin = email in ADMIN_EMAILS

    if not (is_school_account or is_allowlisted_admin):
        return None

    return {
        "google_id": id_info["sub"],
        "email": email,
        "name": id_info["name"],
        "should_be_admin": is_allowlisted_admin
    }

# Helper functions

# Flask's 'g' object to cache the user for the rest of the session
def get_current_user():
    if "user_id" not in session:
        return None

    if not hasattr(g, "current_user"):
        g.current_user = query_db("SELECT * FROM Users Where id=?", (session["user_id"],), one=True)

    return g.current_user

def is_candidate(user_id):
    row = query_db("SELECT id FROM Candidates WHERE user_id=?", (user_id,), one=True)
    
    return row is not None

def get_active_election():
    return query_db("SELECT * FROM Election WHERE is_active=1", one=True)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect("/login")

        return view(*args, **kwargs)

    return wrapped

def candidate_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")

        user = get_current_user()
        if user is None:
            session.clear()
            return redirect("/login")

        if not is_candidate(user["id"]):
            return render_template("403.html"), 403

        return view(*args, **kwargs)

    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")

        user = get_current_user()
        if user is None:
            session.clear()
            return redirect("/login")

        if not user["is_admin"]:
            return render_template("403.html"), 403

        return view(*args, **kwargs)

    return wrapped

def parse_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)

    except ValueError:
        return datetime.fromisoformat(value + ":00")

def format_datetime(value):
    date_time = parse_date(value)

    if not date_time:
        return "Not set"

    return date_time.strftime("%d %b %Y, %I:%M %p")

@app.template_filter("datetime")
def datetime_filter(value):
    return format_datetime(value)

def update_expired_elections():
    now = datetime.now()

    elections = query_db("SELECT id, end_date FROM Election WHERE is_active=1")

    for election in elections:
        end = parse_date(election["end_date"])

        if end and now > end:
            execute_db("UPDATE Election SET is_active=0 WHERE id=?", (election["id"],))

@app.before_request
def csrf_protect():
    if request.method == "POST":
        if request.path == "/login":
            return

        token = session.get("csrf_token")
        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        
        if not token or not sent_token or not secrets_lib.compare_digest(token, sent_token):
            abort(403)

@app.before_request
def check_expired_elections():
    update_expired_elections()

def user_voted_in_election(user_id, election_id):
    row = query_db("""
        SELECT Votes.id
        FROM Votes
        JOIN Positions ON Votes.position_id = Positions.id
        WHERE Votes.voter_id = ? AND Positions.election_id = ?
        LIMIT 1
    """, (user_id, election_id), one=True)

    return row is not None

def log_admin_action(action, details="", admin_id="__unset__"):
    if admin_id == "__unset__":
        admin = get_current_user()
    
        if admin:
            admin_id = admin["id"]
        else:
            admin_id = None

    execute_db("INSERT INTO AuditLog (admin_id, action, details) VALUES (?, ?, ?)", (admin_id, action, details))

@app.route("/")
def home():
    return render_template("index.html", user=session.get("user_name"))

@app.route("/login")
def login_page():
    return render_template("login.html", client_id=GOOGLE_CLIENT_ID )

@app.route("/login", methods=["POST"])
def login_data():

    token = request.json.get("credential")

    user_data = verify_google_token(token)

    if not user_data:
        return jsonify({"error": "Unauthorized domain"}), 403

    user = query_db("SELECT * FROM Users WHERE google_id=?", (user_data["google_id"],), one=True)

    if not user:
        if user_data["should_be_admin"]:
            is_admin_val = 1
        else:
            is_admin_val = 0

        try:
            execute_db("""INSERT INTO Users (google_id, email, name, is_admin) VALUES (?, ?, ?, ?)""", 
                        (user_data["google_id"], user_data["email"], user_data["name"], is_admin_val))

        except sqlite3.IntegrityError:
            pass 

        user = query_db("SELECT * FROM Users WHERE google_id=?", (user_data["google_id"],), one=True)

    else:
        if user_data["should_be_admin"] and not user["is_admin"]:
            execute_db("UPDATE Users SET is_admin=1 WHERE id=?", (user["id"],))

        if user["name"] != user_data["name"]:
            execute_db("UPDATE Users SET name=? WHERE id=?", (user_data["name"], user["id"]))

        user = query_db("SELECT * FROM Users WHERE id=?", (user["id"],), one=True)

    session.clear()
    session.permanent = True
    session["user_email"] = user["email"]
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["is_admin"] = bool(user["is_admin"])

    return jsonify({"success": True})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    
    if user["is_admin"]:
        return redirect("/admin")
    if is_candidate(user["id"]):
        return redirect("/candidate")
    
    return redirect("/voter")

@app.route("/voter")
@login_required
def voter_dashboard():
    user = get_current_user()
    election = get_active_election()
    is_open, message = voting_is_open(election)

    positions = []

    if election:
        raw_positions = query_db("SELECT * FROM Positions WHERE election_id=?", (election["id"],))

        for raw_position in raw_positions:
            candidates = query_db("""
                SELECT Candidates.id AS candidate_id, Candidates.bio, Candidates.photo,
                    Users.name AS candidate_name
                FROM Candidates
                JOIN Users ON Candidates.user_id = Users.id
                WHERE Candidates.position_id = ?
            """, (raw_position["id"],))

            candidates_list = []

            for candidate in candidates:

                if candidate["photo"]:
                    media = json.loads(candidate["photo"])
                else:
                    media = {}
                    
                candidates_list.append({
                        "id": candidate["candidate_id"],
                        "name": candidate["candidate_name"],
                        "bio": candidate["bio"],
                        "media": media,
                })
            
            already_voted = query_db(
                "SELECT id FROM Votes WHERE voter_id=? AND position_id=?",
                (user["id"], raw_position["id"]), one=True
            )

            positions.append({
                "position": dict(raw_position),
                "candidates": candidates_list,
                "has_voted": already_voted is not None,
            })

    return render_template("voter_dashboard.html", user=user, election=election, positions=positions, voting_open=is_open, voting_message=message)

@app.route("/vote/<int:position_id>/<int:candidate_id>", methods=["POST"])
@login_required
def cast_vote(position_id, candidate_id):
    user = get_current_user()
    election = get_active_election()
    is_open, message = voting_is_open(election)

    if not is_open:
        return jsonify({"error": message}), 403

    position = query_db("SELECT * FROM Positions WHERE id=?", (position_id,), one=True)

    if not position or position["election_id"] != election["id"]:
        return jsonify({"error": "Invalid position for the current election."}), 400

    candidate = query_db(
        "SELECT * FROM Candidates WHERE id=? AND position_id=?",
        (candidate_id, position_id), one=True
    )

    if not candidate:
        return jsonify({"error": "Invalid candidate for this position."}), 400

    try:
        execute_db(
            "INSERT INTO Votes (voter_id, position_id, candidate_id) VALUES (?, ?, ?)",
            (user["id"], position_id, candidate_id)
        )
        
    except sqlite3.IntegrityError:
        return jsonify({"error": "You have already voted for this position."}), 409

    return jsonify({"success": True})

@app.route("/candidate")
@candidate_required
def candidate_dashboard():
    user = get_current_user()

    candidate_row = query_db("""
        SELECT Candidates.*, Positions.position_name, Positions.election_id
        FROM Candidates
        JOIN Positions ON Candidates.position_id = Positions.id
        WHERE Candidates.user_id = ?
    """, (user["id"],), one=True)

    candidate_election = None

    if candidate_row:
        candidate_election = query_db("SELECT * FROM Election WHERE id=?", (candidate_row["election_id"],), one=True)

    vote_count = None

    if candidate_row and candidate_election and not candidate_election["is_active"]:
        row = query_db("SELECT COUNT(*) AS c FROM Votes WHERE candidate_id=?", (candidate_row["id"],), one=True)

        vote_count = row["c"]

    if candidate_row and candidate_row["photo"]:
        media = json.loads(candidate_row["photo"])
    else:
        media = {}

    return render_template("candidate_dashboard.html", user=user, candidate=candidate_row, media=media, vote_count=vote_count)

@app.route("/candidate/profile", methods=["GET", "POST"])
@candidate_required
def candidate_profile():
    user = get_current_user()
    candidate_row = query_db("SELECT * FROM Candidates WHERE user_id=?", (user["id"],), one=True)

    if candidate_row["photo"]:
        media = json.loads(candidate_row["photo"])
    else:
        media = {}

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()[:2000]
        video_url = request.form.get("video_url", "").strip()[:500]

        if video_url:
            media["video_url"] = video_url

        photo_file = request.files.get("photo_file")

        if photo_file and photo_file.filename:
            ext = Path(photo_file.filename).suffix.lower().lstrip('.')

            if ext in ALLOWED_IMAGE_EXT:
                filename = secure_filename(f"candidate_{candidate_row['id']}_photo.{ext}")
                full_path = Path(UPLOAD_FOLDER).resolve() / filename

                if not str(full_path).startswith(str(Path(UPLOAD_FOLDER).resolve())):
                    abort(400)

                photo_file.save(full_path)

                media["photo"] = f"/static/uploads/candidates/{filename}"
            else:
                flash("Photo must be PNG, JPG or WEBP.", "error")

        voice_file = request.files.get("voice_file")

        if voice_file and voice_file.filename:
            ext = voice_file.filename.rsplit(".", 1)[-1].lower()

            if ext in ALLOWED_AUDIO_EXT:
                filename = secure_filename(f"candidate_{candidate_row['id']}_voice.{ext}")
                voice_file.save(os.path.join(UPLOAD_FOLDER, filename))

                media["voice"] = f"/static/uploads/candidates/{filename}"
            else:
                flash("Voice clip must be webm, mp3, wav or ogg.", "error")

        execute_db("UPDATE Candidates SET bio=?, photo=? WHERE id=? AND user_id=?",
                   (bio, json.dumps(media), candidate_row["id"], user["id"]))

        flash("Profile updated.", "success")

        return redirect("/candidate")

    return render_template("candidate_profile.html", candidate=candidate_row, media=media)

@app.route("/admin")
@admin_required
def admin_dashboard():
    election = get_active_election() or query_db("SELECT * FROM Election ORDER BY id DESC", one=True)

    stats = {
        "positions": 0, 
        "candidates": 0, 
        "votes": 0
    }

    if election:
        stats["positions"] = query_db("SELECT COUNT(*) AS c FROM Positions WHERE election_id=?", (election["id"],), one=True)["c"]
        
        stats["candidates"] = query_db("""
            SELECT COUNT(*) AS c FROM Candidates
            JOIN Positions ON Candidates.position_id = Positions.id
            WHERE Positions.election_id=?
        """, (election["id"],), one=True)["c"]

        stats["votes"] = query_db("""
            SELECT COUNT(*) AS c FROM Votes
            JOIN Positions ON Votes.position_id = Positions.id
            WHERE Positions.election_id=?
        """, (election["id"],), one=True)["c"]

    return render_template("admin_dashboard.html", election=election, stats=stats)

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets_lib.token_hex(32)
        
    return dict(csrf_token=session["csrf_token"])

@app.context_processor
def inject_announcements():
    active = query_db("SELECT * FROM Announcements WHERE is_active=1 ORDER BY id DESC")

    return dict(site_announcements=active)

def voting_is_open(election):
    if not election or not election["is_active"]:
        return False, "No current election running"

    now = datetime.now()
    start = parse_date(election["start_date"])
    end = parse_date(election["end_date"])

    if start and now < start:
        return False, f"Voting starts {start.strftime('%d %b %Y, %I:%M %p')}"
    
    if end and now > end:
        return False, "Voting has stopped for this election"
    
    return True, None

@app.route("/admin/elections", methods=["GET", "POST"])
@admin_required
def admin_elections():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            execute_db("""
                INSERT INTO Election (title, description, start_date, end_date, is_active)
                VALUES (?, ?, ?, ?, 0)
            """, (
                request.form.get("title", "").strip(),
                request.form.get("description", "").strip(),
                request.form.get("start_date") or None,
                request.form.get("end_date") or None,
            ))

            flash("Election created.", "success")

        elif action == "toggle_active":
            election_id = request.form.get("election_id")
            election = query_db("SELECT * FROM Election WHERE id=?", (election_id,), one=True)

            if not election:
                flash("Election not found.", "error")
            else:
                end = parse_date(election["end_date"])

                if end and datetime.now() > end:
                    flash("Can't activate this election — its end time has already passed. Please Create a new one.", "error")
                else:
                    execute_db("UPDATE Election SET is_active = 0")
                    execute_db("UPDATE Election SET is_active = 1 WHERE id = ?", (election_id,))
                    flash("Election activated. All other elections were deactivated.", "success")

            return redirect("/admin/elections")

        elif action == "deactivate":
            election_id = request.form.get("election_id")

            execute_db("UPDATE Election SET is_active = 0 WHERE id = ?", (election_id,))

            flash("Election closed.", "info")

        elif action == "update_dates":
            execute_db("""
                UPDATE Election SET title=?, description=?, start_date=?, end_date=?
                WHERE id=?
            """, (
                request.form.get("title", "").strip(),
                request.form.get("description", "").strip(),
                request.form.get("start_date") or None,
                request.form.get("end_date") or None,
                request.form.get("election_id"),
            ))

            flash("Election updated.", "success")

        return redirect("/admin/elections")

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    return render_template("admin_elections.html", elections=elections)

@app.route("/admin/positions", methods=["GET", "POST"])
@admin_required
def admin_positions():
    election_id = request.values.get("election_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":

            execute_db(
                "INSERT INTO Positions (election_id, position_name, max_votes) VALUES (?, ?, ?)",
                (request.form.get("election_id"), request.form.get("position_name", "").strip(),
                 request.form.get("max_votes", 1))
            )

            flash("Position added.", "success")

        elif action == "delete":
            execute_db("DELETE FROM Positions WHERE id=?", (request.form.get("position_id"),))

            flash("Position removed.", "info")

        return redirect(f"/admin/positions?election_id={election_id}")

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    if election_id:
        positions = query_db("SELECT * FROM Positions WHERE election_id=?",(election_id,))
    else:
        positions = []

    return render_template("admin_positions.html", elections=elections, positions=positions, election_id=election_id)

@app.route("/admin/candidates", methods=["GET", "POST"])
@admin_required
def admin_candidates():
    election_id = request.values.get("election_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "assign":
            email = request.form.get("student_email", "").strip().lower()
            student = query_db("SELECT * FROM Users WHERE email=?", (email,), one=True)

            if not student:
                flash("That email hasn't logged into the site yet. Ask them to sign in once first.", "error")
            else:
                existing = query_db(
                    "SELECT id FROM Candidates WHERE user_id=? AND position_id=?",
                    (student["id"], request.form.get("position_id")), one=True
                )

                if existing:
                    flash("That student is already a candidate for this position.", "error")
                else:
                    execute_db(
                        "INSERT INTO Candidates (position_id, user_id, bio, photo) VALUES (?, ?, '', '{}')",
                        (request.form.get("position_id"), student["id"])
                    )
                    
                    flash(f"{student['name']} added as a candidate.", "success")

        elif action == "remove":
            execute_db("DELETE FROM Candidates WHERE id=?", (request.form.get("candidate_id"),))

            flash("Candidate removed.", "info")

        return redirect(f"/admin/candidates?election_id={election_id}")

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    if election_id:
        positions = query_db("SELECT * FROM Positions WHERE election_id=?", (election_id,))
    else:
        positions = []

    candidates = []

    if election_id:
        candidates = query_db("""
            SELECT Candidates.id, Candidates.bio, Positions.position_name, Users.name, Users.email
            FROM Candidates
            JOIN Positions ON Candidates.position_id = Positions.id
            JOIN Users ON Candidates.user_id = Users.id
            WHERE Positions.election_id = ?
        """, (election_id,))

    return render_template("admin_candidates.html", elections=elections, positions=positions, candidates=candidates, election_id=election_id)

@app.route("/admin/api/results/<int:position_id>")
@admin_required
def api_results(position_id):
    position = query_db(
        "SELECT * FROM Positions WHERE id=?",
        (position_id,),
        one=True
    )

    if not position:
        return jsonify({"error": "not found"}), 404

    rows = query_db("""
        SELECT Users.name AS name, COUNT(Votes.id) AS votes
        FROM Candidates
        JOIN Users ON Candidates.user_id = Users.id
        LEFT JOIN Votes ON Votes.candidate_id = Candidates.id
        WHERE Candidates.position_id = ?
        GROUP BY Candidates.id
        ORDER BY votes DESC, Users.name ASC
    """, (position_id,))

    candidates = []

    for r in rows:
        candidate_data = {
            "name": r["name"], 
            "votes": int(r["votes"])
        }
        candidates.append(candidate_data)

    total_votes = 0
    for c in candidates:
        total_votes += c["votes"]

    return jsonify({
        "position_name": position["position_name"],
        "candidates": candidates,
        "total_votes": total_votes
    })

@app.route("/admin/api/turnout")
@admin_required
def api_turnout():
    election = get_active_election()

    if not election:
        return jsonify({"voted": 0, "eligible": 0})

    eligible = query_db("SELECT COUNT(*) AS c FROM Users WHERE is_admin = 0", one=True)["c"]

    voted = query_db("""
        SELECT COUNT(DISTINCT Votes.voter_id) AS c
        FROM Votes JOIN Positions ON Votes.position_id = Positions.id
        WHERE Positions.election_id = ?
    """, (election["id"],), one=True)["c"]

    return jsonify({"voted": voted, "eligible": eligible})

@app.route("/admin/results")
@admin_required
def admin_results():
    election = get_active_election() or query_db("SELECT * FROM Election ORDER BY id DESC", one=True)

    if election:
        positions = query_db("SELECT * FROM Positions WHERE election_id=?", (election["id"],))
    else:
        positions = []
        
    return render_template("admin_results.html", election=election, positions=positions)

@app.route("/voter/results")
@login_required
def voter_results_list():
    user = get_current_user()

    elections = query_db("""
        SELECT DISTINCT Election.*
        FROM Votes
        JOIN Positions ON Votes.position_id = Positions.id
        JOIN Election ON Positions.election_id = Election.id
        WHERE Votes.voter_id = ? AND Election.is_active = 0
        ORDER BY Election.id DESC
    """, (user["id"],))

    return render_template("voter_results_list.html", elections=elections)

@app.route("/voter/results/<int:election_id>")
@login_required
def voter_results(election_id):
    user = get_current_user()
    election = query_db("SELECT * FROM Election WHERE id=?", (election_id,), one=True)

    if not election or election["is_active"]:
        abort(403)

    if not user_voted_in_election(user["id"], election_id):
        abort(403)

    positions = query_db("SELECT * FROM Positions WHERE election_id=?", (election_id,))

    return render_template("voter_results.html", election=election, positions=positions)

@app.route("/voter/api/results/<int:position_id>")
@login_required
def voter_api_results(position_id):
    user = get_current_user()
    position = query_db("SELECT * FROM Positions WHERE id=?", (position_id,), one=True)

    if not position:
        return jsonify({"error": "not found"}), 404

    election = query_db("SELECT * FROM Election WHERE id=?", (position["election_id"],), one=True)

    if not election or election["is_active"]:
        return jsonify({"error": "Results aren't available until this election has closed."}), 403

    if not user_voted_in_election(user["id"], election["id"]):
        return jsonify({"error": "forbidden"}), 403

    rows = query_db("""
        SELECT Users.name AS name, COUNT(Votes.id) AS votes
        FROM Candidates
        JOIN Users ON Candidates.user_id = Users.id
        LEFT JOIN Votes ON Votes.candidate_id = Candidates.id
        WHERE Candidates.position_id = ?
        GROUP BY Candidates.id
        ORDER BY votes DESC, Users.name ASC
    """, (position_id,))

    candidates = [{"name": r["name"], "votes": int(r["votes"])} for r in rows]
    total_votes = sum(c["votes"] for c in candidates)

    return jsonify({
        "position_name": position["position_name"],
        "candidates": candidates,
        "total_votes": total_votes
    })

@app.route("/admin/voters")
@admin_required
def admin_voters():
    election = get_active_election() or query_db("SELECT * FROM Election ORDER BY id DESC", one=True)
    search = request.args.get("q", "").strip()

    voters = []

    if election:
        query = """
            SELECT Users.id, Users.name, Users.email,
                   MIN(Votes.time) AS first_vote_time,
                   GROUP_CONCAT(Positions.position_name, ', ') AS positions_voted
            FROM Votes
            JOIN Positions ON Votes.position_id = Positions.id
            JOIN Users ON Votes.voter_id = Users.id
            WHERE Positions.election_id = ?
        """
        params = [election["id"]]

        if search:
            query += " AND (Users.name LIKE ? OR Users.email LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]

        query += " GROUP BY Users.id ORDER BY Users.name"

        voters = query_db(query, tuple(params))

    return render_template("admin_voters.html", election=election, voters=voters, search=search)

@app.route("/admin/manage-admins", methods=["GET", "POST"])
@admin_required
def manage_admins():
    current_user = get_current_user()

    if request.method == "POST":
        target_id = request.form.get("user_id")
        action = request.form.get("action")

        if str(current_user["id"]) == str(target_id):
            flash("You can't change your own admin rights.", "error")
        
        elif action == "promote":
            execute_db("UPDATE Users SET is_admin=1 WHERE id=?", (target_id,))
            flash("User has been promoted to admin.", "success")
        
        elif action == "demote":
            execute_db("UPDATE Users SET is_admin=0 WHERE id=?", (target_id,))
            flash("User has been demoted from admin.", "info")

        return redirect("/admin/manage-admins")

    search = request.args.get("q", "").strip()

    if search:
        users = query_db(
            "SELECT * FROM Users WHERE email LIKE ? OR name LIKE ? ORDER BY name", (f"%{search}%", f"%{search}%"))
        
    else:
        users = query_db("SELECT * FROM Users ORDER BY is_admin DESC, name")

    return render_template("admin_manage_admins.html", users=users, search=search)

@app.route("/admin/announcements", methods=["GET", "POST"])
@admin_required
def admin_announcements():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            message = request.form.get("message", "").strip()[:300]
            level = request.form.get("level", "info")

            if message:
                execute_db(
                    "INSERT INTO Announcements (message, level, created_by) VALUES (?, ?, ?)", (message, level, session["user_id"]))
                
                log_admin_action("create_announcement", message)
                flash("Announcement posted.", "success")

        elif action == "deactivate":
            announcement_id = request.form.get("announcement_id")
            execute_db("UPDATE Announcements SET is_active=0 WHERE id=?", (announcement_id,))

            log_admin_action("deactivate_announcement", f"id={announcement_id}")
            flash("Announcement removed.", "info")

        return redirect("/admin/announcements")

    announcements = query_db("SELECT * FROM Announcements ORDER BY id DESC LIMIT 50")

    return render_template("admin_announcements.html", announcements=announcements)

@app.route("/admin/audit-log")
@admin_required
def admin_audit_log():
    logs = query_db("""
        SELECT AuditLog.*, Users.name AS admin_name
        FROM AuditLog LEFT JOIN Users ON AuditLog.admin_id = Users.id
        ORDER BY AuditLog.id DESC
        LIMIT 200
    """)
    
    return render_template("admin_audit_log.html", logs=logs)

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    app.run(debug=True)