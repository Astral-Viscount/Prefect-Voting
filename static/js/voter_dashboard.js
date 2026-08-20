/**
 * voter_dashboard.js
 *
 * Powers the voter dashboard (voter_dashboard.html): the "Learn More"
 * candidate detail modal, and the vote-casting flow including a confirm
 * step (via show_confirm_toast from layout.js) since a vote cannot be
 * changed once cast.
 *
 * Relies on two globals set inline by voter_dashboard.html:
 *   window.POSITIONS_DATA - the full positions/candidates data structure
 *       the server already rendered, reused here instead of re-fetching
 *   window.VOTE_URL_BASE  - the /vote/0/0 URL pattern to substitute real
 *       ids into
 */

const csrf_token = document.querySelector('meta[name="csrf-token"]').content;
const positions_data = window.POSITIONS_DATA;

// Wire up every "Vote" button on the page.
document.querySelectorAll('.vote-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const position_id = Number(btn.dataset.positionId);
        const candidate_id = Number(btn.dataset.candidateId);
        const candidate_name = btn.dataset.candidateName;

        vote_for(position_id, candidate_id, candidate_name);
    });
});

// Wire up every "Learn More" button on the page.
document.querySelectorAll('.btn.outline').forEach(btn => {
    btn.addEventListener('click', () => {
        const position_id = Number(btn.dataset.positionId);
        const candidate_id = Number(btn.dataset.candidateId);
        
        show_candidate_detail(candidate_id, position_id);
    });
});

// Clicking the dark overlay (but not the modal box itself) closes the
// candidate detail modal.
document.getElementById('candidate-modal')
    .addEventListener('click', (event) => {
        if (event.target.id === 'candidate-modal') {
            close_candidate_modal();
        }
});

/**
 * Look up one candidate's data from the already-rendered
 * window.POSITIONS_DATA, avoiding a network round-trip for something the
 * server already sent down with the page.
 * @param {number} position_id
 * @param {number} candidate_id
 * @returns {object} the candidate entry (id, name, bio, media)
 */
function find_candidate(position_id, candidate_id) {
    const entry = positions_data.find(p => p.position.id === position_id);
    return entry.candidates.find(c => c.id === candidate_id);
}

/**
 * Build and show the "Learn More" modal for one candidate: photo, bio,
 * voice clip and/or intro video link, whichever are present.
 * @param {number} candidate_id
 * @param {number} position_id
 */
function show_candidate_detail(candidate_id, position_id) {
    const candi = find_candidate(position_id, candidate_id);

    const photo_html = candi.media.photo
        ? `<img src="${candi.media.photo}" class="candidate-photo-large">`
        : "";

    const voice_html = candi.media.voice
        ? `<audio controls src="${candi.media.voice}"></audio>`
        : "";

    const video_html = candi.media.video_url
        ? `<a href="${candi.media.video_url}" target="_blank" rel="noopener"
               class="btn outline small" style="margin-top:12px;display:inline-block;">
               Watch introduction video
           </a>`
        : "";

    // The bio is user-submitted free text, so "<" is escaped to "&lt;"
    // before inserting it as HTML - a minimal but effective guard against
    // a candidate's bio breaking the modal layout with stray markup.
    document.getElementById('candidate-modal-content').innerHTML = `
        <h3>${candi.name}</h3>
        ${photo_html}
        <p>${candi.bio ? candi.bio.replace(/</g, "&lt;") : "No bio provided yet."}</p>
        ${voice_html}
        ${video_html}
    `;

    document.getElementById('candidate-modal').classList.remove('hidden');
}

/** Hide the candidate detail modal. */
function close_candidate_modal() {
    document.getElementById('candidate-modal').classList.add('hidden');
}

/**
 * Substitute real position/candidate ids into the server-provided
 * /vote/0/0 URL template.
 * @param {number} position_id
 * @param {number} candidate_id
 * @returns {string} the real vote endpoint URL, e.g. /vote/3/12
 */
function build_vote_url(position_id, candidate_id) {
    return window.VOTE_URL_BASE.replace('/0/0', `/${position_id}/${candidate_id}`);
}

/**
 * Confirm with the voter, then POST a vote to the backend and reload the
 * page on success so the dashboard reflects the new "already voted"
 * state. Handles the three outcomes the backend can return: success,
 * expired/invalid session (403), and any other rejection (already voted,
 * voting closed, etc).
 * @param {number} position_id
 * @param {number} candidate_id
 * @param {string} candidate_name - shown in the confirm prompt
 */
async function vote_for(position_id, candidate_id, candidate_name) {
    const confirmed = await show_confirm_toast(
        `Confirm your vote for ${candidate_name}? This cannot be changed afterwards.`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(build_vote_url(position_id, candidate_id), {
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
