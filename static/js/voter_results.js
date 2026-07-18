document.addEventListener("DOMContentLoaded", () => {
    (window.POSITION_IDS || []).forEach(id => {
        initLiveChart(id, "bar", { apiBase: "/voter/api/results", live: false });
    });
});