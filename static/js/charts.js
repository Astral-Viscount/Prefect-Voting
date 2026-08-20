/**
 * charts.js
 *
 * Shared Chart.js wrapper used by three near-identical results pages:
 * admin_results.html (live, polling), candidate_results.html and
 * voter_results.html (static, closed elections). Each page sets
 * window.API_RESULTS_BASE to the correct per-role endpoint before this
 * script runs, so the same chart code can hit different backend routes
 * depending on who is viewing it.
 *
 * Also renders the "click to enlarge" modal chart, and (for the admin
 * page only) the turnout progress bar.
 */

// Brand colour palette used for chart series, applied in order. If more
// candidates exist than colours, get_color() falls back to generating
// evenly-spaced hues so any number of candidates still get visually
// distinct colours.
const PALETTE = [
    "#004E42",
    "#00AB8E",
    "#EBC234",
    "#69C5D8",
    "#00384E",
    "#8fd6c4"
];

// chart_state[position_id] holds everything needed to (re)draw and poll
// one position's chart: { type, chart, api_base, last_data, modal_open,
// timer }.
const chart_state = {};
// Only one enlarged chart can be open in the modal at a time.
let modal_chart = null;

/**
 * Pick a colour for the i-th candidate in a chart.
 * @param {number} i - zero-based candidate index
 * @returns {string} a CSS colour string
 */
function get_color(i) {
    if (i < PALETTE.length) {
        return PALETTE[i];
    }
    const hue = (i * 137.508) % 360;
    return `hsl(${hue}, 55%, 42%)`;
}

/**
 * Fetch vote-count results for one position from the appropriate
 * role-specific API endpoint.
 * @param {number} position_id
 * @param {string} api_base - e.g. window.API_RESULTS_BASE
 * @returns {Promise<{position_name: string, candidates: {name:string, votes:number}[], total_votes: number}>}
 */
async function fetch_results(position_id, api_base) {
    const res = await fetch(`${api_base}${position_id}`);

    if (!res.ok) {
        throw new Error("Failed to load results");
    }

    return res.json();
}

/**
 * Build a Chart.js config object for either a bar or pie chart from the
 * same results payload.
 * @param {"bar"|"pie"} type
 * @param {object} data - result of fetch_results()
 * @returns {object} Chart.js configuration
 */
function build_chart_config(type, data) {
    return {
        type: type,
        data: {
            labels: data.candidates.map(c => c.name),

            datasets: [{
                label: "Votes",
                data: data.candidates.map(c => c.votes),
                backgroundColor: data.candidates.map((_, i) => get_color(i)),
                borderWidth: 1
            }]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

            plugins: {
                // Pie charts need a legend to identify slices by colour;
                // bar charts already label each bar via the x-axis.
                legend: { display: type === "pie" },
                tooltip: { enabled: true }
            },

            // Bar charts get a y-axis starting at 0 with whole-number
            // ticks (you can't have half a vote); pie charts don't use
            // axes at all.
            scales: type === "bar" ? {
                y: { beginAtZero: true, ticks: { precision: 0 } }
            } : {}
        }
    };
}

/**
 * Destroy any existing chart for a position and draw a fresh one on its
 * canvas.
 * @param {number} position_id
 * @param {"bar"|"pie"} type
 * @param {object} data - result of fetch_results()
 */
function create_chart(position_id, type, data) {
    const canvas = document.getElementById(`chart${position_id}`);
    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    if (chart_state[position_id]?.chart) {
        chart_state[position_id].chart.destroy();
    }

    chart_state[position_id].chart = new Chart(ctx, build_chart_config(type, data));
}

/**
 * Fetch the latest results for one position and redraw its chart (and
 * the enlarged modal chart, if that position's modal happens to be
 * open). Called once immediately and then on every poll interval for
 * live (admin) charts.
 * @param {number} position_id
 */
