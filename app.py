from flask import Flask, render_template, session, redirect, request, jsonify, g, abort
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

# replaces any old env varible with the new one
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

    idinfo = id_token.verify_oauth2_token(
        token,
        requests.Request(),
        GOOGLE_CLIENT_ID
    )

    email = idinfo["email"].lower()

    is_school_account = email.endswith(SCHOOL_DOMAIN)
    is_allowlisted_admin = email in ADMIN_EMAILS

    if not (is_school_account or is_allowlisted_admin):
        return None

    return {
        "google_id": idinfo["sub"],
        "email": email,
        "name": idinfo["name"],
        "should_be_admin": is_allowlisted_admin
    }

# Wrapper functions
def get_current_user():
    if "user_id" not in session:
        return None

    return query_db("SELECT * FROM Users Where id=?", (session["user_id"],), one=True)

def is_candidate(user_id):
    row = query_db("SELECT id FROM Candidates WHERE user_id=?", (user_id,), one=True)
    
    return row is not None

def get_active_election():
    return query_db("SLELCT * FROM Election WHERE is_active=1", one=True)

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

@app.route("/")
def home():
    return render_template(
        "index.html",
        user=session.get("user_email")
    )

@app.route("/login")
def login_page():
    return render_template(
        "login.html",
        client_id=GOOGLE_CLIENT_ID
    )

@app.route("/login", methods=["POST"])
def login_data():

    token = request.json.get("credential")

    user_data = verify_google_token(token)

    if not user_data:
        return jsonify({"error": "Unauthorized domain"}), 403

    user = query_db(
        "SELECT * FROM Users WHERE google_id=?",
        (user_data["google_id"],),
        one=True
    )

    if not user:
        if user_data["should_be_admin"]:
            is_admin_val = 1
        else:
            is_admin_val = 0

        execute_db("""
            INSERT INTO Users (google_id, email, name, is_admin)
            VALUES (?, ?, ?, ?)
        """, (
            user_data["google_id"],
            user_data["email"],
            user_data["name"],
            is_admin_val
        ))

        user = query_db(
            "SELECT * FROM Users WHERE google_id=?",
            (user_data["google_id"],),
            one=True
        )
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
        raw_position = query_db("SELECT * FROM Positions WHERE election_id=?", (election["id"],))

        for pos in raw_position:
            candidates = query_db("""
                SELECT Candidates.id AS candidate_id, Candidates.bio, Candidates.photo,
                    Users.name AS candidate_name
                FROM Candidates
                JOIN Users ON Candidates.user_id = Users.id
                WHERE Candidates.position_id = ?
            """, (pos["id"],))

        candidates_list = []

        for c in candidates:
            media = json.loads(c["photo"]) if c["photo"] else {}
            candidates_list.append({
                    "id": c["candidate_id"],
                    "name": c["candidate_name"],
                    "bio": c["bio"],
                    "media": media,
            })
        
        already_voted = query_db(
            "SELECT id FROM Votes WHERE voter_id=? AND position_id=?",
            (user["id"], pos["id"]), one=True
        )

        positions.append({
            "position": pos,
            "candidates": candidate_list,
            "has_voted": already_voted is not None,
        })

    return render_template(
        "voter_dashboard.html", user=user, election=election, positions=positions, voting_open=is_open, voting_message=message)

@app.route("/candidate")
@candidate_required
def candidate_dashboard():
    return "Candidate dashboard"

@app.route("/admin")
@admin_required
def admin_dashboard():
    return "Admin dashboard"

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

@app.before_request
def csrf_protect():
    if request.method == "POST":
        if request.path == "/login":
            return

        token = session.get("csrf_token")
        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        
        if not token or not sent_token or not secrets_lib.compare_digest(token, sent_token):
            abort(403)

@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets_lib.token_hex(32)
        
    return dict(csrf_token=session["csrf_token"])

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromisoformat(value + ":00")

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

if __name__ == "__main__":
    app.run(debug=True)