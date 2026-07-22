const SOUND_STORAGE_KEY = 'brain-games-sound-enabled';


function readSoundPreference() {
    try {
        return window.localStorage.getItem(SOUND_STORAGE_KEY) !== 'false';
    } catch (_error) {
        return true;
    }
}


export class ArcadeAudio {
    constructor(toggleButton) {
        this.toggleButton = toggleButton;
        this.enabled = readSoundPreference();
        this.context = null;
        this.updateToggle();

        if (this.toggleButton) {
            this.toggleButton.addEventListener('click', () => {
                this.enabled = !this.enabled;
                try {
                    window.localStorage.setItem(
                        SOUND_STORAGE_KEY,
                        String(this.enabled),
                    );
                } catch (_error) {
                    // Sound still works when storage is unavailable.
                }
                if (this.enabled) {
                    this.unlock();
                    this.cue('start');
                }
                this.updateToggle();
            });
        }
    }

    updateToggle() {
        if (!this.toggleButton) {
            return;
        }
        const label = this.enabled ? 'Sound on' : 'Sound off';
        this.toggleButton.setAttribute('aria-pressed', String(this.enabled));
        this.toggleButton.setAttribute('aria-label', label);
        this.toggleButton.setAttribute('title', label);
        const labelElement = this.toggleButton.querySelector(
            '[data-sound-label]',
        );
        if (labelElement) {
            labelElement.textContent = label;
        }
        this.toggleButton.dataset.sound = this.enabled ? 'on' : 'off';
    }

    unlock() {
        if (!this.enabled) {
            return null;
        }
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) {
            return null;
        }
        if (!this.context) {
            this.context = new AudioContext();
        }
        if (this.context.state === 'suspended') {
            this.context.resume();
        }
        return this.context;
    }

    tone(frequency, offset, duration, options = {}) {
        const context = this.unlock();
        if (!context || !this.enabled) {
            return;
        }
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const startsAt = context.currentTime + offset;
        const endsAt = startsAt + duration;

        oscillator.type = options.type || 'sine';
        oscillator.frequency.setValueAtTime(frequency, startsAt);
        if (options.slideTo) {
            oscillator.frequency.exponentialRampToValueAtTime(
                options.slideTo,
                endsAt,
            );
        }
        gain.gain.setValueAtTime(0.0001, startsAt);
        gain.gain.exponentialRampToValueAtTime(
            options.volume || 0.035,
            startsAt + 0.018,
        );
        gain.gain.exponentialRampToValueAtTime(0.0001, endsAt);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start(startsAt);
        oscillator.stop(endsAt + 0.02);
    }

    cue(name) {
        if (!this.enabled) {
            return;
        }
        const cues = {
            click: [
                [320, 0, 0.055, {volume: 0.018}],
            ],
            start: [
                [330, 0, 0.11, {volume: 0.028}],
                [440, 0.085, 0.14, {volume: 0.032}],
            ],
            correct: [
                [520, 0, 0.095, {volume: 0.032}],
                [680, 0.06, 0.14, {volume: 0.036}],
            ],
            wrong: [
                [190, 0, 0.16, {
                    type: 'triangle',
                    volume: 0.034,
                    slideTo: 145,
                }],
                [128, 0.09, 0.12, {volume: 0.022}],
            ],
            gameover: [
                [294, 0, 0.18, {volume: 0.026}],
                [233, 0.11, 0.2, {volume: 0.028}],
                [175, 0.22, 0.25, {volume: 0.03}],
            ],
            best: [
                [523, 0, 0.13, {volume: 0.03}],
                [659, 0.08, 0.15, {volume: 0.032}],
                [784, 0.17, 0.22, {volume: 0.036}],
            ],
        };
        (cues[name] || cues.click).forEach((note) => this.tone(...note));
    }
}
