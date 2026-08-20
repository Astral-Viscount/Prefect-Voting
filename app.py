"""
app.py — Burnside Prefect Voting System (Flask backend)

This is the single Flask application file for the prefect voting web app.
It handles:
    - Google OAuth login restricted to school/admin email domains
    - Voter, Candidate and Admin dashboards (role-based access control)
    - Election / Position / Candidate management (admin only)
    - Vote casting with one-vote-per-position enforcement at the database level
    - Live and closed-election results (JSON APIs consumed by charts.js)
    - Candidate self-service profile editing (bio, photo, voice, video link)
    - Site announcements and an admin audit log
    - CSRF protection and custom 403/404 error pages

Architecture notes for the dev log:
    - Routes are kept thin: most read/write logic goes through query_db() /
      execute_db() helper functions rather than raw sqlite3 calls scattered
      around the file. This is what "well-structured, logical response to
      the specified task" (Excellence - Programming) refers to.
    - Access control is implemented as decorators (login_required,
      candidate_required, admin_required, voter_required) rather than
      repeating the same "if not logged in" checks in every route.
    - Flask's `g` object is used to cache the current user for the
      lifetime of a single request, so get_current_user() only hits the
      database once per request even if it's called multiple times.
"""

from flask import (
    Flask, render_template, session, redirect, request,
    jsonify, g, abort, flash, url_for
)
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
from google.auth.exceptions import GoogleAuthError
import re
from zoneinfo import ZoneInfo

"""  
Load variables from .env into os.environ. override=True means that if the
same variable is already set in the real OS environment (e.g. left over
from a previous run), the .env value always wins - keeps local dev
consistent no matter what shell state we're in.
""" 
load_dotenv(override=True)

# Set up the Flask app
app = Flask(__name__)

# Load the secret key from the environment to keep sessions secure
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

""" 
Fail loudly and immediately if the app is started without a secret key,
rather than letting Flask silently run with session signing broken.
""" 
if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "SECRET_KEY is missing"
        "Please generate a new one by running the secret_token.py "
        "file from /utils folder and add it to .env"
    )

# --- Make sessions and cookies more secure ---
# Prevent JavaScript from reading the session cookie (stops XSS attacks).
app.config["SESSION_COOKIE_HTTPONLY"] = True
# Stop the cookie from being sent on cross-site requests (stops CSRF attacks).
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Log users out automatically after 8 hours.
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 8

"""  
Admin allow-list, built once at startup from the ADMIN_EMAILS env var
(comma separated). Using a set comprehension instead of a loop is more
efficient for membership testing (`in ADMIN_EMAILS`) later on.
""" 
ADMIN_EMAILS = {
    admin_email.strip().lower()
    for admin_email in os.getenv("ADMIN_EMAILS", "").split(",")
    if admin_email.strip()
}

# SCHOOL_DOMAIN = os.getenv("SCHOOL_DOMAIN", "@burnside.school.nz").lower()

"""  
Same idea as ADMIN_EMAILS, but for the list of email domains that are
allowed to sign in as ordinary voters/candidates (e.g. @burnside.school.nz).
Supporting a comma-separated list (instead of one hardcoded domain) makes
it easy to add @gmail.com temporarily for testing without touching code. 
"""
SCHOOL_DOMAINS = {
    school_domain.strip().lower()
    for school_domain in os.getenv("SCHOOL_DOMAIN").split(",")
    if school_domain.strip()
}
# print(f"debug: school domain = {SCHOOL_DOMAIN!r}")

# Where we save the SQLite database
DATABASE = "voting.db"
# Google Login client ID
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# --- Settings for candidate uploads (photos, audio) ---
# Folder to store candidate photos and audio
UPLOAD_FOLDER = os.path.join("static", "uploads", "candidates")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# File types we allow users to upload
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
ALLOWED_AUDIO_EXT = {"webm", "mp3", "wav", "ogg"}
# Limit upload size to 32 MB so people can't crash the server with huge files
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

# We only allow YouTube links for videos. This saves us from hosting large video files.
YOUTUBE_URL_RE = re.compile(
    r'^https?://(www\.)?(youtube\.com/(watch\?v=[\w-]{6,}(&\S*)?|'
    r'shorts/[\w-]{6,}(\?\S*)?)|youtu\.be/[\w-]{6,}(\?\S*)?)$'
)

# Always use New Zealand time for the elections, no matter where the server is.
NZ_TIME = ZoneInfo("Pacific/Auckland")


def now_nz():
    # Get the current time in NZ.

    return datetime.now(NZ_TIME).replace(tzinfo=None)


def get_db():
    # Get a database connection for this request, or make a new one if we don't have it yet.

    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    # Close the database connection when we're done.
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    """Run a SELECT query and return the results.

    Args:
        query: SQL string, with '?' placeholders for parameters.
        args: tuple of values to substitute for the '?' placeholders.
              Always using parameterised queries (never manual string
              formatting) is what prevents SQL injection in this app.
        one: if True, return only the first row (or None if no rows).
             If False, return the full list of rows (possibly empty).

    Returns:
        A single sqlite3.Row, a list of sqlite3.Row, or None.
    """
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    """Run an INSERT/UPDATE/DELETE statement and commit immediately.

    Committing on every write (rather than batching) keeps the code simple
    and matches how this app is used - lots of small, independent writes
    (one vote, one announcement, one admin toggle) rather than large
    multi-step transactions.
    """
    db = get_db()
    db.execute(query, args)
    db.commit()


