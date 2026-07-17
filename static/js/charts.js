const PALETTE = [
    "#004E42",
    "#00AB8E",
    "#EBC234",
    "#69C5D8",
    "#00384E",
    "#8fd6c4"
];

const chartState = {};

async function fetchResults(positionId) {
    const res = await fetch(`/admin/api/results/${positionId}`);

    if (!res.ok) {
        throw new Error("Failed to load results");
    }

    return res.json();
}


function createChart(positionId, type, data) {
    const canvas = document.getElementById(`chart-${positionId}`);

    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    if (chartState[positionId]?.chart) {
        chartState[positionId].chart.destroy();
    }

    chartState[positionId].chart = new Chart(ctx, {
        type: type,

        data: {
            labels: data.candidates.map(c => c.name),

            datasets: [{
                label: "Votes",

                data: data.candidates.map(c => c.votes),

                backgroundColor: data.candidates.map(
                    (_, i) => PALETTE[i % PALETTE.length]
                ),

                borderWidth: 1
            }]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

            plugins: {
                legend: {
                    display: type === "pie"
                },
                tooltip: {
                    enabled: true
                }
            },

            scales: type === "bar" ? {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0
                    }
                }

            } : {}

        }
    });
}

function renderChart(positionId) {

    fetchResults(positionId)
        .then(data => {
            const type = chartState[positionId].type;

            createChart(
                positionId,
                type,
                data
            );
            
            document.getElementById(
                `total-${positionId}`
            ).textContent =
            
                `Total votes: ${data.total_votes}`;
        })

        .catch(err =>
            console.error(err)
        );
}

function initLiveChart(positionId, defaultType="bar") {

    chartState[positionId] = {
        type: defaultType,
        chart: null
    };

    renderChart(positionId);

    chartState[positionId].timer =
        setInterval(
            () => renderChart(positionId),
            5000
        );
}

function setChartType(positionId, type) {
    chartState[positionId].type = type;
    renderChart(positionId);
}

function renderTurnout() {
    fetch("/admin/api/turnout")
    .then(r => r.json())
    .then(data => {

        const pct =
            data.eligible
            ? Math.round(
                (data.voted / data.eligible) * 100
              )
            : 0;

        const bar =
            document.getElementById("turnout-bar");

        const label =
            document.getElementById("turnout-label");

        if (bar)
            bar.style.width = `${pct}%`;

        if(label)
            label.textContent =
            `${data.voted} / ${data.eligible} logged-in accounts have voted (${pct}%)`;
    });

    setTimeout(renderTurnout,5000);
}