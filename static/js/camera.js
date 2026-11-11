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
    const cameraFrame = video?.closest('.camera-frame');
    const cameraStatusText = document.getElementById('camera-scan-status-text');
    const processingIndicator = document.getElementById('processing-indicator');
    const processLabel = document.querySelector('.scan-submit-label');
    let stream = null;
    let capturedFile = null;

    if (!form || !openButton || !captureButton || !retakeButton || !video
        || !capturedPreview || !canvas || !fileInput || !message || !placeholder
        || !zoomControls || !zoomInput || !zoomValue || !cameraFrame || !cameraStatusText) {
        return;
    }

    const setCameraState = (state, label) => {
        cameraFrame.classList.toggle('is-live', state === 'live');
        cameraFrame.classList.toggle('is-reading', state === 'reading');
        cameraStatusText.textContent = label;
    };

    const stopCamera = () => {
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        video.srcObject = null;
        if (!cameraFrame.classList.contains('is-reading')) {
            setCameraState('off', 'Camera off');
        }
    };

    const setZoom = () => {
        const zoom = Number(zoomInput.value);
        video.style.transform = `scale(${zoom})`;
        zoomValue.value = `${zoom.toFixed(1)}×`;
    };

    const focusCamera = async () => {
        const track = stream?.getVideoTracks()[0];
        const focusModes = track?.getCapabilities?.().focusMode || [];
        try {
            if (focusModes.includes('single-shot')) {
                await track.applyConstraints({ advanced: [{ focusMode: 'single-shot' }] });
            } else if (focusModes.includes('continuous')) {
                await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
            }
        } catch (focusError) {
            console.warn('Camera autofocus adjustment was not available.', focusError);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
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
        setCameraState('off', 'Requesting camera');
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
            const focusModes = track.getCapabilities?.().focusMode || [];
            if (focusModes.includes('continuous')) {
                try {
                    await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
                } catch (focusError) {
                    console.warn('Could not enable continuous camera autofocus.', focusError);
                }
            }
            video.srcObject = stream;
            await video.play();
            captureButton.hidden = false;
            zoomControls.hidden = false;
            setZoom();
            setCameraState('live', 'CAMERA LIVE · ALIGN DATE');
            message.textContent = focusModes.length
                ? 'Autofocus is on. Tap the date in the preview, wait for focus, then capture.'
                : 'Center the date in the preview, hold the camera steady, then capture.';
        } catch (cameraError) {
            stopCamera();
            setCameraState('off', 'Camera unavailable');
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

    video.addEventListener('click', () => {
        focusCamera().then(() => {
            message.textContent = 'Focused. Capture the date when it looks sharp.';
        });
    });

    captureButton.addEventListener('click', async () => {
        if (!video.videoWidth || !video.videoHeight) {
            message.textContent = 'The camera is not ready yet. Please wait a moment and try again.';
            return;
        }
        captureButton.disabled = true;
        message.textContent = 'Focusing camera… hold still.';
        await focusCamera();
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        if (!context) {
            captureButton.disabled = false;
            message.textContent = 'Could not capture the image. Please upload a photo instead.';
            setCameraState('live', 'CAMERA LIVE · ALIGN DATE');
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
                captureButton.disabled = false;
                message.textContent = 'Could not create the photo. Please try again or upload an image.';
                setCameraState('live', 'CAMERA LIVE · ALIGN DATE');
                return;
            }
            capturedFile = new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' });
            capturedPreview.src = URL.createObjectURL(capturedFile);
            capturedPreview.hidden = false;
            video.hidden = true;
            placeholder.hidden = true;
            captureButton.hidden = true;
            captureButton.disabled = false;
            retakeButton.hidden = false;
            zoomControls.hidden = true;
            stopCamera();
            setCameraState('off', 'PHOTO READY · TAP SCAN DATE');
            message.textContent = 'Photo captured. Process scan to read the expiry label.';
        }, 'image/jpeg', 0.92);
    });

    retakeButton.addEventListener('click', openCamera);
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            capturedFile = null;
            capturedPreview.src = URL.createObjectURL(fileInput.files[0]);
            capturedPreview.hidden = true;
            stopCamera();
            video.hidden = true;
            capturedPreview.hidden = false;
            placeholder.hidden = true;
            captureButton.hidden = true;
            retakeButton.hidden = true;
            zoomControls.hidden = true;
            setCameraState('off', 'PHOTO READY · TAP SCAN DATE');
            message.textContent = `Selected ${fileInput.files[0].name}. Process scan to read it.`;
        }
    });

    form.addEventListener('submit', (event) => {
        if (!capturedFile) {
            if (!fileInput.files.length && !document.getElementById('manual_date').value) {
                return;
            }
        } else {
            const transfer = new DataTransfer();
            transfer.items.add(capturedFile);
            fileInput.files = transfer.files;
        }

        if (fileInput.files.length) {
            setCameraState('reading', 'READING PHOTO · PLEASE WAIT');
            message.textContent = 'Reading the expiry date from your photo…';
            processLabel.textContent = 'Reading date...';
        } else {
            processLabel.textContent = 'Preparing verification...';
        }

        processButton.disabled = true;
        processingIndicator.hidden = false;
    });

    window.addEventListener('pagehide', stopCamera);
})();
