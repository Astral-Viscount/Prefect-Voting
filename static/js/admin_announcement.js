document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".announcement-message").forEach((msg) => {
        const toggle = document.querySelector(
            `.message-toggle[data-target="${msg.id}"]`
        );

        if (!toggle) return;

        // only show the toggle if the text is overflowing
        if (msg.scrollHeight > msg.clientHeight + 1) {
            toggle.classList.add("visible");
        }

        toggle.addEventListener("click", () => {
            const expanded = msg.classList.toggle("expanded");
            toggle.textContent = expanded ? "Show less" : "Show more";
        });
    });
});