const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const positionsData = window.POSITIONS_DATA;

function findCandidate(positionId, candidateId) {
    const entry = positionsData.find(p => p.position.id === positionId);
    return entry.candidates.find(c => c.id === candidateId);
}

function showCandidateDetail(candidateId, positionId) {
    const c = findCandidate(positionId, candidateId);
    let mediaHtml = "";
    if (c.media.photo) mediaHtml += `<img src="${c.media.photo}" class="candidate-photo-large">`;
    if (c.media.voice) mediaHtml += `<audio controls src="${c.media.voice}"></audio>`;
    if (c.media.video_url) mediaHtml += `<a href="${c.media.video_url}" target="_blank" rel="noopener">Watch introduction video</a>`;

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
    if (!confirm(`Confirm your vote for ${candidateName}? This cannot be changed afterwards.`)) return;

    const res = await fetch(`/vote/${positionId}/${candidateId}`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken }
    });
    const data = await res.json();

    if (res.ok) {
        alert("Vote recorded. Thank you!");
        window.location.reload();
    } else {
        alert(data.error || "Something went wrong.");
    }
}