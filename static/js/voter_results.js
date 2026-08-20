/**
 * voter_results.js
 *
 * Entry point for a voter's own closed-election results page
 * (voter_results.html). Draws a static (non-polling) bar chart per
 * position - identical pattern to candidate_results.js, just pointed at
 * the voter-specific API endpoint via window.API_RESULTS_BASE.
 */
document.addEventListener("DOMContentLoaded", () => {
    (window.POSITION_IDS || []).forEach(id => {
        init_live_chart(id, "bar", { api_base: window.API_RESULTS_BASE, live: false });
    });
});
