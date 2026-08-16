const PALETTE = [
    "#004E42",
    "#00AB8E",
    "#EBC234",
    "#69C5D8",
    "#00384E",
    "#8fd6c4"
];

const chart_state = {};
let modal_chart = null;

function get_color(i) {
    if (i < PALETTE.length) {
        return PALETTE[i];
    }
    const hue = (i * 137.508) % 360;
    return `hsl(${hue}, 55%, 42%)`;
}

async function fetch_results(position_id, api_base) {
    const res = await fetch(`${api_base}${position_id}`);

    if (!res.ok) {
        throw new Error("Failed to load results");
    }

    return res.json();
}

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
                legend: { display: type === "pie" },
                tooltip: { enabled: true }
            },

            scales: type === "bar" ? {
                y: { beginAtZero: true, ticks: { precision: 0 } }
            } : {}
        }
    };
}

function create_chart(position_id, type, data) {
    const canvas = document.getElementById(`chart${position_id}`);
    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    if (chart_state[position_id]?.chart) {
        chart_state[position_id].chart.destroy();
    }

    chart_state[position_id].chart = new Chart(ctx, build_chart_config(type, data));
}

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

function set_chart_type(position_id, type) {
    chart_state[position_id].type = type;
    render_chart(position_id);
}

function open_chart_modal(position_id) {
    const state = chart_state[position_id];
    const modal = document.getElementById("chart-modal");

    if (!state || !state.last_data || !modal) return;

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

function close_chart_modal() {
    const modal = document.getElementById("chart-modal");
    if (modal) modal.classList.add("hidden");

    Object.values(chart_state).forEach(s => s.modal_open = false);

    if (modal_chart) {
        modal_chart.destroy();
        modal_chart = null;
    }
}

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