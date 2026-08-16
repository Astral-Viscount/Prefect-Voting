document.addEventListener("DOMContentLoaded", () => {

    render_turnout();

    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id, "bar", { api_base: window.API_RESULTS_BASE });
    });

});