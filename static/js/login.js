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
            setTimeout(() => window.location = "/dashboard", 600);
        } 
        else {
            show_toast(data.error || "Login failed. Please try again.", "error");
            console.log(data);
        }
    })
    .catch(err => {
        console.error("Network error:", err);
        show_toast("Server error. Please try again.", "error");
    });
}