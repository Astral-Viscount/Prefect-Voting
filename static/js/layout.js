/**
 * layout.js
 *
 * Site-wide behaviour loaded on every page via layout.html:
 *   - the mobile hamburger nav toggle
 *   - a small toast notification system (info/success/error banners that
 *     slide in bottom-right and auto-dismiss)
 *   - a toast-based confirm dialog, used to replace the browser's blocking
 *     window.confirm() with something that matches the site's styling
 *   - automatically wires up any <form data-confirm="..."> to show that
 *     confirm dialog before submitting (used for destructive actions like
 *     "Remove candidate")
 */

// Toggle the mobile navigation menu open/closed and keep the button's
// aria-expanded attribute in sync for screen readers.
document.getElementById('nav-toggle')?.addEventListener('click', function () {
    const nav = document.getElementById('site-nav');
    const is_open = nav.classList.toggle('open');

    this.setAttribute('aria-expanded', is_open);
});

/**
 * Get (creating if necessary) the fixed-position container that toasts
 * are appended to.
 * @returns {HTMLElement} the #toast-container element
 */
function ensure_toast_container() {
    let container = document.getElementById('toast-container');

    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    return container;
}

/**
 * Fade a toast out and remove it from the DOM once the CSS transition
 * finishes, rather than deleting it immediately (which would cause it to
 * disappear with a visible jump).
 * @param {HTMLElement} toast
 */
function remove_toast(toast) {
    toast.classList.remove('toast-visible');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
}

/**
 * Show a simple auto-dismissing toast notification.
 * @param {string} message - text to display
 * @param {string} [type="info"] - "info" | "success" | "error", controls colour
 * @param {number} [duration=4000] - ms before auto-dismiss; pass 0 to disable
 */
function show_toast(message, type = "info", duration = 4000) {
    const container = ensure_toast_container();
    const toast = document.createElement('div');

    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.addEventListener('click', () => remove_toast(toast));

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-visible'));

    if (duration) {
        setTimeout(() => remove_toast(toast), duration);
    }
}

/**
 * Show a toast with Cancel/Confirm buttons and resolve a Promise<boolean>
 * once the user picks one. This is the app's replacement for the native,
 * blocking window.confirm() dialog.
 * @param {string} message - question to ask the user
 * @returns {Promise<boolean>} resolves true if confirmed, false if cancelled
 */
function show_confirm_toast(message) {
    return new Promise(resolve => {
        const container = ensure_toast_container();
        const toast = document.createElement('div');
        toast.className = 'toast toast-confirm';

        const text = document.createElement('p');
        text.className = 'toast-message';
        text.textContent = message;

        const actions = document.createElement('div');
        actions.className = 'toast-actions';

        const cancel_btn = document.createElement('button');
        cancel_btn.type = 'button';
        cancel_btn.className = 'btn outline small';
        cancel_btn.textContent = 'Cancel';

        const confirm_btn = document.createElement('button');
        confirm_btn.type = 'button';
        confirm_btn.className = 'btn danger small';
        confirm_btn.textContent = 'Confirm';

        const finish = (result) => {
            remove_toast(toast);
            resolve(result);
        };

        cancel_btn.addEventListener('click', () => finish(false));
        confirm_btn.addEventListener('click', () => finish(true));

        actions.append(cancel_btn, confirm_btn);
        toast.append(text, actions);
        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('toast-visible'));
    });
}

// Intercept the submit of any form marked data-confirm="..." so that a
// confirm toast is shown first. form.dataset.confirmed guards against an
// infinite loop: once the user confirms, the form is re-submitted with
// that flag set, and this listener lets it through on the second pass.
document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', async (e) => {
        if (form.dataset.confirmed === "true") return;

        e.preventDefault();
        const ok = await show_confirm_toast(form.dataset.confirm);

        if (ok) {
            form.dataset.confirmed = "true";
            form.requestSubmit ? form.requestSubmit() : form.submit();
        }
    });
});
