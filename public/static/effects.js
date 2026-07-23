export class ArcadeEffects {
    constructor(canvas) {
        this.canvas = canvas;
        this.context = canvas ? canvas.getContext('2d') : null;
        this.particles = [];
        this.frame = null;
        this.reducedMotion = window.matchMedia(
            '(prefers-reduced-motion: reduce)',
        ).matches;
        this.resize = this.resize.bind(this);
        this.draw = this.draw.bind(this);

        if (this.canvas && this.context) {
            window.addEventListener('resize', this.resize, {passive: true});
            this.resize();
        }
    }

    resize() {
        if (!this.canvas || !this.context) {
            return;
        }
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = Math.floor(window.innerWidth * ratio);
        this.canvas.height = Math.floor(window.innerHeight * ratio);
        this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    burst(color = '#63E6BE', count = 26, origin = null) {
        if (!this.context || this.reducedMotion) {
            return;
        }
        const x = origin?.x ?? window.innerWidth / 2;
        const y = origin?.y ?? window.innerHeight * 0.42;

        for (let index = 0; index < count; index += 1) {
            const angle = Math.random() * Math.PI * 2;
            const speed = 1.5 + Math.random() * 4.5;
            this.particles.push({
                x,
                y,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed - 1.2,
                life: 1,
                decay: 0.018 + Math.random() * 0.018,
                size: 2 + Math.random() * 4,
                color,
                rotation: Math.random() * Math.PI,
                spin: (Math.random() - 0.5) * 0.18,
            });
        }
        if (!this.frame) {
            this.frame = window.requestAnimationFrame(this.draw);
        }
    }

    celebrate(isPersonalBest = false) {
        const colors = isPersonalBest
            ? ['#63E6BE', '#FFD43B', '#B197FC', '#74C0FC']
            : ['#63E6BE', '#74C0FC'];
        colors.forEach((color, index) => {
            window.setTimeout(
                () => this.burst(color, isPersonalBest ? 34 : 18),
                index * 80,
            );
        });
    }

    mistake() {
        this.burst('#FF7B89', 16);
    }

    draw() {
        if (!this.context || !this.canvas) {
            this.frame = null;
            return;
        }
        this.context.clearRect(0, 0, window.innerWidth, window.innerHeight);
        this.particles = this.particles.filter((particle) => {
            particle.x += particle.vx;
            particle.y += particle.vy;
            particle.vy += 0.08;
            particle.vx *= 0.99;
            particle.life -= particle.decay;
            particle.rotation += particle.spin;
            if (particle.life <= 0) {
                return false;
            }

            this.context.save();
            this.context.globalAlpha = Math.max(0, particle.life);
            this.context.translate(particle.x, particle.y);
            this.context.rotate(particle.rotation);
            this.context.fillStyle = particle.color;
            this.context.fillRect(
                -particle.size / 2,
                -particle.size / 2,
                particle.size,
                particle.size,
            );
            this.context.restore();
            return true;
        });

        if (this.particles.length) {
            this.frame = window.requestAnimationFrame(this.draw);
        } else {
            this.context.clearRect(0, 0, window.innerWidth, window.innerHeight);
            this.frame = null;
        }
    }
}
