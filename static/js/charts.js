const PALETTE = [
    "#004E42",
    "#00AB8E",
    "#EBC234",
    "#69C5D8",
    "#00384E",
    "#8fd6c4"
];

const chartState = {};
let modalChart = null;

function getColor(i) {
    if (i < PALETTE.length) {
        return PALETTE[i];
    }
    const hue = (i * 137.508) % 360;
    return `hsl(${hue}, 55%, 42%)`;
}

async function fetchResults(positionId, apiBase = "/admin/api/results") {
    const res = await fetch(`${apiBase}/${positionId}`);

    if (!res.ok) {
        throw new Error("Failed to load results");
    }

    return res.json();
}

function buildChartConfig(type, data) {
    return {
        type: type,
        data: {
            labels: data.candidates.map(c => c.name),

            datasets: [{
                label: "Votes",
                data: data.candidates.map(c => c.votes),
                backgroundColor: data.candidates.map((_, i) => getColor(i)),
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

function createChart(positionId, type, data) {
    const canvas = document.getElementById(`chart-${positionId}`);
    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    if (chartState[positionId]?.chart) {
        chartState[positionId].chart.destroy();
    }

    chartState[positionId].chart = new Chart(ctx, buildChartConfig(type, data));
}

function renderChart(positionId) {
    const state = chartState[positionId];

    fetchResults(positionId, state.apiBase)
        .then(data => {
            state.lastData = data;

            createChart(positionId, state.type, data);

            const totalEl = document.getElementById(`total-${positionId}`);
            if (totalEl) {
                totalEl.textContent = `Total votes: ${data.total_votes}`;
            }

            if (modalChart && state.modalOpen) {
                modalChart.destroy();
                modalChart = new Chart(
                    document.getElementById("modalChartCanvas").getContext("2d"),
                    buildChartConfig(state.type, data)
                );

                const modalTotal = document.getElementById("modalChartTotal");
                if (modalTotal) {
                    modalTotal.textContent = `Total votes: ${data.total_votes}`;
                }
            }
        })
        .catch(err => console.error(err));
}

function initLiveChart(positionId, defaultType = "bar", options = {}) {
    const { apiBase = "/admin/api/results", live = true, pollMs = 5000 } = options;

    chartState[positionId] = {
        type: defaultType,
        chart: null,
        apiBase: apiBase,
        lastData: null,
        modalOpen: false
    };

    renderChart(positionId);

    if (live) {
        chartState[positionId].timer = setInterval(() => renderChart(positionId), pollMs);
    }

    const wrapper = document.querySelector(`.chart-wrapper[data-position-id="${positionId}"]`);

    if (wrapper) {
        wrapper.classList.add("clickable");
        wrapper.addEventListener("click", () => openChartModal(positionId));
    }
}

function setChartType(positionId, type) {
    chartState[positionId].type = type;
    renderChart(positionId);
}

function openChartModal(positionId) {
    const state = chartState[positionId];
    const modal = document.getElementById("chartModal");

    if (!state || !state.lastData || !modal) return;

    Object.values(chartState).forEach(s => s.modalOpen = false);
    state.modalOpen = true;

    modal.classList.remove("hidden");

    if (modalChart) {
        modalChart.destroy();
    }

    modalChart = new Chart(
        document.getElementById("modalChartCanvas").getContext("2d"),
        buildChartConfig(state.type, state.lastData)
    );

    const modalTotal = document.getElementById("modalChartTotal");
    if (modalTotal) {
        modalTotal.textContent = `Total votes: ${state.lastData.total_votes}`;
    }
}

function closeChartModal() {
    const modal = document.getElementById("chartModal");
    if (modal) modal.classList.add("hidden");

    Object.values(chartState).forEach(s => s.modalOpen = false);

    if (modalChart) {
        modalChart.destroy();
        modalChart = null;
    }
}

function renderTurnout() {
    fetch("/admin/api/turnout")
    .then(r => r.json())
    
    .then(data => {
        const pct = data.eligible ? Math.round((data.voted / data.eligible) * 100) : 0;

        const bar = document.getElementById("turnout-bar");
        const label = document.getElementById("turnout-label");

        if (bar) bar.style.width = `${pct}%`;

        if (label) label.textContent = `${data.voted} / ${data.eligible} logged-in accounts have voted (${pct}%)`;
    });

    setTimeout(renderTurnout, 5000);
}