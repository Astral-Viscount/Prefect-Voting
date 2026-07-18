document.getElementById('navToggle')?.addEventListener('click', function () {
    const nav = document.getElementById('siteNav');
    const isOpen = nav.classList.toggle('open');

    this.setAttribute('aria-expanded', isOpen);
});

function ensureToastContainer() {
    let container = document.getElementById('toastContainer');

    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    return container;
}

function removeToast(toast) {
    toast.classList.remove('toast-visible');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
}

function showToast(message, type = "info", duration = 4000) {
    const container = ensureToastContainer();
    const toast = document.createElement('div');

    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.addEventListener('click', () => removeToast(toast));

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-visible'));

    if (duration) {
        setTimeout(() => removeToast(toast), duration);
    }
}

function showConfirmToast(message) {
    return new Promise(resolve => {
        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = 'toast toast-confirm';

        const text = document.createElement('p');
        text.className = 'toast-message';
        text.textContent = message;

        const actions = document.createElement('div');
        actions.className = 'toast-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn outline small';
        cancelBtn.textContent = 'Cancel';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'btn danger small';
        confirmBtn.textContent = 'Confirm';

        const finish = (result) => {
            removeToast(toast);
            resolve(result);
        };

        cancelBtn.addEventListener('click', () => finish(false));
        confirmBtn.addEventListener('click', () => finish(true));

        actions.append(cancelBtn, confirmBtn);
        toast.append(text, actions);
        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('toast-visible'));
    });
}

document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', async (e) => {
        if (form.dataset.confirmed === "true") return;

        e.preventDefault();
        const ok = await showConfirmToast(form.dataset.confirm);

        if (ok) {
            form.dataset.confirmed = "true";
            form.requestSubmit ? form.requestSubmit() : form.submit();
        }
    });
});