(() => {
    const form = document.getElementById('process-scan')?.closest('form');
    const fileInput = document.getElementById('image');
    const preview = document.getElementById('captured-preview');
    const placeholder = document.getElementById('camera-placeholder');
    const cameraFrame = document.getElementById('camera-frame');
    const statusText = document.getElementById('camera-scan-status-text');
    const message = document.getElementById('camera-message');
    const retakeButton = document.getElementById('retake-photo');
    const processButton = document.getElementById('process-scan');
    const processLabel = document.querySelector('.scan-submit-label');
    const processingIndicator = document.getElementById('processing-indicator');
    let previewUrl = null;

    if (!form || !fileInput || !preview || !placeholder || !cameraFrame
        || !statusText || !message || !retakeButton || !processButton
        || !processLabel || !processingIndicator) {
        return;
    }

    const setState = (state, label) => {
        cameraFrame.classList.toggle('is-reading', state === 'reading');
        statusText.textContent = label;
    };

    const showSelectedPhoto = () => {
        const file = fileInput.files?.[0];
        if (!file) {
            return;
        }

        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
        }
        previewUrl = URL.createObjectURL(file);
        preview.src = previewUrl;
        preview.hidden = false;
        placeholder.hidden = true;
        retakeButton.hidden = false;
        setState('ready', 'PHOTO READY · REVIEW DATE');
        message.textContent = 'Photo ready. Tap “Scan date and review” to read its expiry date.';
    };

    fileInput.addEventListener('change', showSelectedPhoto);

    retakeButton.addEventListener('click', () => {
        fileInput.value = '';
        fileInput.click();
    });

    form.addEventListener('submit', () => {
        const hasPhoto = Boolean(fileInput.files?.length);
        const manualDate = document.getElementById('manual_date');
        if (!hasPhoto && !manualDate?.value) {
            return;
        }

        if (hasPhoto) {
            setState('reading', 'READING PHOTO · PLEASE WAIT');
            message.textContent = 'Reading the expiry date from your original photo…';
            processLabel.textContent = 'Reading date...';
        } else {
            processLabel.textContent = 'Preparing verification...';
        }

        processButton.disabled = true;
        processingIndicator.hidden = false;
    });

    window.addEventListener('pagehide', () => {
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
        }
    });
})();
