function handleCredentialResponse(response) {

    fetch("/login", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            credential: response.credential
        })
    })
    .then(async res => {

        const data = await res.json();

        if (res.ok && data.success) {
            window.location = "/dashboard";
        } else {
            alert(data.error || "Login failed. Please try again.");
            console.log(data);
        }

    })
    .catch(err => {
        console.error("Network error:", err);
        alert("Server error. Check console.");
    });

    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken, "Content-Type": "application/json" },
    body: JSON.stringify(payload)
    });

}