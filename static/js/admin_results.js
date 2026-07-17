document.addEventListener("DOMContentLoaded", () => {

    renderTurnout();

    (window.POSITION_IDS || []).forEach(id => {
        initLiveChart(id);
    });

});