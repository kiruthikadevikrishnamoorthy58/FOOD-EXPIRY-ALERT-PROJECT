(() => {
    const form = document.querySelector('.form-card form');
    const openButton = document.getElementById('open-camera');
    const captureButton = document.getElementById('capture-photo');
    const retakeButton = document.getElementById('retake-photo');
    const video = document.getElementById('camera-preview');
    const capturedPreview = document.getElementById('captured-preview');
    const canvas = document.getElementById('capture-canvas');
    const fileInput = document.getElementById('image');
    const message = document.getElementById('camera-message');
    let stream = null;
    let capturedFile = null;

    if (!form || !openButton || !captureButton || !retakeButton || !video
        || !capturedPreview || !canvas || !fileInput || !message) {
        return;
    }

    const stopCamera = () => {
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        video.srcObject = null;
    };

    const openCamera = async () => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            message.textContent = 'Camera access is not available in this browser. Please upload a photo instead.';
            return;
        }

        stopCamera();
        capturedPreview.hidden = true;
        video.hidden = false;
        captureButton.hidden = true;
        retakeButton.hidden = true;
        message.textContent = 'Requesting camera permission…';

        try {
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    audio: false,
                    video: { facingMode: { ideal: 'environment' } }
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
            video.srcObject = stream;
            await video.play();
            captureButton.hidden = false;
            message.textContent = 'Camera is ready. Center the expiry label and capture a clear photo.';
        } catch (cameraError) {
            stopCamera();
            video.hidden = true;
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
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
            if (!blob) {
                message.textContent = 'Could not create the photo. Please try again or upload an image.';
                return;
            }
            capturedFile = new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' });
            capturedPreview.src = URL.createObjectURL(capturedFile);
            capturedPreview.hidden = false;
            video.hidden = true;
            captureButton.hidden = true;
            retakeButton.hidden = false;
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
            captureButton.hidden = true;
            retakeButton.hidden = true;
            message.textContent = `Selected ${fileInput.files[0].name}. Process scan to read it.`;
        }
    });

    form.addEventListener('submit', (event) => {
        if (!capturedFile) {
            return;
        }
        event.preventDefault();
        const transfer = new DataTransfer();
        transfer.items.add(capturedFile);
        fileInput.files = transfer.files;
        form.submit();
    });

    window.addEventListener('pagehide', stopCamera);
})();
