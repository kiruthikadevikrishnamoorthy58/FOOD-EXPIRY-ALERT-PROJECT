(() => {
    const processButton = document.getElementById('process-scan');
    const form = processButton?.closest('form');
    const openButton = document.getElementById('open-camera');
    const captureButton = document.getElementById('capture-photo');
    const retakeButton = document.getElementById('retake-photo');
    const video = document.getElementById('camera-preview');
    const capturedPreview = document.getElementById('captured-preview');
    const canvas = document.getElementById('capture-canvas');
    const fileInput = document.getElementById('image');
    const message = document.getElementById('camera-message');
    const placeholder = document.getElementById('camera-placeholder');
    const zoomControls = document.getElementById('camera-zoom-controls');
    const zoomInput = document.getElementById('camera-zoom');
    const zoomValue = document.getElementById('camera-zoom-value');
    const processingIndicator = document.getElementById('processing-indicator');
    const processLabel = document.querySelector('.scan-submit-label');
    let stream = null;
    let capturedFile = null;

    if (!form || !openButton || !captureButton || !retakeButton || !video
        || !capturedPreview || !canvas || !fileInput || !message || !placeholder
        || !zoomControls || !zoomInput || !zoomValue) {
        return;
    }

    const stopCamera = () => {
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        video.srcObject = null;
    };

    const setZoom = () => {
        const zoom = Number(zoomInput.value);
        video.style.transform = `scale(${zoom})`;
        zoomValue.value = `${zoom.toFixed(1)}×`;
    };

    const openCamera = async () => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            message.textContent = 'Camera access is not available in this browser. Please upload a photo instead.';
            return;
        }

        stopCamera();
        capturedPreview.hidden = true;
        video.hidden = false;
        placeholder.hidden = true;
        captureButton.hidden = true;
        retakeButton.hidden = true;
        zoomControls.hidden = true;
        zoomInput.value = '1';
        setZoom();
        message.textContent = 'Requesting camera permission…';

        try {
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    audio: false,
                    video: {
                        facingMode: { ideal: 'environment' },
                        width: { ideal: 1920 },
                        height: { ideal: 1080 },
                    }
                });
            } catch (cameraError) {
                if (cameraError.name === 'NotFoundError'
                    || cameraError.name === 'OverconstrainedError') {
                    stream = await navigator.mediaDevices.getUserMedia({
                        audio: false,
                        video: true
                    });
                } else {
                    throw cameraError;
                }
            }
            const track = stream.getVideoTracks()[0];
            const zoomCapabilities = track.getCapabilities?.().zoom;
            if (zoomCapabilities
                && zoomCapabilities.min <= 1
                && zoomCapabilities.max >= 1) {
                try {
                    await track.applyConstraints({ advanced: [{ zoom: 1 }] });
                } catch (zoomError) {
                    console.warn('Could not set the camera hardware zoom to 1x.', zoomError);
                }
            }
            video.srcObject = stream;
            await video.play();
            captureButton.hidden = false;
            zoomControls.hidden = false;
            setZoom();
            message.textContent = 'Camera is ready. Center the expiry label and capture a clear photo.';
        } catch (cameraError) {
            stopCamera();
            video.hidden = true;
            placeholder.hidden = false;
            const messages = {
                NotAllowedError: 'Camera permission was denied. Allow camera access in your browser settings, or upload a photo.',
                NotFoundError: 'No camera was found on this device. Please upload a photo instead.',
                NotReadableError: 'The camera is busy or unavailable. Close other apps using it, or upload a photo.',
                SecurityError: 'Camera access requires HTTPS. Open this site using its secure HTTPS address.',
            };
            message.textContent = messages[cameraError.name]
                || 'Could not open the camera. Please check browser permissions or upload a photo.';
        }
    };

    openButton.addEventListener('click', openCamera);

    zoomInput.addEventListener('input', setZoom);

    captureButton.addEventListener('click', () => {
        if (!video.videoWidth || !video.videoHeight) {
            message.textContent = 'The camera is not ready yet. Please wait a moment and try again.';
            return;
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        if (!context) {
            message.textContent = 'Could not capture the image. Please upload a photo instead.';
            return;
        }
        const zoom = Number(zoomInput.value);
        const sourceWidth = video.videoWidth / zoom;
        const sourceHeight = video.videoHeight / zoom;
        context.drawImage(
            video,
            (video.videoWidth - sourceWidth) / 2,
            (video.videoHeight - sourceHeight) / 2,
            sourceWidth,
            sourceHeight,
            0,
            0,
            canvas.width,
            canvas.height,
        );
        canvas.toBlob((blob) => {
            if (!blob) {
                message.textContent = 'Could not create the photo. Please try again or upload an image.';
                return;
            }
            capturedFile = new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' });
            capturedPreview.src = URL.createObjectURL(capturedFile);
            capturedPreview.hidden = false;
            video.hidden = true;
            placeholder.hidden = true;
            captureButton.hidden = true;
            retakeButton.hidden = false;
            zoomControls.hidden = true;
            message.textContent = 'Photo captured. Process scan to read the expiry label.';
            stopCamera();
        }, 'image/jpeg', 0.92);
    });

    retakeButton.addEventListener('click', openCamera);
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            capturedFile = null;
            capturedPreview.hidden = true;
            stopCamera();
            video.hidden = true;
            placeholder.hidden = true;
            captureButton.hidden = true;
            retakeButton.hidden = true;
            zoomControls.hidden = true;
            message.textContent = `Selected ${fileInput.files[0].name}. Process scan to read it.`;
        }
    });

    form.addEventListener('submit', (event) => {
        if (!capturedFile) {
            if (!fileInput.files.length && !document.getElementById('manual_date').value) {
                return;
            }
        } else {
            event.preventDefault();
            const transfer = new DataTransfer();
            transfer.items.add(capturedFile);
            fileInput.files = transfer.files;
            form.submit();
        }

        processButton.disabled = true;
        processLabel.textContent = 'Preparing verification...';
        processingIndicator.hidden = false;
    });

    window.addEventListener('pagehide', stopCamera);
})();
