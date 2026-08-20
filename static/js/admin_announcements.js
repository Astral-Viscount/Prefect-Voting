/**
 * admin_announcements.js
 *
 * Truncates long announcement/audit-log messages to MESSAGE_LIMIT
 * characters with a "Show more"/"Show less" toggle, so the tables on
 * admin_announcements.html and admin_audit_log.html stay readable even
 * when a message is long. Shared by both pages via the same
 * .announcement-message / .message-toggle element pair pattern.
 */
const MESSAGE_LIMIT = 75;

/**
 * Find every truncatable message on the page and wire up its "Show
 * more"/"Show less" toggle button. Safe to call once the DOM is ready;
 * does nothing to messages that are already short enough to not need
 * truncating.
 */
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

// Run immediately if the DOM is already parsed (e.g. script loaded with
// defer/at the end of <body>), otherwise wait for DOMContentLoaded - this
// makes the script safe to include in different positions on different
// pages.
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAnnouncements);
} else {
    initAnnouncements();
}
