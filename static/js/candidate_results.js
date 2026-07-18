document.addEventListener("DOMContentLoaded", () => {
    (window.POSITION_IDS || []).forEach(id => {
        initLiveChart(id, "bar", { apiBase: "/candidate/api/results", live: false });
    });
});