document.querySelectorAll('.edit-election-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = document.getElementById(`edit-row-${btn.dataset.electionId}`);
        row?.classList.remove('hidden');
    });
});

document.querySelectorAll('.cancel-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = document.getElementById(`edit-row-${btn.dataset.electionId}`);
        row?.classList.add('hidden');
    });
});