const csrf_token = document.querySelector('meta[name="csrf-token"]').content;
const positions_data = window.POSITIONS_DATA;

document.querySelectorAll('.vote-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const position_id = Number(btn.dataset.positionId);
        const candidate_id = Number(btn.dataset.candidateId);
        const candidate_name = btn.dataset.candidateName;

        vote_for(position_id, candidate_id, candidate_name);
    });
});

document.querySelectorAll('.btn.outline').forEach(btn => {
    btn.addEventListener('click', () => {
        const position_id = Number(btn.dataset.positionId);
        const candidate_id = Number(btn.dataset.candidateId);
        
        show_candidate_detail(candidate_id, position_id);
    });
});

document.getElementById('candidate-modal')
    .addEventListener('click', (event) => {
        if (event.target.id === 'candidate-modal') {
            close_candidate_modal();
        }
});

function find_candidate(position_id, candidate_id) {
    const entry = positions_data.find(p => p.position.id === position_id);
    return entry.candidates.find(c => c.id === candidate_id);
}

function show_candidate_detail(candidate_id, position_id) {
    const c = find_candidate(position_id, candidate_id);

    let media_html = "";

    if (c.media.photo) {
        media_html += `<img src="${c.media.photo}" class="candidate-photo-large">`;
    }

    if (c.media.voice) {
        media_html += `<audio controls src="${c.media.voice}"></audio>`;
    }

    if (c.media.video_url) {
        media_html += `
            <a href="${c.media.video_url}" target="_blank" rel="noopener">
                Watch introduction video
            </a>
        `;
    }

    document.getElementById('candidate-modal-content').innerHTML = `
        <h3>${c.name}</h3>
        ${media_html}
        <p>${c.bio ? c.bio.replace(/</g, "&lt;") : "No bio provided yet."}</p>
    `;

    document.getElementById('candidate-modal').classList.remove('hidden');
}

function close_candidate_modal() {
    document.getElementById('candidate-modal').classList.add('hidden');
}

async function vote_for(position_id, candidate_id, candidate_name) {
    const confirmed = await show_confirm_toast(
        `Confirm your vote for ${candidate_name}? This cannot be changed afterwards.`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/vote/${position_id}/${candidate_id}`, {
            method: "POST",
            headers: { "X-CSRFToken": csrf_token }
        });

        let data = null;
        try { data = await res.json(); } catch {}

        if (res.ok && data?.success) {
            show_toast("Vote recorded. Thank you!", "success");
            setTimeout(() => window.location.reload(), 1200);
        } 
        else if (res.status === 403) {
            show_toast("Your session may have expired. Please refresh the page and try again.", "error");
        } 
        else {
            show_toast(data?.error || "Something went wrong. Please refresh and try again.", "error");
        }
    } 
    catch (err) {
        console.error("Vote request failed:", err);
        show_toast("Network error — please check your connection and try again.", "error");
    }
}