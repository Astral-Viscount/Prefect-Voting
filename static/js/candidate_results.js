document.addEventListener("DOMContentLoaded", () => {
    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id, "bar", { api_base: "/candidate/api/results", live: false });
    });
});