/**
 * login.js
 *
 * Handles the Google Identity Services callback fired after a student
 * signs in on the login page (see login.html's g_id_onload /
 * data-callback attribute, which points here by name).
 */

/**
 * Called automatically by Google's Sign-In library once the user has
 * picked an account. Sends the returned Google ID token credential to
 * the Flask backend (POST /login) for server-side verification, then
 * redirects to the dashboard on success.
 * @param {{credential: string}} response - Google Identity Services response
 */
function handle_credential_response(response) {
    fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: response.credential })
    })

    .then(async res => {
        const data = await res.json();

        if (res.ok && data.success) {
            show_toast("Signed in! Redirecting…", "success", 1200);
            // Small delay so the success toast is actually visible before
            // the page navigates away.
            setTimeout(() => window.location = "/dashboard", 600);
        } 
        else {
            // Covers both "wrong domain" (403 from the backend) and any
            // other rejected-login case.
            show_toast(data.error || "Login failed. Please try again.", "error");
            console.log(data);
        }
    })
    .catch(err => {
        // Covers network failures (server down, no internet) rather than
        // an application-level rejection.
        console.error("Network error:", err);
        show_toast("Server error. Please try again.", "error");
    });
}