function render_chart(position_id) {
    const state = chart_state[position_id];

    fetch_results(position_id, state.api_base)
        .then(data => {
            state.last_data = data;

            create_chart(position_id, state.type, data);

            const total_el = document.getElementById(`total${position_id}`);
            if (total_el) {
                total_el.textContent = `Total votes: ${data.total_votes}`;
            }

            if (modal_chart && state.modal_open) {
                modal_chart.destroy();
                modal_chart = new Chart(
                    document.getElementById("modal-chart-canvas").getContext("2d"),
                    build_chart_config(state.type, data)
                );

                const modal_total = document.getElementById("modal-chart-total");
                if (modal_total) {
                    modal_total.textContent = `Total votes: ${data.total_votes}`;
                }
            }
        })
        .catch(err => console.error(err));
}

/**
 * Initialise a chart for one position: sets up its state, draws it
 * immediately, optionally starts polling for live updates, and makes its
 * wrapper clickable to open the enlarged modal view.
 * @param {number} position_id
 * @param {"bar"|"pie"} [default_type="bar"]
 * @param {{api_base?: string, live?: boolean, poll_ms?: number}} [options]
 *   live=true (admin results page) polls every poll_ms; live=false
 *   (candidate/voter results, which never change once an election is
 *   closed) draws once and stops.
 */
function init_live_chart(position_id, default_type = "bar", options = {}) {
    const { api_base = window.API_RESULTS_BASE, live = true, poll_ms = 5000 } = options;

    chart_state[position_id] = {
        type: default_type,
        chart: null,
        api_base: api_base,
        last_data: null,
        modal_open: false
    };

    render_chart(position_id);

    if (live) {
        chart_state[position_id].timer = setInterval(() => render_chart(position_id), poll_ms);
    }

    const wrapper = document.querySelector(`.chart-wrapper[data-position-id="${position_id}"]`);

    if (wrapper) {
        wrapper.classList.add("clickable");
        wrapper.addEventListener("click", () => open_chart_modal(position_id));
    }
}

/**
 * Switch a position's chart between bar/pie (triggered by the <select>
 * in each results card) and immediately redraw it.
 * @param {number} position_id
 * @param {"bar"|"pie"} type
 */
function set_chart_type(position_id, type) {
    chart_state[position_id].type = type;
    render_chart(position_id);
}

/**
 * Open the enlarged chart modal for one position, using the most
 * recently fetched data (does not re-fetch).
 * @param {number} position_id
 */
function open_chart_modal(position_id) {
    const state = chart_state[position_id];
    const modal = document.getElementById("chart-modal");

    if (!state || !state.last_data || !modal) return;

    // Only one position's modal_open flag should ever be true at once,
    // so render_chart() knows which (if any) modal chart to keep in sync
    // while polling.
    Object.values(chart_state).forEach(s => s.modal_open = false);
    state.modal_open = true;

    modal.classList.remove("hidden");

    if (modal_chart) {
        modal_chart.destroy();
    }

    modal_chart = new Chart(
        document.getElementById("modal-chart-canvas").getContext("2d"),
        build_chart_config(state.type, state.last_data)
    );

    const modal_total = document.getElementById("modal-chart-total");
    if (modal_total) {
        modal_total.textContent = `Total votes: ${state.last_data.total_votes}`;
    }
}

/** Close and tear down the enlarged chart modal. */
function close_chart_modal() {
    const modal = document.getElementById("chart-modal");
    if (modal) modal.classList.add("hidden");

    Object.values(chart_state).forEach(s => s.modal_open = false);

    if (modal_chart) {
        modal_chart.destroy();
        modal_chart = null;
    }
}

/**
 * Fetch and display the turnout bar (admin results page only), then
 * reschedule itself every 5 seconds - a simple self-repeating poll
 * rather than setInterval, so a slow request can't stack up overlapping
 * calls.
 */
function render_turnout() {
    fetch(window.TURNOUT_URL)
    .then(r => r.json())
    
    .then(data => {
        const pct = data.eligible ? Math.round((data.voted / data.eligible) * 100) : 0;

        const bar = document.getElementById("turnout-bar");
        const label = document.getElementById("turnout-label");

        if (bar) bar.style.width = `${pct}%`;

        if (label) label.textContent = `${data.voted} / ${data.eligible} logged-in accounts have voted (${pct}%)`;
    });

    setTimeout(render_turnout, 5000);
}
