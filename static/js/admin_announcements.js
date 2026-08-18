const MESSAGE_LIMIT = 75;

function initAnnouncements() {
    document.querySelectorAll(".announcement-message").forEach((msg) => {
        const toggle = msg.nextElementSibling;

        if (!toggle || !toggle.classList.contains("message-toggle")) return;

        const fullMessage = msg.textContent.trim();
        msg.dataset.fullMessage = fullMessage;

        if (fullMessage.length > MESSAGE_LIMIT) {
            msg.textContent = fullMessage.substring(0, MESSAGE_LIMIT); 
            toggle.classList.add("visible");
        } else {
            toggle.classList.remove("visible");
        }

        // handle click
        toggle.addEventListener("click", () => {
            const expanded = msg.classList.toggle("expanded");

            if (expanded) {
                msg.textContent = fullMessage + " ";
                toggle.textContent = "Show less";
            } else {
                msg.textContent = fullMessage.substring(0, MESSAGE_LIMIT); 
                toggle.textContent = "...";
            }
        });
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAnnouncements);
} else {
    initAnnouncements();
}