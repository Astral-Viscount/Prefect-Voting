/**
 * admin_results.js
 *
 * Entry point for the admin live-results page (admin_results.html).
 * Starts the turnout bar and a live (polling) bar chart for every
 * position in the current election. Relies on charts.js and
 * window.POSITION_IDS / window.API_RESULTS_BASE / window.TURNOUT_URL,
 * which are set inline by admin_results.html before this file loads.
 */
document.addEventListener("DOMContentLoaded", () => {

    render_turnout();

    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id, "bar", { api_base: window.API_RESULTS_BASE });
    });

});
