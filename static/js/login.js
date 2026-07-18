function handleCredentialResponse(response) {
    fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: response.credential })
    })

    .then(async res => {
        const data = await res.json();

        if (res.ok && data.success) {
            showToast("Signed in! Redirecting…", "success", 1200);
            setTimeout(() => window.location = "/dashboard", 600);
        } 
        else {
            showToast(data.error || "Login failed. Please try again.", "error");
            console.log(data);
        }
    })
    .catch(err => {
        console.error("Network error:", err);
        showToast("Server error. Please try again.", "error");
    });
}