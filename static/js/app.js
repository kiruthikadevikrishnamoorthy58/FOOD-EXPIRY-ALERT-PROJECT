(() => {
    const toggle = document.querySelector('.nav-toggle');
    const navigation = document.getElementById('site-navigation');

    if (!toggle || !navigation) {
        return;
    }

    const closeNavigation = () => {
        navigation.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', 'Open navigation menu');
        toggle.querySelector('span').textContent = '☰';
    };

    toggle.addEventListener('click', () => {
        const isOpen = toggle.getAttribute('aria-expanded') === 'true';
        navigation.classList.toggle('is-open', !isOpen);
        toggle.setAttribute('aria-expanded', String(!isOpen));
        toggle.setAttribute('aria-label', isOpen ? 'Open navigation menu' : 'Close navigation menu');
        toggle.querySelector('span').textContent = isOpen ? '☰' : '×';
    });

    navigation.addEventListener('click', (event) => {
        if (event.target.closest('a')) {
            closeNavigation();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeNavigation();
            toggle.focus();
        }
    });
})();
