(() => {
    let audioContext = null;
    let alertInterval = null;

    const soundNotes = {
        bell: [880, 660],
        ding: [1046],
        chime: [659, 784, 1046],
    };

    const getAudioContext = async () => {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) {
            throw new Error('Audio playback is not supported in this browser.');
        }
        if (!audioContext) {
            audioContext = new AudioContextClass();
        }
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
        }
        return audioContext;
    };

    const playPattern = async (sound, volume) => {
        if (volume <= 0) {
            throw new Error('Increase the alert volume to hear this reminder.');
        }
        const context = await getAudioContext();
        const notes = soundNotes[sound] || soundNotes.bell;
        notes.forEach((frequency, index) => {
            const start = context.currentTime + index * 0.19;
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.type = sound === 'ding' ? 'sine' : 'triangle';
            oscillator.frequency.setValueAtTime(frequency, start);
            gain.gain.setValueAtTime(0.0001, start);
            gain.gain.exponentialRampToValueAtTime(Math.min(volume, 1) * 0.16, start + 0.025);
            gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.42);
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.start(start);
            oscillator.stop(start + 0.44);
        });
    };

    const settingsVolume = () => {
        const slider = document.getElementById('alert-volume');
        return slider ? Number(slider.value) : 0.5;
    };

    const settingsSound = () => document.getElementById('sound-choice')?.value || 'bell';

    document.querySelectorAll('[data-sound-preview], [data-test-alert]').forEach((button) => {
        button.addEventListener('click', async () => {
            const message = document.querySelector('[data-sound-message]');
            button.disabled = true;
            if (message) {
                message.textContent = 'Playing your alert sound...';
            }
            try {
                await playPattern(button.dataset.soundPreview || settingsSound(), settingsVolume());
                if (message) {
                    message.textContent = 'Preview played. Save your settings to use this sound for reminders.';
                }
            } catch (error) {
                if (message) {
                    message.textContent = error.message;
                }
            } finally {
                button.disabled = false;
            }
        });
    });

    const volumeSlider = document.getElementById('alert-volume');
    const volumeOutput = document.getElementById('volume-value');
    if (volumeSlider && volumeOutput) {
        const updateVolumeLabel = () => {
            volumeOutput.value = `${Math.round(Number(volumeSlider.value) * 100)}%`;
        };
        volumeSlider.addEventListener('input', updateVolumeLabel);
        updateVolumeLabel();
    }

    const startButton = document.querySelector('[data-alert-start]');
    const stopButton = document.querySelector('[data-alert-stop]');
    const alertMessage = document.querySelector('[data-alert-message]');
    if (startButton && stopButton) {
        startButton.addEventListener('click', async () => {
            startButton.disabled = true;
            if (alertMessage) {
                alertMessage.textContent = 'Starting your reminder sound...';
            }
            try {
                const sound = startButton.dataset.alertSound;
                const volume = Number(startButton.dataset.alertVolume);
                await playPattern(sound, volume);
                alertInterval = window.setInterval(() => {
                    playPattern(sound, volume).catch((error) => {
                        window.clearInterval(alertInterval);
                        alertInterval = null;
                        startButton.disabled = false;
                        stopButton.disabled = true;
                        if (alertMessage) {
                            alertMessage.textContent = error.message;
                        }
                    });
                }, 5000);
                stopButton.disabled = false;
                if (alertMessage) {
                    alertMessage.textContent = 'Reminder sound is repeating. Acknowledge it when you are ready to stop.';
                }
            } catch (error) {
                startButton.disabled = false;
                if (alertMessage) {
                    alertMessage.textContent = error.message;
                }
            }
        });

        stopButton.addEventListener('click', () => {
            if (alertInterval !== null) {
                window.clearInterval(alertInterval);
                alertInterval = null;
            }
            startButton.disabled = false;
            stopButton.disabled = true;
            if (alertMessage) {
                alertMessage.textContent = 'Reminder acknowledged. Sound stopped for this visit.';
            }
        });
    }
})();
