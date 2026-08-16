document.addEventListener("DOMContentLoaded", () => {

    render_turnout();

    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id);
    });

});