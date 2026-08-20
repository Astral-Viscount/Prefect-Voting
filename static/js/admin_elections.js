/**
 * admin_elections.js
 *
 * Shows/hides the inline "edit election" row on admin_elections.html.
 * Each election row has a matching hidden row (#edit-row<id>) containing
 * a full edit form; clicking "Edit" reveals it in place instead of
 * navigating to a separate page, and "Cancel" hides it again without
 * submitting.
 */

document.querySelectorAll('.edit-election-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = document.getElementById(`edit-row${btn.dataset.electionId}`);
        row?.classList.remove('hidden');
    });
});

document.querySelectorAll('.cancel-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = document.getElementById(`edit-row${btn.dataset.electionId}`);
        row?.classList.add('hidden');
    });
});
