(function () {
    const input = document.getElementById('student-search');
    const dropdown = document.getElementById('student-suggestions');

    if (!input || !dropdown) return;

    let debounce_timer = null;
    let active_index = -1;
    let current_items = [];

    function close_dropdown() {
        dropdown.classList.add('hidden');
        dropdown.innerHTML = '';
        active_index = -1;
        current_items = [];
    }

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

    function select_user(user) {
        input.value = user.email;
        close_dropdown();
    }

    async function fetch_suggestions(q) {
        try {
            const res = await fetch(`/admin/api/users/search?q=${encodeURIComponent(q)}`);
            if (!res.ok) return;
            render_suggestions(await res.json());
        } catch (err) {
            console.error('User search failed:', err);
        }
    }

    function update_active(items) {
        items.forEach((item, i) => item.classList.toggle('active', i === active_index));

        if (active_index >= 0) {
            items[active_index].scrollIntoView({ block: 'nearest' });
        }
    }

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(debounce_timer);

        if (q.length < 2) {
            close_dropdown();
            return;
        }

        debounce_timer = setTimeout(() => fetch_suggestions(q), 200);
    });

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

    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target) && e.target !== input) {
            close_dropdown();
        }
    });
})();