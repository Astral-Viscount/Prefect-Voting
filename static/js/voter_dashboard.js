const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const positionsData = window.POSITIONS_DATA;

document.querySelectorAll('.vote-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const positionId = Number(btn.dataset.positionId);
        const candidateId = Number(btn.dataset.candidateId);
        const candidateName = btn.dataset.candidateName;

        voteFor(positionId, candidateId, candidateName);
    });
});

function findCandidate(positionId, candidateId) {
    const entry = positionsData.find(p => p.position.id === positionId);
    return entry.candidates.find(c => c.id === candidateId);
}

function showCandidateDetail(candidateId, positionId) {
    const c = findCandidate(positionId, candidateId);

    let mediaHtml = "";

    if (c.media.photo) {
        mediaHtml += `<img src="${c.media.photo}" class="candidate-photo-large">`;
    }

    if (c.media.voice) {
        mediaHtml += `<audio controls src="${c.media.voice}"></audio>`;
    }

    if (c.media.video_url) {
        mediaHtml += `
            <a href="${c.media.video_url}" target="_blank" rel="noopener">
                Watch introduction video
            </a>
        `;
    }

    document.getElementById('candidateModalContent').innerHTML = `
        <h3>${c.name}</h3>
        ${mediaHtml}
        <p>${c.bio ? c.bio.replace(/</g, "&lt;") : "No bio provided yet."}</p>
    `;

    document.getElementById('candidateModal').classList.remove('hidden');
}

function closeCandidateModal() {
    document.getElementById('candidateModal').classList.add('hidden');
}

async function voteFor(positionId, candidateId, candidateName) {
    const confirmed = await showConfirmToast(
        `Confirm your vote for ${candidateName}? This cannot be changed afterwards.`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/vote/${positionId}/${candidateId}`, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken }
        });

        let data = null;
        try { data = await res.json(); } catch {}

        if (res.ok && data?.success) {
            showToast("Vote recorded. Thank you!", "success");
            setTimeout(() => window.location.reload(), 1200);
        } 
        else if (res.status === 403) {
            showToast("Your session may have expired. Please refresh the page and try again.", "error");
        } 
        else {
            showToast(data?.error || "Something went wrong. Please refresh and try again.", "error");
        }
    } 
    catch (err) {
        console.error("Vote request failed:", err);
        showToast("Network error — please check your connection and try again.", "error");
    }
}