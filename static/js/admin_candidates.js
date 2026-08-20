/**
 * admin_candidates.js
 *
 * Autocomplete for the "assign a candidate" search box on
 * admin_candidates.html. As the admin types a name/email, this debounces
 * requests to /admin/api/users/search and shows a dropdown of matching
 * students, supporting mouse click and full keyboard navigation
 * (arrow keys, Enter, Escape).
 *
 * Wrapped in an IIFE so its variables (debounce_timer, active_index,
 * etc.) don't leak into the global scope and can't collide with other
 * scripts on the page.
 */
(function () {
    const input = document.getElementById('student-search');
    const dropdown = document.getElementById('student-suggestions');

    // Bail out quietly if this page doesn't have the autocomplete markup
    // (defensive - this script is only ever loaded on admin_candidates.html,
    // but this keeps it safe if that ever changes).
    if (!input || !dropdown) return;

    let debounce_timer = null;
    let active_index = -1;   // currently keyboard-highlighted suggestion, -1 = none
    let current_items = [];  // the users[] currently shown in the dropdown

    /** Hide and clear the suggestions dropdown, resetting selection state. */
    function close_dropdown() {
        dropdown.classList.add('hidden');
        dropdown.innerHTML = '';
        active_index = -1;
        current_items = [];
    }

    /**
     * Render a list of matching users into the dropdown and wire up
     * click-to-select on each one.
     * @param {{name: string, email: string}[]} users
     */
    function render_suggestions(users) {
        current_items = users;
        active_index = -1;

        if (!users.length) {
            close_dropdown();
            return;
        }

        dropdown.innerHTML = users.map((u, i) =>
            `<div class="autocomplete-item" data-index="${i}">
                <span class="autocomplete-name">${u.name}</span>
                <span class="autocomplete-email">${u.email}</span>
            </div>`
        ).join('');

        dropdown.classList.remove('hidden');

        dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', () => {
                select_user(current_items[Number(item.dataset.index)]);
            });
        });
    }

    /**
     * Fill the search box with a chosen user's email (the unambiguous
     * identifier the backend's "assign" action looks for first) and
     * close the dropdown.
     * @param {{name: string, email: string}} user
     */
    function select_user(user) {
        input.value = user.email;
        close_dropdown();
    }

    /**
     * Query the backend autocomplete API for users matching q and render
     * the results. Errors are logged rather than shown to the admin,
     * since a failed autocomplete lookup isn't critical - they can still
     * type a full email manually.
     * @param {string} q - search text (already known to be >= 2 chars)
     */
    async function fetch_suggestions(q) {
        try {
            const base = window.USER_SEARCH_URL;
            const res = await fetch(`${base}?q=${encodeURIComponent(q)}`);
            if (!res.ok) return;
            render_suggestions(await res.json());
        } catch (err) {
            console.error('User search failed:', err);
        }
    }

    /**
     * Apply the "active" highlight class to the currently
     * keyboard-selected suggestion and scroll it into view.
     * @param {NodeListOf<HTMLElement>} items
     */
    function update_active(items) {
        items.forEach((item, i) => item.classList.toggle('active', i === active_index));

        if (active_index >= 0) {
            items[active_index].scrollIntoView({ block: 'nearest' });
        }
    }

    // Debounced live search: waits 200ms after the user stops typing
    // before hitting the backend, so a fast typist doesn't fire a
    // request per keystroke. Requires at least 2 characters, matching
    // the minimum length the backend route also enforces.
    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(debounce_timer);

        if (q.length < 2) {
            close_dropdown();
            return;
        }

        debounce_timer = setTimeout(() => fetch_suggestions(q), 200);
    });

    // Full keyboard support for the dropdown: Up/Down to move the
    // highlight, Enter to pick the highlighted item, Escape to dismiss.
    input.addEventListener('keydown', (e) => {
        const items = dropdown.querySelectorAll('.autocomplete-item');
        if (!items.length || dropdown.classList.contains('hidden')) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            active_index = Math.min(active_index + 1, items.length - 1);
            update_active(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            active_index = Math.max(active_index - 1, 0);
            update_active(items);
        } else if (e.key === 'Enter' && active_index >= 0) {
            e.preventDefault();
            select_user(current_items[active_index]);
        } else if (e.key === 'Escape') {
            close_dropdown();
        }
    });

    // Clicking anywhere outside the input/dropdown closes the dropdown -
    // standard autocomplete UX.
    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target) && e.target !== input) {
            close_dropdown();
        }
    });
})();
