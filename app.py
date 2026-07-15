from flask import Flask, render_template, session, redirect, request, jsonify, g
import sqlite3
import os
from dotenv import load_dotenv
from google.oauth2 import id_token
from google.auth.transport import requests

load_dotenv()

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

    if not (is_school_account ot is_allowlisted_admin):
        return None

    return {
        "google_id": idinfo["sub"],
        "email": email,
        "name": idinfo["name"],
        "should_be_admin": is_allowlisted_admin,
    }

@app.route("/")
def home():
    return render_template(
        "index.html",
        user=session.get("user_email")
    )


@app.route("/dashboard")
def dashboard():
    if "user_email" not in session:
        return redirect("/")
    return f"Logged in as {session['user_email']}"


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
        execute_db("""
            INSERT INTO Users (google_id, email, name)
            VALUES (?, ?, ?)
        """, (
            user_data["google_id"],
            user_data["email"],
            user_data["name"]
        ))

    session["user_email"] = user_data["email"]

    return jsonify({"success": True})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)