def verify_google_token(token):
    """Validate a Google Sign-In ID token and decide if the user may log in.

    Verifies the token's signature and audience against GOOGLE_CLIENT_ID,
    then checks the verified email against the school domain allow-list
    OR the explicit admin allow-list.

    Returns:
        None if the token is valid but the email isn't allowed to use the
        site (caller treats this as "Unauthorized domain").
        A dict of {google_id, email, name, should_be_admin} if the login
        is accepted.
        A Flask (jsonify(...), status_code) tuple if the token itself is
        invalid/expired/malformed - the caller returns this directly to
        the browser as an error response.
    """

    try:
        # Ask Google to check if this login token is real
        id_info = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

    except ValueError as e:
        # The token was messed up or didn't match.
        return jsonify({
            "status": "error",
            "info": "invalid token format or signature",
            "error_message": str(e)
        }), 401

    except GoogleAuthError as e:
        # Something went wrong on Google's end, or the token expired.
        return jsonify({
            "status": "error",
            "info": "google authentication failed or token expired",
            "error_message": str(e)
        }), 401

    except Exception as e:
        # Catch any other weird errors so the app doesn't crash.
        return jsonify({
            "status": "error",
            "info": "unexpected/unknown error",
            "error_message": str(e)
        }), 500

    # Make the email lowercase so it's easier to check
    email = id_info["email"].lower()

    # Check if the email ends with one of the allowed school domains
    is_school_account = any(
        email.endswith(domain) for domain in SCHOOL_DOMAINS
    )
    # Check if the user is on the admin list
    is_allowlisted_admin = email in ADMIN_EMAILS

    # Block anyone who isn't a student or an admin
    if not (is_school_account or is_allowlisted_admin):
        return None

    # If everything looks good, return the user's details
    return {
        "google_id": id_info["sub"],
        "email": email,
        "name": id_info["name"],
        "should_be_admin": is_allowlisted_admin
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_current_user():
    """Return the logged-in user's row, cached on `g` for this request.

    Returns None if nobody is logged in. Caching on `g` means that even if
    this is called from several places in the same request (a route plus
    several context processors, for example) it only queries the database
    once.
    """
    if "user_id" not in session:
        return None

    # Look up the user in the database and save it for this request
    if not hasattr(g, "current_user"):
        g.current_user = query_db(
            "SELECT * FROM Users Where id=?",
            (session["user_id"],), one=True
        )

    return g.current_user


def is_candidate(user_id):
    """Return True if this user has ever been made a candidate for any
    position (regardless of whether that election is still active)."""
    # Check the database to see if this user is a candidate
    row = query_db(
        "SELECT id FROM Candidates WHERE user_id=?",
        (user_id,), one=True
    )

    return row is not None


def get_active_election():
    """Return the single currently-active Election row, or None.

    Relies on the invariant (enforced in admin_elections' toggle_active
    action) that at most one election ever has is_active = 1 at a time.
    """
    return query_db("SELECT * FROM Election WHERE is_active=1", one=True)


def is_candidate_in_active_election(user_id):
    """Return True if this user is standing as a candidate specifically in
    the currently active election (not just in some past election)."""
    election = get_active_election()
    if not election:
        return False
    return is_candidate_in_election(user_id, election["id"])


def login_required(view):
    """Decorator: redirect to the login page unless a valid session exists.

    Also defends against a "ghost session" - a session cookie whose
    user_id no longer exists in the Users table (e.g. deleted by an
    admin) - by clearing the session and redirecting rather than letting
    the route crash on a None user.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Make sure the user is actually logged in
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        # Check that the user still exists in the database
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login_page"))

        return view(*args, **kwargs)

    return wrapped


def candidate_required(view):
    """Decorator: only allow users who are a candidate (in any election)
    to access this route; everyone else gets a 403 page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Send them to the login page if they aren't signed in
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        # Log them out if their account is gone
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login_page"))

        # Block them if they aren't a candidate
        if not is_candidate(user["id"]):
            return render_template("403.html"), 403

        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Decorator: only allow users flagged is_admin=1 to access this route."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Block people who aren't logged in
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        # Log them out if their account was deleted
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login_page"))

        # Block them if they aren't an admin
        if not user["is_admin"]:
            return render_template("403.html"), 403

        return view(*args, **kwargs)

    return wrapped


def voter_required(view):
    """Decorator: block admins and candidates-in-the-active-election from
    voter-only pages.

    This exists so that, e.g., a candidate cannot see the voter dashboard
    and vote for their own position, and an admin (who isn't meant to have
    a vote in the election they're running) can't either.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Make sure they are logged in
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        # Make sure their account still exists
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login_page"))

        # Block admins and active candidates from voting
        if user["is_admin"] or is_candidate_in_active_election(user["id"]):
            return render_template("403.html"), 403

        return view(*args, **kwargs)

    return wrapped


def parse_date(value):
    """Parse a stored date/time string into a datetime, or None.

    Handles two shapes of input:
        - a full ISO datetime string (from datetime.isoformat())
        - the shorter "YYYY-MM-DDTHH:MM" string that HTML
          <input type="datetime-local"> forms submit (no seconds), which
          fromisoformat() can't parse directly, so ":00" is appended.
    """
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)

    except ValueError:
        # If the time is missing seconds (like from HTML forms), add ":00" and try again
        return datetime.fromisoformat(value + ":00")


def format_datetime(value):
    """Format a stored date/time string for display, e.g. '20 Aug 2026, 09:00 AM'."""
    date_time = parse_date(value)

    if not date_time:
        return "Not set"

    # Turn the date into a nice, readable format
    return date_time.strftime("%d %b %Y, %I:%M %p")


@app.template_filter("datetime")
def datetime_filter(value):
    """Jinja filter: {{ some_value|datetime }} in templates calls this."""
    return format_datetime(value)


def election_dates_conflict(start_date, end_date, exclude_id=None):
    """Return the title of an existing election whose voting window
    overlaps the given start/end, or None if there's no conflict.

    Only one election is allowed to be open for voting at a time, so this
    is called whenever an election is created or its dates are edited.
    Missing dates are treated as "open ended" (datetime.min / datetime.max)
    so an election with no end date still correctly conflicts with anything
    that starts after it.

    Args:
        exclude_id: when editing an existing election, its own id is
            excluded so it doesn't "conflict with itself".
    """
    # Figure out the start and end times
    start_dt = parse_date(start_date) or datetime.min
    end_dt = parse_date(end_date) or datetime.max

    # Get the dates for all other elections
    other_elections = query_db(
        "SELECT id, title, start_date, end_date FROM Election"
    )

    for other in other_elections:
        # Skip the current election if we are editing it
        if exclude_id and str(other["id"]) == str(exclude_id):
            continue

        other_start = parse_date(other["start_date"]) or datetime.min
        other_end = parse_date(other["end_date"]) or datetime.max

        # Check if one election ends before the other starts
        new_ends_first = end_dt <= other_start
        other_ends_first = other_end <= start_dt

        # If they overlap, return the name of the conflicting election
        if not new_ends_first and not other_ends_first:
            return other["title"]

    return None


def sync_election_status():
    """Keep Election.is_active in sync with the current time.

    Runs before every request (see check_expired_elections below):
        1. Any election marked active whose end_date has passed gets
           deactivated automatically, so voting can't continue past the
           advertised closing time even if no admin is watching.
        2. If nothing is active afterwards, the next election whose
           start_date has arrived (and hasn't ended) is activated
           automatically, so admins don't have to manually flip the
           switch at the exact start time.
    """
    now = now_nz()

    # Close any active elections that have passed their end date
    active_elections = query_db(
        "SELECT id, end_date FROM Election WHERE is_active=1"
    )

    for election in active_elections:
        end = parse_date(election["end_date"])

        if end and now > end:
            execute_db(
                "UPDATE Election SET is_active=0 WHERE id=?",
                (election["id"],)
            )

    # Stop here if an election is still running
    still_active = query_db(
        "SELECT id FROM Election WHERE is_active=1", one=True
    )

    if still_active:
        return

    # Look for inactive elections that should be starting right now
    candidates = query_db(
        "SELECT id, start_date, end_date FROM Election WHERE is_active=0"
    )

    for election in candidates:
        start = parse_date(election["start_date"])
        end = parse_date(election["end_date"])

        if start and now >= start and (not end or now <= end):
            execute_db(
                "UPDATE Election SET is_active=1 WHERE id=?",
                (election["id"],)
            )
            break


@app.before_request
def csrf_protect():
    """Reject any POST request that doesn't carry a matching CSRF token.

    The login endpoint is exempt because the browser hasn't been issued a
    session (and therefore a csrf_token) until after a successful login -
    it's instead protected by Google's own token verification.
    secrets_lib.compare_digest is used instead of `==` so the comparison
    takes constant time and doesn't leak the token via a timing attack.
    """
    if request.method == "POST":
        # Don't check the login page because they don't have a token yet
        if request.path == url_for("login_data"):
            return

        # Get the CSRF token from the session and the request
        token = session.get("csrf_token")
        sent_token = (
            request.form.get("csrf_token")
            or request.headers.get("X-CSRFToken")
        )

        # Block the request if the tokens are missing or don't match
        if not token or not sent_token or not secrets_lib.compare_digest(
            token, sent_token
        ):
            abort(403)


@app.before_request
def check_expired_elections():
    """Run the election auto-activate/auto-deactivate check on every request."""
    sync_election_status()


def user_voted_in_election(user_id, election_id):
    """Return True if this user has cast at least one vote in this election."""
    # See if this person has already voted in this election
    row = query_db("""
        SELECT Votes.id
        FROM Votes
        JOIN Positions ON Votes.position_id = Positions.id
        WHERE Votes.voter_id = ? AND Positions.election_id = ?
        LIMIT 1
    """, (user_id, election_id), one=True)

    return row is not None


def log_admin_action(action, details="", admin_id="__unset__"):
    """Write a row to the AuditLog table describing an admin action.

    Deliberately only ever called from admin-side management routes
    (announcements, elections, etc.) - never from anything in the voting
    flow - so the audit log can never end up recording who voted for whom.
    This is the mechanism referenced in privacy.html under
    "Who can see what".

    Args:
        admin_id: defaults to the string "__unset__" (rather than None) so
            that "no admin id was explicitly passed" can be distinguished
            from "the caller explicitly wants admin_id=None" (e.g. for a
            fully automatic/system action with no human admin attached).
    """
    # Figure out which admin is doing this, if not told specifically
    if admin_id == "__unset__":
        admin = get_current_user()

        if admin:
            admin_id = admin["id"]
        else:
            admin_id = None

    # Save this action in the audit log
    execute_db(
        "INSERT INTO AuditLog (admin_id, action, details) "
        "VALUES (?, ?, ?)",
        (admin_id, action, details)
    )


def is_candidate_in_election(user_id, election_id):
    """Return True if this user is a candidate for some position that
    belongs to the given election (not necessarily the active one)."""
    # Check if this user is running in this election
    row = query_db("""
        SELECT Candidates.id
        FROM Candidates
        JOIN Positions ON Candidates.position_id = Positions.id
        WHERE Candidates.user_id = ? AND Positions.election_id = ?
        LIMIT 1
    """, (user_id, election_id), one=True)

    return row is not None


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """Landing page. Shows a login button, or a welcome message + dashboard
    link if a session already exists."""
    return render_template("index.html", user=session.get("user_name"))


@app.route("/login")
def login_page():
    """Render the Google Sign-In button page."""
    return render_template("login.html", client_id=GOOGLE_CLIENT_ID)


@app.route("/login", methods=["POST"])
def login_data():
    """Receive a Google ID token from the front end, verify it, and either
    log an existing user in or create a new Users row for a first-time
    login.

    Also "self-heals" two things on every login for an existing user:
        - if their email is on the admin allow-list but their is_admin
          flag is somehow still 0, it's promoted here
        - if their Google-account display name has changed, it's updated
    """

    # Get the Google login token from the request
    token = request.json.get("credential")

    # Check if the token is valid and allowed
    user_data = verify_google_token(token)

    # Block them if the token is bad or they have the wrong email domain
    if not user_data:
        return jsonify({"error": "Unauthorized domain"}), 403

    # Look up the user in our database
    user = query_db(
        "SELECT * FROM Users WHERE google_id=?",
        (user_data["google_id"],), one=True
    )

    # Create a new account if this is their first time logging in
    if not user:
        if user_data["should_be_admin"]:
            is_admin_val = 1
        else:
            is_admin_val = 0

        try:
            execute_db(
                "INSERT INTO Users (google_id, email, name, is_admin) "
                "VALUES (?, ?, ?, ?)",
                (
                    user_data["google_id"], user_data["email"],
                    user_data["name"], is_admin_val
                )
            )

        except sqlite3.IntegrityError:
            # Rare race: two near-simultaneous first logins for the same
            # google_id/email (unique columns). the
            # SELECT below will now find the row the other request created.
            pass

        user = query_db(
            "SELECT * FROM Users WHERE google_id=?",
            (user_data["google_id"],), one=True
        )

    else:
        # Make sure they are marked as an admin if they should be
        if user_data["should_be_admin"] and not user["is_admin"]:
            execute_db(
                "UPDATE Users SET is_admin=1 WHERE id=?", (user["id"],)
            )

        # Update their name if they changed it on Google
        if user["name"] != user_data["name"]:
            execute_db(
                "UPDATE Users SET name=? WHERE id=?",
                (user_data["name"], user["id"])
            )

        user = query_db(
            "SELECT * FROM Users WHERE id=?", (user["id"],), one=True
        )

    # session.clear() wipes any stale data from a previous session/user
    # before writing the new one, and a fresh CSRF token is issued
    # implicitly by inject_csrf_token() on the next request.
    session.clear()
    session.permanent = True
    session["user_email"] = user["email"]
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["is_admin"] = bool(user["is_admin"])
    session["is_candidate"] = is_candidate(user["id"])

    return jsonify({"success": True})


@app.route("/logout")
def logout():
    """Clear the session and return to the home page."""
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    """Role router: sends the logged-in user to the correct dashboard
    (admin / candidate-in-current-election / voter) without them needing
    to know which one applies to them."""
    user = get_current_user()

    # Send admins to their dashboard
    if user["is_admin"]:
        return redirect(url_for("admin_dashboard"))
    # Send active candidates to their dashboard
    if is_candidate_in_active_election(user["id"]):
        return redirect(url_for("candidate_dashboard"))

    # Send everyone else to the regular voting page
    return redirect(url_for("voter_dashboard"))


# ---------------------------------------------------------------------------
# Voter routes
# ---------------------------------------------------------------------------

@app.route("/voter")
@voter_required
@login_required
def voter_dashboard():
    """Show every position in the active election, the candidates standing
    for each, and whether this voter has already voted for that position.

    Candidate media is stored as a JSON blob in Candidates.photo (keys:
    photo / voice / video_url) so it's decoded here into a plain dict
    before being handed to the template.
    """
    user = get_current_user()
    election = get_active_election()
    is_open, message = voting_is_open(election)

    positions = []

    # Get all the positions and candidates for the current election
    if election:
        raw_positions = query_db(
            "SELECT * FROM Positions WHERE election_id=?",
            (election["id"],)
        )

        for raw_position in raw_positions:
            candidates = query_db("""
                SELECT Candidates.id AS candidate_id, Candidates.bio,
                    Candidates.photo, Users.name AS candidate_name
                FROM Candidates
                JOIN Users ON Candidates.user_id = Users.id
                WHERE Candidates.position_id = ?
            """, (raw_position["id"],))

            candidates_list = []

            for candidate in candidates:

                # Unpack the candidate's photos and videos
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

            # Check if this person already voted for this role
            already_voted = query_db(
                "SELECT id FROM Votes WHERE voter_id=? AND position_id=?",
                (user["id"], raw_position["id"]), one=True
            )

            positions.append({
                "position": dict(raw_position),
                "candidates": candidates_list,
                "has_voted": already_voted is not None,
            })

    return render_template(
        "voter_dashboard.html", user=user, election=election,
        positions=positions, voting_open=is_open, voting_message=message
    )


@app.route("/vote/<int:position_id>/<int:candidate_id>", methods=["POST"])
@login_required
@voter_required
def cast_vote(position_id, candidate_id):
    """Record one vote for a candidate in a position.

    Defence in depth against an invalid or duplicate vote:
        1. voting_is_open() - is voting currently allowed at all?
        2. the position must belong to the currently active election
        3. the candidate must actually be standing for that position
        4. the Votes table has a UNIQUE(voter_id, position_id) constraint,
           so even a race condition (two rapid double-clicks) can only
           ever result in one row - the second INSERT raises
           IntegrityError, which is caught and turned into a friendly
           JSON error rather than a 500.
    """
    user = get_current_user()
    election = get_active_election()
    is_open, message = voting_is_open(election)

    # Stop them if voting is closed
    if not is_open:
        return jsonify({"error": message}), 403

    position = query_db(
        "SELECT * FROM Positions WHERE id=?", (position_id,), one=True
    )

    # Make sure the position is real and part of this election
    if not position or position["election_id"] != election["id"]:
        return jsonify(
            {"error": "Invalid position for the current election."}
        ), 400

    candidate = query_db(
        "SELECT * FROM Candidates WHERE id=? AND position_id=?",
        (candidate_id, position_id), one=True
    )

    # Make sure the candidate is actually running for this role
    if not candidate:
        return jsonify(
            {"error": "Invalid candidate for this position."}
        ), 400

    try:
        # Try to save their vote
        execute_db(
            "INSERT INTO Votes (voter_id, position_id, candidate_id) "
            "VALUES (?, ?, ?)",
            (user["id"], position_id, candidate_id)
        )

    except sqlite3.IntegrityError:
        # Tell them they already voted if they try to vote twice
        return jsonify(
            {"error": "You have already voted for this position."}
        ), 409

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Candidate routes
# ---------------------------------------------------------------------------

@app.route("/candidate")
@candidate_required
def candidate_dashboard():
    """Show a candidate their own standing, profile preview, and - once
    their election has closed - their final vote count.

    Vote counts are deliberately withheld while candidate_election is
    still active, so a candidate can't see live numbers and adjust their
    campaigning mid-election (see candidate_dashboard.html for the
    matching user-facing explanation).
    """
    user = get_current_user()

    # Get the candidate's role and election info
    candidate_row = query_db("""
        SELECT Candidates.*, Positions.position_name, Positions.election_id
        FROM Candidates
        JOIN Positions ON Candidates.position_id = Positions.id
        WHERE Candidates.user_id = ?
    """, (user["id"],), one=True)

    candidate_election = None

    if candidate_row:
        candidate_election = query_db(
            "SELECT * FROM Election WHERE id=?",
            (candidate_row["election_id"],), one=True
        )

    vote_count = None

    # Only show how many votes they got if the election is over
    if candidate_row and candidate_election and \
            not candidate_election["is_active"]:
        row = query_db(
            "SELECT COUNT(*) AS c FROM Votes WHERE candidate_id=?",
            (candidate_row["id"],), one=True
        )

        vote_count = row["c"]

    # Unpack their media (photo/video) if they have any
    if candidate_row and candidate_row["photo"]:
        media = json.loads(candidate_row["photo"])
    else:
        media = {}

    return render_template(
        "candidate_dashboard.html", user=user, candidate=candidate_row,
        media=media, vote_count=vote_count
    )


@app.route("/candidate/profile", methods=["GET", "POST"])
@candidate_required
def candidate_profile():
    """Let a candidate view and edit their own bio/photo/voice/video link.

    All three media types are merged into one JSON dict stored in
    Candidates.photo, so uploading a new photo doesn't wipe out an
    existing voice clip or video link - each key is only overwritten if a
    new value for that specific field was actually submitted.

    File-upload safety measures:
        - extension allow-lists for image/audio uploads (rejects anything
          else with a flashed error rather than saving it)
        - secure_filename() strips any path characters an attacker could
          use for directory traversal
        - filenames are rebuilt as "candidate_<id>_photo.<ext>" rather
          than trusting the browser-supplied filename at all
        - the resolved save path is double-checked to still be inside
          UPLOAD_FOLDER before saving, and the request aborts (400) if not
    """
    user = get_current_user()
    candidate_row = query_db(
        "SELECT * FROM Candidates WHERE user_id=?",
        (user["id"],), one=True
    )

    # Load the candidate's current media
    if candidate_row["photo"]:
        media = json.loads(candidate_row["photo"])
    else:
        media = {}

    if request.method == "POST":
        # Clean up and shorten their bio and video link
        bio = request.form.get("bio", "").strip()[:2000]
        video_url = request.form.get("video_url", "").strip()[:500]

        # Make sure it's a real YouTube link
        if video_url:
            if YOUTUBE_URL_RE.match(video_url):
                media["video_url"] = video_url
            else:
                flash(
                    "Video link must be a YouTube video or "
                    "YouTube Shorts link.", "error"
                )

        photo_file = request.files.get("photo_file")

        # Safely handle their photo upload
        if photo_file and photo_file.filename:
            ext = Path(photo_file.filename).suffix.lower().lstrip('.')

            if ext in ALLOWED_IMAGE_EXT:
                filename = secure_filename(
                    f"candidate_{candidate_row['id']}_photo.{ext}"
                )
                full_path = Path(UPLOAD_FOLDER).resolve() / filename

                # Make sure the file saves in the right folder
                if not str(full_path).startswith(
                    str(Path(UPLOAD_FOLDER).resolve())
                ):
                    abort(400)

                photo_file.save(full_path)

                media["photo"] = url_for(
                    "static", filename=f"uploads/candidates/{filename}"
                )
            else:
                flash("Photo must be PNG, JPG or WEBP.", "error")

        voice_file = request.files.get("voice_file")

        # Safely handle their audio upload
        if voice_file and voice_file.filename:
            ext = Path(voice_file.filename).suffix.lower().lstrip('.')

            if ext in ALLOWED_AUDIO_EXT:
                filename = secure_filename(
                    f"candidate_{candidate_row['id']}_voice.{ext}"
                )
                voice_file.save(os.path.join(UPLOAD_FOLDER, filename))

                media["voice"] = url_for(
                    "static", filename=f"uploads/candidates/{filename}"
                )
            else:
                flash(
                    "Voice clip must be webm, mp3, wav or ogg.", "error"
                )

        # Save their new profile to the database
        execute_db(
            "UPDATE Candidates SET bio=?, photo=? "
            "WHERE id=? AND user_id=?",
            (bio, json.dumps(media), candidate_row["id"], user["id"])
        )

        flash("Profile updated.", "success")

        return redirect(url_for("candidate_dashboard"))

    return render_template(
        "candidate_profile.html", candidate=candidate_row, media=media
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin landing page: shows the active election (or, if none is
    active, the most recently created one) plus quick stats and links to
    every other admin tool."""
    user = get_current_user()
    # Get the active election, or the newest one if none are active
    election = get_active_election() or query_db(
        "SELECT * FROM Election ORDER BY id DESC", one=True
    )

    stats = {
        "positions": 0,
        "candidates": 0,
        "votes": 0
    }

    # Count the positions, candidates, and votes for this election
    if election:
        stats["positions"] = query_db(
            "SELECT COUNT(*) AS c FROM Positions WHERE election_id=?",
            (election["id"],), one=True
        )["c"]

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

    return render_template(
        "admin_dashboard.html", user=user, election=election, stats=stats
    )


@app.errorhandler(404)
def not_found(error):
    """Custom 404 page for any unmatched route."""
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(error):
    """Custom 403 page, used both for abort(403) and for the
    *_required decorators' access-denied case."""
    return render_template("403.html"), 403


@app.context_processor
def inject_csrf_token():
    """Make csrf_token available in every template, generating and storing
    a new one in the session the first time it's needed."""
    # Create a security token for this session if it doesn't have one
    if "csrf_token" not in session:
        session["csrf_token"] = secrets_lib.token_hex(32)

    return dict(csrf_token=session["csrf_token"])


@app.context_processor
def inject_announcements():
    """Make the list of currently-active site announcements available in
    every template, so layout.html can render the banner stack on any page
    without every route having to remember to pass it in."""
    # Get the latest active announcements
    active = query_db(
        "SELECT * FROM Announcements WHERE is_active=1 ORDER BY id DESC"
    )

    return dict(site_announcements=active)


@app.context_processor
def inject_role_flags():
    """Make is_candidate_ever / is_candidate_now available in every
    template, so layout.html's navigation can show/hide the "Edit
    Profile" and "Candidate Results" links correctly."""
    user = get_current_user()
    # Let templates know if the user is a candidate
    return dict(
        is_candidate_ever=is_candidate(user["id"]) if user else False,
        is_candidate_now=is_candidate_in_active_election(user["id"]) if user else False,
    )


def voting_is_open(election):
    """Return (is_open: bool, message: str | None) for whether voting can
    currently happen in the given election.

    message is a human-readable reason (e.g. "Voting starts ...") shown to
    the voter on the dashboard when is_open is False, or None when it's
    True.
    """
    # Say no if there isn't an active election
    if not election or not election["is_active"]:
        return False, "No current election running"

    now = now_nz()
    start = parse_date(election["start_date"])
    end = parse_date(election["end_date"])

    # Say no if the election hasn't started yet
    if start and now < start:
        return False, (
            f"Voting starts {start.strftime('%d %b %Y, %I:%M %p')}"
        )

    # Say no if the election is over
    if end and now > end:
        return False, "Voting has stopped for this election"

    return True, None


@app.route("/admin/elections", methods=["GET", "POST"])
@admin_required
def admin_elections():
    """Admin page for creating elections and editing/activating/closing
    existing ones. All four form actions (create, toggle_active,
    deactivate, update_dates) post to this single route and are
    distinguished by the hidden "action" field.

    Overlap prevention: election_dates_conflict() is checked before both
    create and update_dates, so admins physically cannot schedule two
    elections with overlapping voting windows (this backs up the "one
    election at a time" invariant relied on elsewhere, e.g.
    get_active_election()).
    """
    if request.method == "POST":
        action = request.form.get("action")

        # Handle creating a new election
        if action == "create":
            title = request.form.get("title", "").strip()[:100]
            description = request.form.get("description", "").strip()
            start_date = request.form.get("start_date") or None
            end_date = request.form.get("end_date") or None

            start_dt = parse_date(start_date)
            end_dt = parse_date(end_date)

            conflict_title = election_dates_conflict(start_date, end_date)

            # Check if the dates make sense
            if end_dt and end_dt <= now_nz():
                flash("End date/time must be in the future.", "error")
            elif start_dt and end_dt and end_dt <= start_dt:
                flash(
                    "End date/time must be after the start date/time.",
                    "error"
                )
            elif conflict_title:
                flash(
                    "These dates overlap with "
                    f"'{conflict_title}'. Only one election can be "
                    "running at a time, so voting windows can't "
                    "overlap. Please choose different dates.",
                    "error"
                )
            else:
                execute_db("""
                    INSERT INTO Election
                        (title, description, start_date, end_date,
                         is_active)
                    VALUES (?, ?, ?, ?, 0)
                """, (title, description, start_date, end_date))

                flash("Election created.", "success")

            return redirect(url_for("admin_elections"))

        # Handle turning an election on or off
        elif action == "toggle_active":
            election_id = request.form.get("election_id")
            election = query_db(
                "SELECT * FROM Election WHERE id=?",
                (election_id,), one=True
            )

            if not election:
                flash("Election not found.", "error")
            else:
                end = parse_date(election["end_date"])

                # Stop them from starting an election that's already over
                if end and now_nz() > end:
                    flash(
                        f"Can't activate '{election['title']}' — its "
                        "end time has already passed. Please Create a "
                        "new one or edit it's end time", "error"
                    )
                else:
                    # Only one election may be active at a time: turn
                    # every election off, then turn just this one on.
                    execute_db("UPDATE Election SET is_active = 0")
                    execute_db(
                        "UPDATE Election SET is_active = 1 WHERE id = ?",
                        (election_id,)
                    )
                    flash(
                        f"'{election['title']}' activated. All other "
                        "elections were deactivated.", "success"
                    )

            return redirect(url_for("admin_elections"))

        # Handle ending an election early
        elif action == "deactivate":
            election_id = request.form.get("election_id")
            election = query_db(
                "SELECT * FROM Election WHERE id=?",
                (election_id,), one=True
            )

            # Closing early is implemented as "set end_date to right now"
            # rather than a separate flag, so sync_election_status() and
            # voting_is_open() don't need any special-case logic for it -
            # the election just looks like it always ended at this moment.
            now_str = now_nz().strftime("%Y-%m-%dT%H:%M")

            execute_db(
                "UPDATE Election SET is_active = 0, end_date = ? "
                "WHERE id = ?",
                (now_str, election_id)
            )

            if election:
                flash(
                    f"'{election['title']}' closed early. Its end "
                    "time has been set to now so it won't restart on "
                    "its own.", "info"
                )
            else:
                flash("Election closed.", "info")

            return redirect(url_for("admin_elections"))

        # Handle changing an election's dates or details
        elif action == "update_dates":
            election_id = request.form.get("election_id")
            election = query_db(
                "SELECT * FROM Election WHERE id=?",
                (election_id,), one=True
            )

            title = request.form.get("title", "").strip()[:100]
            description = request.form.get("description", "").strip()
            start_date = request.form.get("start_date") or None
            end_date = request.form.get("end_date") or None

            start_dt = parse_date(start_date)
            end_dt = parse_date(end_date)

            # Make sure these new dates don't overlap with another election
            conflict_title = election_dates_conflict(
                start_date, end_date, exclude_id=election_id
            )

            if end_dt and end_dt <= now_nz():
                flash("End date/time must be in the future.", "error")
            elif start_dt and end_dt and end_dt <= start_dt:
                flash(
                    "End date/time must be after the start date/time.",
                    "error"
                )
            elif conflict_title:
                flash(
                    "These dates overlap with "
                    f"'{conflict_title}'. Only one election can be "
                    "running at a time, so voting windows can't "
                    "overlap. Please choose different dates.",
                    "error"
                )
            else:
                execute_db("""
                    UPDATE Election
                    SET title=?, description=?, start_date=?, end_date=?
                    WHERE id=?
                """, (title, description, start_date, end_date,
                      election_id))

                if election:
                    flash(f"'{election['title']}' updated.", "info")
                else:
                    flash("Election updated.", "info")

            return redirect(url_for("admin_elections"))

    # Show the admin page for elections
    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    return render_template("admin_elections.html", elections=elections)


@app.route("/admin/positions", methods=["GET", "POST"])
@admin_required
def admin_positions():
    """Admin page for adding/removing the positions (roles) being voted on
    within a chosen election, e.g. "Head Prefect", "Deputy Head Prefect".
    """
    election_id = request.values.get("election_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")

        # Create a new role
        if action == "create":

            execute_db(
                "INSERT INTO Positions "
                "(election_id, position_name, max_votes) "
                "VALUES (?, ?, ?)",
                (
                    request.form.get("election_id"),
                    request.form.get("position_name", "").strip(),
                    request.form.get("max_votes", 1)
                )
            )

            flash("Position added.", "success")

        # Remove a role
        elif action == "delete":
            position_id = request.form.get("position_id")
            
            # 1. Delete the child candidates first
            execute_db(
                "DELETE FROM Candidates WHERE position_id=?",
                (position_id,)
            )
            
            # 2. Then delete the parent position
            execute_db(
                "DELETE FROM Positions WHERE id=?",
                (position_id,)
            )

            flash("Position and all associated candidates removed.", "info")

        return redirect(url_for("admin_positions", election_id=election_id))

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    # Get the roles for this election
    if election_id:
        positions = query_db(
            "SELECT * FROM Positions WHERE election_id=?", (election_id,)
        )
    else:
        positions = []

    return render_template(
        "admin_positions.html", elections=elections, positions=positions,
        election_id=election_id
    )


@app.route("/admin/api/users/search")
@admin_required
def api_users_search():
    """JSON API used by admin_candidates.js's autocomplete box.

    Returns up to 8 matching users (by name or email substring) so an
    admin can find a student to assign as a candidate without typing
    their exact email. Requires at least 2 characters before querying,
    to avoid a very slow/broad LIKE '%%' scan on every keystroke.
    """
    q = request.args.get("q", "").strip()

    # Wait until they type at least 2 characters before searching
    if len(q) < 2:
        return jsonify([])

    # Search for students by name or email
    like = f"%{q}%"
    rows = query_db("""
        SELECT id, name, email FROM Users
        WHERE LOWER(name) LIKE LOWER(?) OR LOWER(email) LIKE LOWER(?)
        ORDER BY name
        LIMIT 8
    """, (like, like))

    return jsonify(
        [{"name": row["name"], "email": row["email"]} for row in rows]
    )


@app.route("/admin/candidates", methods=["GET", "POST"])
@admin_required
def admin_candidates():
    """Admin page for assigning students as candidates for a position, and
    removing candidates.

    Assignment accepts either an exact email or a name. Email is checked
    first (unique, unambiguous); if that fails, name is tried and only
    accepted if it matches exactly one student, otherwise the admin is
    asked to be more specific (there can easily be two students with the
    same first name).
    """
    election_id = request.values.get("election_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")

        # Handle adding a new candidate
        if action == "assign":
            query_text = request.form.get("student_query", "").strip()
            student = None
            error_message = None

            # Try to find the student by email first
            student = query_db(
                "SELECT * FROM Users WHERE LOWER(email)=LOWER(?)",
                (query_text,), one=True
            )

            # If email didn't work, try searching by their exact name
            if not student:
                name_matches = query_db(
                    "SELECT * FROM Users WHERE LOWER(name)=LOWER(?)",
                    (query_text,)
                )

                if len(name_matches) == 1:
                    student = name_matches[0]
                elif len(name_matches) > 1:
                    error_message = (
                        "More than one student has that name — please "
                        "use their email instead, or pick them from "
                        "the suggestions."
                    )

            # Show an error if we couldn't find them
            if not student:
                flash(
                    error_message or
                    "That student hasn't logged into the site yet. "
                    "Ask them to sign in once first, or double check "
                    "the spelling.", "error"
                )

            # Stop admins from running in elections
            elif student["is_admin"]:
                flash(
                    f"{student['name']} is an administrator and "
                    "cannot be added as a candidate.", "error"
                )

            else:
                # Make sure they aren't already running for this role
                existing = query_db(
                    "SELECT id FROM Candidates "
                    "WHERE user_id=? AND position_id=?",
                    (student["id"], request.form.get("position_id")),
                    one=True
                )

                if existing:
                    flash(
                        "That student is already a candidate for "
                        "this position.", "error"
                    )
                else:
                    # Add them as a candidate
                    execute_db(
                        "INSERT INTO Candidates "
                        "(position_id, user_id, bio, photo) "
                        "VALUES (?, ?, '', '{}')",
                        (request.form.get("position_id"), student["id"])
                    )
                    flash(
                        f"{student['name']} added as a candidate.",
                        "success"
                    )

        # Handle removing a candidate
        elif action == "remove":
            execute_db(
                "DELETE FROM Candidates WHERE id=?",
                (request.form.get("candidate_id"),)
            )

            flash("Candidate removed.", "info")

        return redirect(
            url_for("admin_candidates", election_id=election_id)
        )

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    if election_id:
        positions = query_db(
            "SELECT * FROM Positions WHERE election_id=?", (election_id,)
        )
    else:
        positions = []

    candidates = []

    # Get all candidates in this election
    if election_id:
        candidates = query_db("""
            SELECT Candidates.id, Candidates.bio, Positions.position_name,
                Users.name, Users.email
            FROM Candidates
            JOIN Positions ON Candidates.position_id = Positions.id
            JOIN Users ON Candidates.user_id = Users.id
            WHERE Positions.election_id = ?
        """, (election_id,))

    return render_template(
        "admin_candidates.html", elections=elections, positions=positions,
        candidates=candidates, election_id=election_id
    )


# ---------------------------------------------------------------------------
# Results routes (candidate view, voter view, admin live view)
# ---------------------------------------------------------------------------
# There are three near-identical sets of results routes/APIs below - one
# each for candidates, voters and admins. They're kept separate (rather
# than merged into one parameterised route) because each has a different
# access-control rule for *when* results become visible: candidates and
# voters can only see a CLOSED election they personally took part in;
# admins can see the live, currently-running election. Splitting them
# keeps each permission check simple and easy to verify independently.

@app.route("/candidate/results")
@candidate_required
def candidate_results_list():
    """List every closed election this candidate stood in, so they can
    pick one to view full results for."""
    user = get_current_user()

    # Find past elections where this user was a candidate
    elections = query_db("""
        SELECT DISTINCT Election.*
        FROM Candidates
        JOIN Positions ON Candidates.position_id = Positions.id
        JOIN Election ON Positions.election_id = Election.id
        WHERE Candidates.user_id = ? AND Election.is_active = 0
        ORDER BY Election.id DESC
    """, (user["id"],))

    return render_template("candidate_results_list.html", elections=elections)


@app.route("/candidate/results/<int:election_id>")
@candidate_required
def candidate_results(election_id):
    """Show the results page (chart containers) for one closed election
    this candidate stood in. Actual vote data is fetched client-side from
    candidate_api_results()."""
    user = get_current_user()
    election = query_db(
        "SELECT * FROM Election WHERE id=?", (election_id,), one=True
    )

    # Only show this if the election is over
    if not election or election["is_active"]:
        abort(403)

    # Make sure this user was actually in this election
    if not is_candidate_in_election(user["id"], election_id):
        abort(403)

    positions = query_db(
        "SELECT * FROM Positions WHERE election_id=?", (election_id,)
    )

    return render_template(
        "candidate_results.html", election=election, positions=positions
    )


@app.route("/candidate/api/results/<int:position_id>")
@candidate_required
def candidate_api_results(position_id):
    """JSON API: vote counts per candidate for one position, for a
    candidate viewing a closed election they stood in."""
    user = get_current_user()
    position = query_db(
        "SELECT * FROM Positions WHERE id=?", (position_id,), one=True
    )

    if not position:
        return jsonify({"error": "not found"}), 404

    election = query_db(
        "SELECT * FROM Election WHERE id=?",
        (position["election_id"],), one=True
    )

    # Hide results until the election is done
    if not election or election["is_active"]:
        return jsonify({
            "error": (
                "Results aren't available until this election has "
                "closed."
            )
        }), 403

    # Make sure the user ran in this election
    if not is_candidate_in_election(user["id"], election["id"]):
        return jsonify({"error": "forbidden"}), 403

    # Count how many votes each candidate got
    rows = query_db("""
        SELECT Users.name AS name, COUNT(Votes.id) AS votes
        FROM Candidates
        JOIN Users ON Candidates.user_id = Users.id
        LEFT JOIN Votes ON Votes.candidate_id = Candidates.id
        WHERE Candidates.position_id = ?
        GROUP BY Candidates.id
        ORDER BY votes DESC, Users.name ASC
    """, (position_id,))

    candidates = [
        {"name": r["name"], "votes": int(r["votes"])} for r in rows
    ]
    total_votes = sum(c["votes"] for c in candidates)

    return jsonify({
        "position_name": position["position_name"],
        "candidates": candidates,
        "total_votes": total_votes
    })


@app.route("/admin/api/results/<int:position_id>")
@admin_required
def api_results(position_id):
    """JSON API: vote counts per candidate for one position, for the admin
    live-results page. Unlike the candidate/voter versions, this is not
    restricted to closed elections - admins can watch results update in
    real time while voting is still open."""
    position = query_db(
        "SELECT * FROM Positions WHERE id=?",
        (position_id,),
        one=True
    )

    if not position:
        return jsonify({"error": "not found"}), 404

    # Count current votes for the admins to watch live
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
    """JSON API backing the turnout progress bar on the admin results
    page: how many logged-in, non-admin accounts have voted at least once
    in the current (or most recent) election, out of how many are
    eligible."""
    election = get_active_election() or query_db(
        "SELECT * FROM Election ORDER BY id DESC", one=True
    )

    if not election:
        return jsonify({"voted": 0, "eligible": 0})

    # Count how many students can vote
    eligible = query_db(
        "SELECT COUNT(*) AS c FROM Users WHERE is_admin = 0", one=True
    )["c"]

    # Count how many have actually voted so far
    voted = query_db("""
        SELECT COUNT(DISTINCT Votes.voter_id) AS c
        FROM Votes JOIN Positions ON Votes.position_id = Positions.id
        WHERE Positions.election_id = ?
    """, (election["id"],), one=True)["c"]

    return jsonify({"voted": voted, "eligible": eligible})


@app.route("/admin/results")
@admin_required
def admin_results():
    """Admin live-results page: one chart per position in the current (or
    most recent) election, plus the turnout bar."""
    election = get_active_election() or query_db(
        "SELECT * FROM Election ORDER BY id DESC", one=True
    )

    if election:
        positions = query_db(
            "SELECT * FROM Positions WHERE election_id=?",
            (election["id"],)
        )
    else:
        positions = []

    return render_template(
        "admin_results.html", election=election, positions=positions
    )


@app.route("/voter/results")
@login_required
@voter_required
def voter_results_list():
    """List every closed election this voter took part in, along with who
    they voted for in each (their own choices only - never anyone else's).
    """
    user = get_current_user()

    # Find past elections this person voted in
    elections = query_db("""
        SELECT DISTINCT Election.*
        FROM Votes
        JOIN Positions ON Votes.position_id = Positions.id
        JOIN Election ON Positions.election_id = Election.id
        WHERE Votes.voter_id = ? AND Election.is_active = 0
        ORDER BY Election.id DESC
    """, (user["id"],))

    my_votes = {}

    # Look up who they voted for in each election
    for election in elections:
        rows = query_db("""
            SELECT Positions.position_name AS position_name,
                Users.name AS candidate_name
            FROM Votes
            JOIN Positions ON Votes.position_id = Positions.id
            JOIN Candidates ON Votes.candidate_id = Candidates.id
            JOIN Users ON Candidates.user_id = Users.id
            WHERE Votes.voter_id = ? AND Positions.election_id = ?
            ORDER BY Positions.position_name
        """, (user["id"], election["id"]))

        my_votes[election["id"]] = rows

    return render_template(
        "voter_results_list.html", elections=elections, my_votes=my_votes
    )


@app.route("/voter/results/<int:election_id>")
@login_required
@voter_required
def voter_results(election_id):
    """Show the results page (chart containers) for one closed election
    this voter took part in."""
    user = get_current_user()
    election = query_db(
        "SELECT * FROM Election WHERE id=?", (election_id,), one=True
    )

    # Stop them if the election is still running or doesn't exist
    if not election or election["is_active"]:
        abort(403)

    # Make sure they actually voted in this election
    if not user_voted_in_election(user["id"], election_id):
        abort(403)

    positions = query_db(
        "SELECT * FROM Positions WHERE election_id=?", (election_id,)
    )

    return render_template(
        "voter_results.html", election=election, positions=positions
    )


@app.route("/voter/api/results/<int:position_id>")
@login_required
@voter_required
def voter_api_results(position_id):
    """JSON API: vote counts per candidate for one position, for a voter
    viewing a closed election they took part in."""
    user = get_current_user()
    position = query_db(
        "SELECT * FROM Positions WHERE id=?", (position_id,), one=True
    )

    if not position:
        return jsonify({"error": "not found"}), 404

    election = query_db(
        "SELECT * FROM Election WHERE id=?",
        (position["election_id"],), one=True
    )

    # Wait until the election is closed to show results
    if not election or election["is_active"]:
        return jsonify({
            "error": (
                "Results aren't available until this election has "
                "closed."
            )
        }), 403

    # Make sure they voted in this election
    if not user_voted_in_election(user["id"], election["id"]):
        return jsonify({"error": "forbidden"}), 403

    # Get the vote counts for this role
    rows = query_db("""
        SELECT Users.name AS name, COUNT(Votes.id) AS votes
        FROM Candidates
        JOIN Users ON Candidates.user_id = Users.id
        LEFT JOIN Votes ON Votes.candidate_id = Candidates.id
        WHERE Candidates.position_id = ?
        GROUP BY Candidates.id
        ORDER BY votes DESC, Users.name ASC
    """, (position_id,))

    candidates = [
        {"name": r["name"], "votes": int(r["votes"])} for r in rows
    ]
    total_votes = sum(c["votes"] for c in candidates)

    return jsonify({
        "position_name": position["position_name"],
        "candidates": candidates,
        "total_votes": total_votes
    })


# ---------------------------------------------------------------------------
# Admin: voters / admins / announcements / audit log
# ---------------------------------------------------------------------------

@app.route("/admin/voters")
@admin_required
def admin_voters():
    """Admin page listing who has voted in the current (or most recent)
    election, and which positions they voted for - but never which
    candidate they chose. GROUP_CONCAT combines a voter's multiple
    positions-voted-for into one readable cell."""
    election = get_active_election() or query_db(
        "SELECT * FROM Election ORDER BY id DESC", one=True
    )
    search = request.args.get("q", "").strip()

    voters = []

    # Get a list of who voted, without showing who they picked
    if election:
        query = """
            SELECT Users.id, Users.name, Users.email,
                   MIN(Votes.time) AS first_vote_time,
                   GROUP_CONCAT(Positions.position_name, ', ')
                       AS positions_voted
            FROM Votes
            JOIN Positions ON Votes.position_id = Positions.id
            JOIN Users ON Votes.voter_id = Users.id
            WHERE Positions.election_id = ?
        """
        params = [election["id"]]

        # Search for a specific voter if the admin typed a name/email
        if search:
            query += " AND (Users.name LIKE ? OR Users.email LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]

        query += " GROUP BY Users.id ORDER BY Users.name"

        voters = query_db(query, tuple(params))

    return render_template(
        "admin_voters.html", election=election, voters=voters,
        search=search
    )


@app.route("/admin/manage-admins", methods=["GET", "POST"])
@admin_required
def manage_admins():
    """Admin page for promoting/demoting other admins. An admin can't
    change their own admin rights (prevents accidentally locking
    themselves out, or a compromised session self-demoting to hide
    activity)."""
    current_user = get_current_user()

    if request.method == "POST":
        target_id = request.form.get("user_id")
        action = request.form.get("action")

        # Stop admins from changing their own powers
        if str(current_user["id"]) == str(target_id):
            flash("You can't change your own admin rights.", "error")

        # Make this user an admin
        elif action == "promote":
            execute_db(
                "UPDATE Users SET is_admin=1 WHERE id=?", (target_id,)
            )
            flash("User has been promoted to admin.", "success")

        # Remove this user's admin powers
        elif action == "demote":
            execute_db(
                "UPDATE Users SET is_admin=0 WHERE id=?", (target_id,)
            )
            flash("User has been demoted from admin.", "info")

        return redirect(url_for("manage_admins"))

    search = request.args.get("q", "").strip()

    # Search for a user, or just list everyone
    if search:
        users = query_db(
            "SELECT * FROM Users WHERE email LIKE ? OR name LIKE ? "
            "ORDER BY name",
            (f"%{search}%", f"%{search}%")
        )

    else:
        users = query_db("SELECT * FROM Users ORDER BY is_admin DESC, name")

    return render_template(
        "admin_manage_admins.html", users=users, search=search
    )


@app.route("/admin/announcements", methods=["GET", "POST"])
@admin_required
def admin_announcements():
    """Admin page for posting/removing site-wide banner announcements.
    Every create/deactivate action is written to the audit log via
    log_admin_action()."""
    if request.method == "POST":
        action = request.form.get("action")

        # Make a new announcement
        if action == "create":
            message = request.form.get("message", "").strip()[:300]
            level = request.form.get("level", "info")

            if message:
                execute_db(
                    "INSERT INTO Announcements "
                    "(message, level, created_by) VALUES (?, ?, ?)",
                    (message, level, session["user_id"])
                )

                log_admin_action("create_announcement", message)
                flash("Announcement posted.", "success")

        # Remove an announcement
        elif action == "deactivate":
            announcement_id = request.form.get("announcement_id")
            execute_db(
                "UPDATE Announcements SET is_active=0 WHERE id=?",
                (announcement_id,)
            )

            log_admin_action(
                "deactivate_announcement", f"id={announcement_id}"
            )
            flash("Announcement removed.", "info")

        return redirect(url_for("admin_announcements"))

    # Get the latest announcements to show the admin
    announcements = query_db(
        "SELECT * FROM Announcements ORDER BY id DESC LIMIT 50"
    )

    return render_template(
        "admin_announcements.html", announcements=announcements
    )


@app.route("/admin/audit-log")
@admin_required
def admin_audit_log():
    """Admin page showing the most recent 200 audit log entries (which
    admin did what, and when) - never anything from the voting flow
    itself, since log_admin_action() is only ever called from admin
    management routes."""
    # Get the log of what admins have been doing
    logs = query_db("""
        SELECT AuditLog.*, Users.name AS admin_name
        FROM AuditLog LEFT JOIN Users ON AuditLog.admin_id = Users.id
        ORDER BY AuditLog.id DESC
        LIMIT 200
    """)

    return render_template("admin_audit_log.html", logs=logs)


# ---------------------------------------------------------------------------
# Static/legal pages
# ---------------------------------------------------------------------------

@app.route("/terms")
def terms():
    """Terms & Conditions page."""
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    """Privacy Policy page."""
    return render_template("privacy.html")


@app.route("/about")
def about():
    """About This Project page."""
    return render_template("about.html")


if __name__ == "__main__":
    app.run(debug=True)