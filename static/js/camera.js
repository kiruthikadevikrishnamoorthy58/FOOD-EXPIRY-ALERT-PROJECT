(() => {
    const form = document.getElementById('process-scan')?.closest('form');
    const fileInput = document.getElementById('image');
    const video = document.getElementById('camera-stream');
    const preview = document.getElementById('captured-preview');
    const placeholder = document.getElementById('camera-placeholder');
    const cameraFrame = document.getElementById('camera-frame');
    const statusText = document.getElementById('camera-scan-status-text');
    const message = document.getElementById('camera-message');
    const retakeButton = document.getElementById('retake-photo');
    const processButton = document.getElementById('process-scan');
    const processLabel = document.querySelector('.scan-submit-label');
    const processingIndicator = document.getElementById('processing-indicator');
    const startCameraButton = document.getElementById('start-camera');
    const captureButton = document.getElementById('capture-photo');
    const switchCameraButton = document.getElementById('switch-camera');
    let previewUrl = null;
    let cameraStream = null;
    let facingMode = 'environment';

    if (!form || !fileInput || !preview || !placeholder || !cameraFrame
        || !statusText || !message || !retakeButton || !processButton
        || !processLabel || !processingIndicator || !video || !startCameraButton
        || !captureButton || !switchCameraButton) {
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

        stopCamera();
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

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach((track) => track.stop());
            cameraStream = null;
        }
        video.srcObject = null;
        video.hidden = true;
        captureButton.hidden = true;
        switchCameraButton.hidden = true;
        startCameraButton.hidden = false;
        startCameraButton.disabled = false;
    }

    const openCamera = async () => {
        if (!navigator.mediaDevices?.getUserMedia) {
            message.textContent = 'Live camera is unavailable here. Use Open Camera below to take or choose a photo.';
            return;
        }

        startCameraButton.disabled = true;
        message.textContent = 'Requesting camera access...';
        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: {
                    facingMode: { ideal: facingMode },
                    width: { ideal: 1920 },
                    height: { ideal: 1080 },
                },
            });
            video.srcObject = cameraStream;
            video.hidden = false;
            preview.hidden = true;
            placeholder.hidden = true;
            await video.play();
            startCameraButton.hidden = true;
            startCameraButton.disabled = false;
            captureButton.hidden = false;
            switchCameraButton.hidden = false;
            setState('ready', 'CAMERA READY · CENTER THE DATE');
            message.textContent = 'Center the printed expiry date, keep it in focus, then capture the photo.';
        } catch (error) {
            stopCamera();
            if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
                message.textContent = 'Camera permission was denied. Allow camera access in your browser, or use Open Camera below.';
            } else if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
                message.textContent = 'No camera was found. Connect a camera or use Open Camera below to choose a photo.';
            } else {
                message.textContent = 'Could not open the camera. Use HTTPS or localhost and check browser camera permissions, or choose a photo below.';
            }
        }
    };

    const capturePhoto = () => {
        if (!video.videoWidth || !video.videoHeight) {
            message.textContent = 'The camera is still starting. Wait a moment, then try again.';
            return;
        }

        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
            if (!blob) {
                message.textContent = 'The photo could not be captured. Try again or choose a photo below.';
                return;
            }
            const photo = new File([blob], `food-label-${Date.now()}.jpg`, { type: 'image/jpeg' });
            const transfer = new DataTransfer();
            transfer.items.add(photo);
            fileInput.files = transfer.files;
            fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        }, 'image/jpeg', 0.98);
    };

    fileInput.addEventListener('change', showSelectedPhoto);
    startCameraButton.addEventListener('click', openCamera);
    captureButton.addEventListener('click', capturePhoto);
    switchCameraButton.addEventListener('click', () => {
        facingMode = facingMode === 'environment' ? 'user' : 'environment';
        stopCamera();
        openCamera();
    });

    retakeButton.addEventListener('click', () => {
        fileInput.value = '';
        preview.hidden = true;
        placeholder.hidden = false;
        retakeButton.hidden = true;
        setState('idle', 'Camera off');
        message.textContent = 'Allow camera access, then hold the expiry date steady in the frame.';
        fileInput.click();
    });

    form.addEventListener('submit', () => {
        const hasPhoto = Boolean(fileInput.files?.length);
        if (!hasPhoto) {
            return;
        }

        stopCamera();
        setState('reading', 'READING PHOTO · PLEASE WAIT');
        message.textContent = 'Reading the expiry date from your photo…';
        processLabel.textContent = 'Reading date...';

        processButton.disabled = true;
        processingIndicator.hidden = false;
    });

    window.addEventListener('pagehide', () => {
        stopCamera();
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
        }
    });
})();
