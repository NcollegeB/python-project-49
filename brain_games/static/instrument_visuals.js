const SPATIAL_GAMES = new Set(['direction-focus', 'symbol-match']);

const VERTEX_SHADER = `
attribute vec2 a_position;
uniform vec2 u_resolution;

void main() {
    vec2 position = a_position / u_resolution;
    vec2 clip = (position * 2.0) - 1.0;
    gl_Position = vec4(clip * vec2(1.0, -1.0), 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision mediump float;
uniform vec4 u_color;

void main() {
    gl_FragColor = u_color;
}
`;


function parseColor(value, fallback) {
    const color = String(value || '').trim();
    const shortHex = color.match(/^#([0-9a-f]{3})$/i);
    if (shortHex) {
        return shortHex[1].split('').map(
            (component) => parseInt(component + component, 16) / 255,
        ).concat(1);
    }
    const hex = color.match(/^#([0-9a-f]{6})$/i);
    if (hex) {
        return [
            parseInt(hex[1].slice(0, 2), 16) / 255,
            parseInt(hex[1].slice(2, 4), 16) / 255,
            parseInt(hex[1].slice(4, 6), 16) / 255,
            1,
        ];
    }
    const rgb = color.match(
        /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i,
    );
    if (rgb) {
        return [
            Number(rgb[1]) / 255,
            Number(rgb[2]) / 255,
            Number(rgb[3]) / 255,
            rgb[4] === undefined ? 1 : Number(rgb[4]),
        ];
    }
    return fallback;
}


function relativeRect(element, origin) {
    const rect = element.getBoundingClientRect();
    return {
        left: rect.left - origin.left,
        top: rect.top - origin.top,
        right: rect.right - origin.left,
        bottom: rect.bottom - origin.top,
        width: rect.width,
        height: rect.height,
    };
}


function combinedRect(elements, origin) {
    const rects = elements.map((element) => relativeRect(element, origin));
    if (!rects.length) {
        return null;
    }
    return {
        left: Math.min(...rects.map((rect) => rect.left)),
        top: Math.min(...rects.map((rect) => rect.top)),
        right: Math.max(...rects.map((rect) => rect.right)),
        bottom: Math.max(...rects.map((rect) => rect.bottom)),
    };
}


function addLine(lines, x1, y1, x2, y2) {
    lines.push(x1, y1, x2, y2);
}


function addCornerFrame(lines, rect, padding = 8, length = 11) {
    const left = rect.left - padding;
    const top = rect.top - padding;
    const right = rect.right + padding;
    const bottom = rect.bottom + padding;
    addLine(lines, left, top, left + length, top);
    addLine(lines, left, top, left, top + length);
    addLine(lines, right, top, right - length, top);
    addLine(lines, right, top, right, top + length);
    addLine(lines, left, bottom, left + length, bottom);
    addLine(lines, left, bottom, left, bottom - length);
    addLine(lines, right, bottom, right - length, bottom);
    addLine(lines, right, bottom, right, bottom - length);
}


function addRectangle(lines, rect, padding = 0) {
    const left = rect.left - padding;
    const top = rect.top - padding;
    const right = rect.right + padding;
    const bottom = rect.bottom + padding;
    addLine(lines, left, top, right, top);
    addLine(lines, right, top, right, bottom);
    addLine(lines, right, bottom, left, bottom);
    addLine(lines, left, bottom, left, top);
}


function addFilledRectangle(triangles, rect, padding = 0) {
    const left = rect.left - padding;
    const top = rect.top - padding;
    const right = rect.right + padding;
    const bottom = rect.bottom + padding;
    triangles.push(
        left, top,
        right, top,
        left, bottom,
        left, bottom,
        right, top,
        right, bottom,
    );
}


function addRegistrationMarks(lines, width, height) {
    const inset = 12;
    const length = 9;
    [
        [inset, inset, 1, 1],
        [width - inset, inset, -1, 1],
        [inset, height - inset, 1, -1],
        [width - inset, height - inset, -1, -1],
    ].forEach(([x, y, xDirection, yDirection]) => {
        addLine(lines, x, y, x + (length * xDirection), y);
        addLine(lines, x, y, x, y + (length * yDirection));
    });
}


function deleteBufferInfo(gl, bufferInfo) {
    Object.values(bufferInfo.attribs || {}).forEach((attribute) => {
        if (attribute.buffer) {
            gl.deleteBuffer(attribute.buffer);
        }
    });
    if (bufferInfo.indices) {
        gl.deleteBuffer(bufferInfo.indices);
    }
}


export class InstrumentVisuals {
    constructor() {
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'instrument-overlay';
        this.canvas.setAttribute('aria-hidden', 'true');
        this.canvas.tabIndex = -1;
        this.container = null;
        this.round = null;
        this.review = null;
        this.gl = null;
        this.programInfo = null;
        this.drawFrame = null;
        this.contextLost = false;
        this.resizeObserver = typeof ResizeObserver === 'function'
            ? new ResizeObserver(() => this.requestDraw())
            : null;
        this.windowResize = () => this.requestDraw();
        this.themeObserver = new MutationObserver(() => this.requestDraw());

        this.canvas.addEventListener('webglcontextlost', (event) => {
            event.preventDefault();
            this.contextLost = true;
            this.programInfo = null;
            this.canvas.hidden = true;
            this.container?.removeAttribute('data-instrument');
        });
        this.canvas.addEventListener('webglcontextrestored', () => {
            this.contextLost = false;
            this.gl = null;
            if (this.ensureContext()) {
                this.canvas.hidden = false;
                this.container?.setAttribute('data-instrument', 'twgl');
                this.requestDraw();
            }
        });
        this.themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme'],
        });
        window.addEventListener('resize', this.windowResize);
    }

    ensureContext() {
        const twgl = globalThis.twgl;
        if (
            this.contextLost
            || !twgl
            || typeof twgl.createProgramInfo !== 'function'
        ) {
            return false;
        }
        if (!this.gl) {
            this.gl = this.canvas.getContext('webgl', {
                alpha: true,
                antialias: true,
                depth: false,
                stencil: false,
                premultipliedAlpha: true,
                powerPreference: 'low-power',
            });
        }
        if (!this.gl) {
            return false;
        }
        if (!this.programInfo) {
            try {
                this.programInfo = twgl.createProgramInfo(
                    this.gl,
                    [VERTEX_SHADER, FRAGMENT_SHADER],
                );
            } catch (_error) {
                this.programInfo = null;
                return false;
            }
        }
        return true;
    }

    render(round, container) {
        if (this.drawFrame !== null) {
            window.cancelAnimationFrame(this.drawFrame);
            this.drawFrame = null;
        }
        if (this.container && this.resizeObserver) {
            this.resizeObserver.unobserve(this.container);
        }
        this.container?.removeAttribute('data-instrument');
        this.container?.removeAttribute('data-plate-code');
        this.container = container;
        this.round = round;
        this.review = null;

        if (!SPATIAL_GAMES.has(round?.source_slug) || !this.ensureContext()) {
            this.canvas.remove();
            return false;
        }

        this.canvas.hidden = false;
        container.append(this.canvas);
        container.dataset.instrument = 'twgl';
        container.dataset.plateCode = (
            round.source_slug === 'direction-focus'
                ? 'DF / OPTICAL FIELD'
                : 'SM / COMPARATOR'
        );
        this.resizeObserver?.observe(container);
        this.requestDraw();
        return true;
    }

    showReview(review) {
        if (!this.container || !this.round) {
            return;
        }
        this.review = review || {};
        this.requestDraw();
    }

    requestDraw() {
        if (
            this.drawFrame !== null
            || !this.container
            || !this.canvas.isConnected
            || this.contextLost
        ) {
            return;
        }
        this.drawFrame = window.requestAnimationFrame(() => {
            this.drawFrame = null;
            this.draw();
        });
    }

    draw() {
        if (!this.ensureContext() || !this.container) {
            return;
        }
        const twgl = globalThis.twgl;
        const gl = this.gl;
        const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
        twgl.resizeCanvasToDisplaySize(this.canvas, pixelRatio);
        gl.viewport(0, 0, gl.canvas.width, gl.canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        const origin = this.container.getBoundingClientRect();
        const width = Math.max(1, origin.width);
        const height = Math.max(1, origin.height);
        const styles = getComputedStyle(document.documentElement);
        const guideColor = parseColor(
            styles.getPropertyValue('--rule-dark'),
            [0.45, 0.45, 0.45, 0.72],
        );
        guideColor[3] = 0.58;
        const reviewColor = parseColor(
            styles.getPropertyValue('--error'),
            [0.75, 0.2, 0.18, 1],
        );
        const guideLines = [];
        const reviewLines = [];
        const reviewFill = [];

        addRegistrationMarks(guideLines, width, height);
        if (this.round.source_slug === 'direction-focus') {
            this.directionGeometry(
                origin,
                guideLines,
                reviewLines,
                reviewFill,
            );
        } else {
            this.symbolGeometry(
                origin,
                guideLines,
                reviewLines,
                reviewFill,
            );
        }

        this.drawGeometry(
            reviewFill,
            gl.TRIANGLES,
            [...reviewColor.slice(0, 3), 0.10],
            width,
            height,
        );
        this.drawGeometry(
            guideLines,
            gl.LINES,
            guideColor,
            width,
            height,
        );
        this.drawGeometry(
            reviewLines,
            gl.LINES,
            reviewColor,
            width,
            height,
        );
    }

    directionGeometry(origin, guideLines, reviewLines, reviewFill) {
        const tokens = Array.from(
            this.container.querySelectorAll('.arrow-token'),
        );
        const field = combinedRect(tokens, origin);
        if (field) {
            addCornerFrame(guideLines, field, 9, 12);
        }
        tokens.forEach((token, index) => {
            const rect = relativeRect(token, origin);
            const centerX = rect.left + (rect.width / 2);
            const tick = index % 2 === 0 ? 4 : 2;
            addLine(
                guideLines,
                centerX,
                rect.top - 5,
                centerX,
                rect.top - 5 - tick,
            );
        });
        const targetIndex = Number(this.review?.target_index);
        if (
            Number.isInteger(targetIndex)
            && targetIndex >= 0
            && targetIndex < tokens.length
        ) {
            const target = relativeRect(tokens[targetIndex], origin);
            addFilledRectangle(reviewFill, target, 4);
            addRectangle(reviewLines, target, 5);
            addCornerFrame(reviewLines, target, 10, 8);
        }
    }

    symbolGeometry(origin, guideLines, reviewLines, reviewFill) {
        const sequences = Array.from(
            this.container.querySelectorAll('.symbol-sequence'),
        );
        sequences.forEach((sequence) => {
            const tokens = Array.from(
                sequence.querySelectorAll('.symbol-token'),
            );
            const field = combinedRect(tokens, origin);
            if (field) {
                addCornerFrame(guideLines, field, 8, 10);
                const baseline = field.bottom + 6;
                addLine(
                    guideLines,
                    field.left,
                    baseline,
                    field.right,
                    baseline,
                );
            }
        });

        if (!this.review) {
            return;
        }
        const rightTokens = Array.from(
            sequences[1]?.querySelectorAll('.symbol-token') || [],
        );
        const mismatchIndices = Array.isArray(this.review.mismatch_indices)
            ? this.review.mismatch_indices
            : [];
        mismatchIndices.forEach((rawIndex) => {
            const index = Number(rawIndex);
            if (!Number.isInteger(index) || !rightTokens[index]) {
                return;
            }
            const mismatch = relativeRect(rightTokens[index], origin);
            addFilledRectangle(reviewFill, mismatch, 4);
            addRectangle(reviewLines, mismatch, 5);
            addLine(
                reviewLines,
                mismatch.left - 5,
                mismatch.top - 5,
                mismatch.right + 5,
                mismatch.bottom + 5,
            );
        });
        if (this.review.matches === true && sequences.length === 2) {
            sequences.forEach((sequence) => {
                const field = combinedRect(
                    Array.from(sequence.querySelectorAll('.symbol-token')),
                    origin,
                );
                if (field) {
                    addCornerFrame(reviewLines, field, 11, 14);
                }
            });
        }
    }

    drawGeometry(positions, primitive, color, width, height) {
        if (!positions.length) {
            return;
        }
        const twgl = globalThis.twgl;
        const bufferInfo = twgl.createBufferInfoFromArrays(this.gl, {
            a_position: {
                numComponents: 2,
                data: positions,
            },
        });
        this.gl.useProgram(this.programInfo.program);
        twgl.setBuffersAndAttributes(
            this.gl,
            this.programInfo,
            bufferInfo,
        );
        twgl.setUniforms(this.programInfo, {
            u_resolution: [width, height],
            u_color: color,
        });
        twgl.drawBufferInfo(this.gl, bufferInfo, primitive);
        deleteBufferInfo(this.gl, bufferInfo);
    }
}
