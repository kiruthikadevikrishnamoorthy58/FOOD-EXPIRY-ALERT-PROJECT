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

    document.addEventListener('click', (event) => {
        const backButton = event.target.closest('[data-back-fallback]');
        if (backButton) {
            const fallback = backButton.dataset.backFallback;
            let previousPageIsInternal = false;
            try {
                previousPageIsInternal = Boolean(
                    document.referrer
                    && new URL(document.referrer).origin === window.location.origin
                    && window.history.length > 1
                );
            } catch {
                previousPageIsInternal = false;
            }
            if (previousPageIsInternal) {
                window.history.back();
            } else {
                window.location.assign(fallback);
            }
        }

        const dismissButton = event.target.closest('.flash-dismiss');
        if (dismissButton) {
            dismissButton.closest('.flash').remove();
        }
    });

    document.querySelectorAll('form[data-confirm]').forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeNavigation();
            toggle.focus();
        }
    });
})();
