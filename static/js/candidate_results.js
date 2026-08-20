/**
 * candidate_results.js
 *
 * Entry point for a candidate's own closed-election results page
 * (candidate_results.html). Draws a static (non-polling) bar chart per
 * position - live=false because results for a closed election never
 * change, so there's nothing to poll for.
 */
document.addEventListener("DOMContentLoaded", () => {
    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id, "bar", { api_base: window.API_RESULTS_BASE, live: false });
    });
});
