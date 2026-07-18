document.getElementById('navToggle')?.addEventListener('click', function () {
    const nav = document.getElementById('siteNav');
    const isOpen = nav.classList.toggle('open');

    this.setAttribute('aria-expanded', isOpen);
});