const SPATIAL_GAMES = new Set(['direction-focus', 'symbol-match']);
const THREE_D_MODES = new Set(['direction_3d', 'polycube_3d']);

const LINE_VERTEX_SHADER = `
attribute vec2 a_position;
uniform vec2 u_resolution;

void main() {
    vec2 position = a_position / u_resolution;
    vec2 clip = (position * 2.0) - 1.0;
    gl_Position = vec4(clip * vec2(1.0, -1.0), 0.0, 1.0);
}
`;

const LINE_FRAGMENT_SHADER = `
precision mediump float;
uniform vec4 u_color;

void main() {
    gl_FragColor = u_color;
}
`;

const SOLID_VERTEX_SHADER = `
attribute vec3 a_position;
attribute vec3 a_normal;
uniform mat4 u_world;
uniform mat4 u_world_view_projection;
varying vec3 v_normal;

void main() {
    gl_Position = u_world_view_projection * vec4(a_position, 1.0);
    v_normal = mat3(u_world) * a_normal;
}
`;

const SOLID_FRAGMENT_SHADER = `
precision mediump float;
uniform vec4 u_color;
uniform vec3 u_light_direction;
varying vec3 v_normal;

void main() {
    vec3 normal = normalize(v_normal);
    float diffuse = max(dot(normal, normalize(u_light_direction)), 0.0);
    float light = 0.44 + (0.56 * diffuse);
    gl_FragColor = vec4(u_color.rgb * light, u_color.a);
}
`;

const DEG_TO_RAD = Math.PI / 180;


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
    return fallback.slice();
}


function mixColor(first, second, amount) {
    const weight = Math.max(0, Math.min(1, amount));
    return first.map((component, index) => (
        component + ((second[index] - component) * weight)
    ));
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


function mat4Identity() {
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ];
}


function mat4Multiply(first, second) {
    const output = new Array(16).fill(0);
    for (let column = 0; column < 4; column += 1) {
        for (let row = 0; row < 4; row += 1) {
            for (let index = 0; index < 4; index += 1) {
                output[(column * 4) + row] += (
                    first[(index * 4) + row]
                    * second[(column * 4) + index]
                );
            }
        }
    }
    return output;
}


function mat4Compose(...matrices) {
    return matrices.reduce(
        (combined, matrix) => mat4Multiply(combined, matrix),
        mat4Identity(),
    );
}


function mat4Translation(x, y, z) {
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        x, y, z, 1,
    ];
}


function mat4Scaling(x, y, z) {
    return [
        x, 0, 0, 0,
        0, y, 0, 0,
        0, 0, z, 0,
        0, 0, 0, 1,
    ];
}


function mat4RotationX(angle) {
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    return [
        1, 0, 0, 0,
        0, cosine, sine, 0,
        0, -sine, cosine, 0,
        0, 0, 0, 1,
    ];
}


function mat4RotationY(angle) {
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    return [
        cosine, 0, -sine, 0,
        0, 1, 0, 0,
        sine, 0, cosine, 0,
        0, 0, 0, 1,
    ];
}


function mat4RotationZ(angle) {
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    return [
        cosine, sine, 0, 0,
        -sine, cosine, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ];
}


function normalisedAxis(rawAxis) {
    const namedAxes = {
        x: [1, 0, 0],
        y: [0, 1, 0],
        z: [0, 0, 1],
    };
    let axis = Array.isArray(rawAxis)
        ? rawAxis.slice(0, 3).map(Number)
        : namedAxes[String(rawAxis || '').toLowerCase()];
    if (!axis || axis.length < 3 || !axis.every(Number.isFinite)) {
        axis = [0, 1, 0];
    }
    const length = Math.hypot(...axis);
    if (length < 0.0001) {
        return [0, 1, 0];
    }
    return axis.map((component) => component / length);
}


function mat4AxisRotation(rawAxis, angle) {
    const [x, y, z] = normalisedAxis(rawAxis);
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    const inverseCosine = 1 - cosine;
    return [
        (x * x * inverseCosine) + cosine,
        (x * y * inverseCosine) + (z * sine),
        (x * z * inverseCosine) - (y * sine),
        0,
        (x * y * inverseCosine) - (z * sine),
        (y * y * inverseCosine) + cosine,
        (y * z * inverseCosine) + (x * sine),
        0,
        (x * z * inverseCosine) + (y * sine),
        (y * z * inverseCosine) - (x * sine),
        (z * z * inverseCosine) + cosine,
        0,
        0, 0, 0, 1,
    ];
}


function mat4Perspective(fieldOfView, aspect, near, far) {
    const focalLength = 1 / Math.tan(fieldOfView / 2);
    const rangeInverse = 1 / (near - far);
    return [
        focalLength / aspect, 0, 0, 0,
        0, focalLength, 0, 0,
        0, 0, (near + far) * rangeInverse, -1,
        0, 0, near * far * rangeInverse * 2, 0,
    ];
}


function finiteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
}


function limitedSpeed(value, fallback = 8) {
    return Math.max(-24, Math.min(24, finiteNumber(value, fallback)));
}


function cubeMeshArrays() {
    const positions = [];
    const normals = [];
    const indices = [];
    const faces = [
        {
            normal: [0, 0, 1],
            corners: [
                [-0.5, -0.5, 0.5], [0.5, -0.5, 0.5],
                [0.5, 0.5, 0.5], [-0.5, 0.5, 0.5],
            ],
        },
        {
            normal: [0, 0, -1],
            corners: [
                [0.5, -0.5, -0.5], [-0.5, -0.5, -0.5],
                [-0.5, 0.5, -0.5], [0.5, 0.5, -0.5],
            ],
        },
        {
            normal: [0, 1, 0],
            corners: [
                [-0.5, 0.5, 0.5], [0.5, 0.5, 0.5],
                [0.5, 0.5, -0.5], [-0.5, 0.5, -0.5],
            ],
        },
        {
            normal: [0, -1, 0],
            corners: [
                [-0.5, -0.5, -0.5], [0.5, -0.5, -0.5],
                [0.5, -0.5, 0.5], [-0.5, -0.5, 0.5],
            ],
        },
        {
            normal: [1, 0, 0],
            corners: [
                [0.5, -0.5, 0.5], [0.5, -0.5, -0.5],
                [0.5, 0.5, -0.5], [0.5, 0.5, 0.5],
            ],
        },
        {
            normal: [-1, 0, 0],
            corners: [
                [-0.5, -0.5, -0.5], [-0.5, -0.5, 0.5],
                [-0.5, 0.5, 0.5], [-0.5, 0.5, -0.5],
            ],
        },
    ];
    faces.forEach((face) => {
        const offset = positions.length / 3;
        face.corners.forEach((corner) => {
            positions.push(...corner);
            normals.push(...face.normal);
        });
        indices.push(
            offset, offset + 1, offset + 2,
            offset, offset + 2, offset + 3,
        );
    });
    return {positions, normals, indices};
}


function coneMeshArrays(
    segments = 12,
    bottomRadius = 0.5,
    topRadius = 0,
) {
    const positions = [];
    const normals = [];
    const indices = [];
    const safeSegments = Math.max(3, Math.round(segments));
    const slope = bottomRadius - topRadius;
    const normalLength = Math.hypot(1, slope);

    for (let index = 0; index <= safeSegments; index += 1) {
        const angle = (index / safeSegments) * Math.PI * 2;
        const cosine = Math.cos(angle);
        const sine = Math.sin(angle);
        positions.push(
            cosine * bottomRadius, -0.5, sine * bottomRadius,
            cosine * topRadius, 0.5, sine * topRadius,
        );
        const normal = [
            cosine / normalLength,
            slope / normalLength,
            sine / normalLength,
        ];
        normals.push(...normal, ...normal);
    }
    for (let index = 0; index < safeSegments; index += 1) {
        const lower = index * 2;
        indices.push(
            lower, lower + 1, lower + 2,
            lower + 1, lower + 3, lower + 2,
        );
    }

    const bottomCenter = positions.length / 3;
    positions.push(0, -0.5, 0);
    normals.push(0, -1, 0);
    for (let index = 0; index <= safeSegments; index += 1) {
        const angle = (index / safeSegments) * Math.PI * 2;
        positions.push(
            Math.cos(angle) * bottomRadius,
            -0.5,
            Math.sin(angle) * bottomRadius,
        );
        normals.push(0, -1, 0);
    }
    for (let index = 0; index < safeSegments; index += 1) {
        indices.push(
            bottomCenter,
            bottomCenter + index + 2,
            bottomCenter + index + 1,
        );
    }

    if (topRadius > 0) {
        const topCenter = positions.length / 3;
        positions.push(0, 0.5, 0);
        normals.push(0, 1, 0);
        for (let index = 0; index <= safeSegments; index += 1) {
            const angle = (index / safeSegments) * Math.PI * 2;
            positions.push(
                Math.cos(angle) * topRadius,
                0.5,
                Math.sin(angle) * topRadius,
            );
            normals.push(0, 1, 0);
        }
        for (let index = 0; index < safeSegments; index += 1) {
            indices.push(
                topCenter,
                topCenter + index + 1,
                topCenter + index + 2,
            );
        }
    }
    return {positions, normals, indices};
}


function polyhedronMeshArrays(vertices, faces) {
    const positions = [];
    const normals = [];
    const indices = [];
    faces.forEach((face) => {
        const points = face.map((index) => vertices[index]);
        const firstEdge = points[1].map(
            (value, index) => value - points[0][index],
        );
        const secondEdge = points[2].map(
            (value, index) => value - points[0][index],
        );
        const rawNormal = [
            (firstEdge[1] * secondEdge[2])
                - (firstEdge[2] * secondEdge[1]),
            (firstEdge[2] * secondEdge[0])
                - (firstEdge[0] * secondEdge[2]),
            (firstEdge[0] * secondEdge[1])
                - (firstEdge[1] * secondEdge[0]),
        ];
        const normalLength = Math.max(0.0001, Math.hypot(...rawNormal));
        const normal = rawNormal.map(
            (component) => component / normalLength,
        );
        const offset = positions.length / 3;
        points.forEach((point) => {
            positions.push(...point);
            normals.push(...normal);
        });
        indices.push(offset, offset + 1, offset + 2);
    });
    return {positions, normals, indices};
}


function tetrahedronMeshArrays() {
    const scale = 0.36;
    return polyhedronMeshArrays(
        [
            [1, 1, 1],
            [-1, -1, 1],
            [-1, 1, -1],
            [1, -1, -1],
        ].map((vertex) => vertex.map((value) => value * scale)),
        [
            [0, 1, 2],
            [0, 3, 1],
            [0, 2, 3],
            [1, 3, 2],
        ],
    );
}


function octahedronMeshArrays() {
    return polyhedronMeshArrays(
        [
            [0, 0.6, 0],
            [0, -0.6, 0],
            [0.6, 0, 0],
            [-0.6, 0, 0],
            [0, 0, 0.6],
            [0, 0, -0.6],
        ],
        [
            [0, 2, 4], [0, 4, 3],
            [0, 3, 5], [0, 5, 2],
            [1, 4, 2], [1, 3, 4],
            [1, 5, 3], [1, 2, 5],
        ],
    );
}


function meshBufferInfo(gl, arrays) {
    return globalThis.twgl.createBufferInfoFromArrays(gl, {
        a_position: {
            numComponents: 3,
            data: arrays.positions,
        },
        a_normal: {
            numComponents: 3,
            data: arrays.normals,
        },
        indices: arrays.indices,
    });
}


function directionOrientation(direction) {
    const normalised = String(direction || '').toLowerCase();
    if (normalised === 'right') {
        return mat4RotationZ(-Math.PI / 2);
    }
    if (normalised === 'down') {
        return mat4RotationZ(Math.PI);
    }
    if (normalised === 'left') {
        return mat4RotationZ(Math.PI / 2);
    }
    if (new Set(['toward', 'towards', 'forward']).has(normalised)) {
        return mat4RotationX(Math.PI / 2);
    }
    if (new Set(['away', 'backward']).has(normalised)) {
        return mat4RotationX(-Math.PI / 2);
    }
    return mat4Identity();
}


function visibleFeature(value) {
    return !new Set(['', '0', 'false', 'none', 'off', 'null']).has(
        String(value ?? '').trim().toLowerCase(),
    );
}


function bandCount(value) {
    const normalised = String(value ?? '').trim().toLowerCase();
    if (!visibleFeature(normalised)) {
        return 0;
    }
    return new Set([
        'double', 'twin', 'two', '2', 'split',
    ]).has(normalised) ? 2 : 1;
}


function normaliseCubes(rawCubes) {
    if (!Array.isArray(rawCubes)) {
        return [];
    }
    return rawCubes.flatMap((cube, index) => {
        if (!Array.isArray(cube) || cube.length < 3) {
            return [];
        }
        const coordinates = cube.slice(0, 3).map(Number);
        if (!coordinates.every(Number.isFinite)) {
            return [];
        }
        return [{coordinates, index}];
    });
}


function cubeCenter(cubes) {
    if (!cubes.length) {
        return [0, 0, 0];
    }
    return [0, 1, 2].map((axis) => {
        const values = cubes.map(({coordinates}) => coordinates[axis]);
        return (Math.min(...values) + Math.max(...values)) / 2;
    });
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
        this.sceneMode = null;
        this.gl = null;
        this.lineProgramInfo = null;
        this.solidProgramInfo = null;
        this.meshes = null;
        this.drawFrame = null;
        this.animationElapsedMs = 0;
        this.lastFrameTime = null;
        this.contextLost = false;
        this.motionQuery = window.matchMedia(
            '(prefers-reduced-motion: reduce)',
        );
        this.resizeObserver = typeof ResizeObserver === 'function'
            ? new ResizeObserver(() => this.requestDraw())
            : null;
        this.windowResize = () => this.requestDraw();
        this.motionChange = () => {
            this.lastFrameTime = null;
            this.requestDraw();
        };
        this.visibilityChange = () => {
            this.lastFrameTime = null;
            if (document.visibilityState !== 'hidden') {
                this.requestDraw();
            }
        };
        this.themeObserver = new MutationObserver(() => this.requestDraw());

        this.canvas.addEventListener('webglcontextlost', (event) => {
            event.preventDefault();
            this.contextLost = true;
            this.cancelDraw();
            this.lineProgramInfo = null;
            this.solidProgramInfo = null;
            this.meshes = null;
            this.canvas.hidden = true;
            this.container?.removeAttribute('data-instrument');
        });
        this.canvas.addEventListener('webglcontextrestored', () => {
            this.contextLost = false;
            this.gl = null;
            if (this.ensureContext()) {
                this.canvas.hidden = false;
                this.applyInstrumentAttribute();
                this.requestDraw();
            }
        });
        this.themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme'],
        });
        if (typeof this.motionQuery.addEventListener === 'function') {
            this.motionQuery.addEventListener('change', this.motionChange);
        } else {
            this.motionQuery.addListener?.(this.motionChange);
        }
        document.addEventListener(
            'visibilitychange',
            this.visibilityChange,
        );
        window.addEventListener('resize', this.windowResize);
    }

    cancelDraw() {
        if (this.drawFrame !== null) {
            window.cancelAnimationFrame(this.drawFrame);
            this.drawFrame = null;
        }
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
                depth: true,
                stencil: false,
                premultipliedAlpha: true,
                powerPreference: 'low-power',
            });
        }
        if (!this.gl) {
            return false;
        }
        if (!this.lineProgramInfo) {
            try {
                this.lineProgramInfo = twgl.createProgramInfo(
                    this.gl,
                    [LINE_VERTEX_SHADER, LINE_FRAGMENT_SHADER],
                );
            } catch (_error) {
                this.lineProgramInfo = null;
                return false;
            }
        }
        return true;
    }

    ensureSolidResources() {
        if (!this.ensureContext()) {
            return false;
        }
        const twgl = globalThis.twgl;
        if (!this.solidProgramInfo) {
            try {
                this.solidProgramInfo = twgl.createProgramInfo(
                    this.gl,
                    [SOLID_VERTEX_SHADER, SOLID_FRAGMENT_SHADER],
                );
            } catch (_error) {
                this.solidProgramInfo = null;
                return false;
            }
        }
        if (!this.meshes) {
            try {
                this.meshes = {
                    cube: meshBufferInfo(this.gl, cubeMeshArrays()),
                    tetrahedron: meshBufferInfo(
                        this.gl,
                        tetrahedronMeshArrays(),
                    ),
                    octahedron: meshBufferInfo(
                        this.gl,
                        octahedronMeshArrays(),
                    ),
                    cone: meshBufferInfo(
                        this.gl,
                        coneMeshArrays(12, 0.5, 0),
                    ),
                    prism3: meshBufferInfo(
                        this.gl,
                        coneMeshArrays(3, 0.5, 0.5),
                    ),
                    prism6: meshBufferInfo(
                        this.gl,
                        coneMeshArrays(6, 0.5, 0.5),
                    ),
                    cylinder: meshBufferInfo(
                        this.gl,
                        coneMeshArrays(12, 0.5, 0.5),
                    ),
                };
            } catch (_error) {
                this.meshes = null;
                return false;
            }
        }
        return true;
    }

    applyInstrumentAttribute() {
        if (!this.container) {
            return;
        }
        this.container.dataset.instrument = this.isThreeDimensional()
            ? 'twgl-3d'
            : 'twgl';
    }

    render(round, container) {
        this.cancelDraw();
        if (this.container && this.resizeObserver) {
            this.resizeObserver.unobserve(this.container);
        }
        this.container?.removeAttribute('data-instrument');
        this.container?.removeAttribute('data-plate-code');
        this.container = container;
        this.round = round;
        this.review = null;
        this.sceneMode = String(
            round?.data?.render_mode || '',
        ).toLowerCase();
        this.animationElapsedMs = 0;
        this.lastFrameTime = null;

        if (!SPATIAL_GAMES.has(round?.source_slug) || !this.ensureContext()) {
            this.canvas.remove();
            return false;
        }
        if (this.isThreeDimensional() && !this.ensureSolidResources()) {
            this.canvas.remove();
            return false;
        }

        this.canvas.hidden = false;
        container.append(this.canvas);
        this.applyInstrumentAttribute();
        if (this.sceneMode === 'direction_3d') {
            container.dataset.plateCode = 'DF / SPATIAL AXIS';
        } else if (this.sceneMode === 'polycube_3d') {
            container.dataset.plateCode = 'SM / SOLID ROTATION';
        } else {
            container.dataset.plateCode = (
                round.source_slug === 'direction-focus'
                    ? 'DF / OPTICAL FIELD'
                    : 'SM / COMPARATOR'
            );
        }
        this.resizeObserver?.observe(container);
        this.requestDraw();
        return true;
    }

    showReview(review) {
        if (!this.container || !this.round) {
            return;
        }
        this.review = review || {};
        this.lastFrameTime = null;
        this.requestDraw();
    }

    isThreeDimensional() {
        return THREE_D_MODES.has(this.sceneMode);
    }

    shouldAnimate() {
        return (
            this.isThreeDimensional()
            && !this.review
            && !this.motionQuery.matches
            && document.visibilityState !== 'hidden'
            && Boolean(this.container?.getClientRects().length)
        );
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
        this.drawFrame = window.requestAnimationFrame((timestamp) => {
            this.drawFrame = null;
            if (this.shouldAnimate()) {
                if (this.lastFrameTime !== null) {
                    this.animationElapsedMs += Math.min(
                        100,
                        Math.max(0, timestamp - this.lastFrameTime),
                    );
                }
                this.lastFrameTime = timestamp;
            } else {
                this.lastFrameTime = null;
            }
            this.draw();
            if (this.shouldAnimate()) {
                this.requestDraw();
            }
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

        if (this.isThreeDimensional()) {
            if (!this.ensureSolidResources()) {
                this.canvas.hidden = true;
                this.container.removeAttribute('data-instrument');
                return;
            }
            gl.enable(gl.DEPTH_TEST);
            gl.depthFunc(gl.LEQUAL);
            gl.disable(gl.BLEND);
            gl.disable(gl.CULL_FACE);
            gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
            if (this.sceneMode === 'direction_3d') {
                this.drawDirection3D();
            } else {
                this.drawPolycube3D();
            }
            return;
        }

        gl.disable(gl.DEPTH_TEST);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        this.drawDiagnosticOverlay();
    }

    themeColors() {
        const styles = getComputedStyle(document.documentElement);
        return {
            ink: parseColor(
                styles.getPropertyValue('--ink'),
                [0.12, 0.12, 0.11, 1],
            ),
            muted: parseColor(
                styles.getPropertyValue('--muted'),
                [0.45, 0.43, 0.4, 1],
            ),
            sheet: parseColor(
                styles.getPropertyValue('--sheet'),
                [0.98, 0.97, 0.93, 1],
            ),
            rule: parseColor(
                styles.getPropertyValue('--rule-dark'),
                [0.45, 0.45, 0.45, 1],
            ),
            error: parseColor(
                styles.getPropertyValue('--error'),
                [0.75, 0.2, 0.18, 1],
            ),
        };
    }

    sceneViewProjection(sceneWidth, sceneHeight) {
        const aspect = Math.max(
            0.25,
            this.canvas.clientWidth / Math.max(1, this.canvas.clientHeight),
        );
        const fieldOfView = 38 * DEG_TO_RAD;
        const verticalDistance = (
            (sceneHeight / 2) / Math.tan(fieldOfView / 2)
        );
        const horizontalDistance = (
            (sceneWidth / 2)
            / (Math.tan(fieldOfView / 2) * aspect)
        );
        const distance = Math.max(
            5.5,
            verticalDistance + 1.3,
            horizontalDistance + 1.3,
        );
        return mat4Multiply(
            mat4Perspective(fieldOfView, aspect, 0.1, 100),
            mat4Translation(0, 0, -distance),
        );
    }

    drawSolid(mesh, world, viewProjection, color) {
        const twgl = globalThis.twgl;
        const worldViewProjection = mat4Multiply(viewProjection, world);
        this.gl.useProgram(this.solidProgramInfo.program);
        twgl.setBuffersAndAttributes(
            this.gl,
            this.solidProgramInfo,
            mesh,
        );
        twgl.setUniforms(this.solidProgramInfo, {
            u_world: world,
            u_world_view_projection: worldViewProjection,
            u_color: color,
            u_light_direction: [0.35, 0.72, 0.6],
        });
        twgl.drawBufferInfo(this.gl, mesh);
    }

    directionShaftMesh(solid) {
        const name = String(solid || '').toLowerCase();
        if (name.includes('tetra')) {
            return this.meshes.tetrahedron;
        }
        if (name.includes('octa')) {
            return this.meshes.octahedron;
        }
        if (name.includes('tri')) {
            return this.meshes.prism3;
        }
        if (name.includes('hex')) {
            return this.meshes.prism6;
        }
        if (
            name.includes('round')
            || name.includes('cylinder')
            || name.includes('tube')
        ) {
            return this.meshes.cylinder;
        }
        return this.meshes.cube;
    }

    drawDirection3D() {
        const data = this.round?.data || {};
        const items = Array.isArray(data.items) ? data.items : [];
        if (!items.length) {
            return;
        }
        const columns = Math.max(
            2,
            Math.min(6, Math.round(finiteNumber(
                data.grid_columns,
                Math.ceil(Math.sqrt(items.length)),
            ))),
        );
        const rows = Math.ceil(items.length / columns);
        const spacingX = 1.22;
        const spacingY = 1.2;
        const sceneWidth = ((columns - 1) * spacingX) + 1.05;
        const sceneHeight = ((rows - 1) * spacingY) + 1.05;
        const viewProjection = this.sceneViewProjection(
            sceneWidth,
            sceneHeight,
        );
        const colors = this.themeColors();
        const bodyColor = mixColor(colors.ink, colors.sheet, 0.16);
        const bandColor = mixColor(colors.rule, colors.ink, 0.28);
        const targetIndex = Number(this.review?.target_index);

        items.forEach((item, index) => {
            const row = Math.floor(index / columns);
            const column = index % columns;
            const rowLength = Math.min(
                columns,
                items.length - (row * columns),
            );
            const x = (
                column - ((rowLength - 1) / 2)
            ) * spacingX;
            const y = (
                ((rows - 1) / 2) - row
            ) * spacingY;
            const phase = finiteNumber(item?.spin_phase_deg, 0);
            const speed = limitedSpeed(item?.spin_speed_deg_s, 9);
            const roll = (
                phase + (speed * this.animationElapsedMs / 1000)
            ) * DEG_TO_RAD;
            const isTarget = (
                this.review
                && Number.isInteger(targetIndex)
                && targetIndex === index
            );
            const color = isTarget ? colors.error : bodyColor;
            const base = mat4Compose(
                mat4Translation(x, y, 0),
                directionOrientation(item?.direction),
                mat4RotationY(roll),
                mat4Scaling(
                    isTarget ? 1.09 : 1,
                    isTarget ? 1.09 : 1,
                    isTarget ? 1.09 : 1,
                ),
            );
            const shaftMesh = this.directionShaftMesh(item?.solid);
            const shaft = mat4Compose(
                base,
                mat4Translation(0, -0.17, 0),
                mat4Scaling(0.34, 0.65, 0.34),
            );
            const head = mat4Compose(
                base,
                mat4Translation(0, 0.29, 0),
                mat4Scaling(0.72, 0.45, 0.72),
            );
            this.drawSolid(
                shaftMesh,
                shaft,
                viewProjection,
                color,
            );
            this.drawSolid(
                this.meshes.cone,
                head,
                viewProjection,
                color,
            );

            const numberOfBands = bandCount(item?.band);
            const bandPositions = numberOfBands === 2
                ? [-0.29, -0.08]
                : [-0.18];
            bandPositions.slice(0, numberOfBands).forEach((bandY) => {
                const band = mat4Compose(
                    base,
                    mat4Translation(0, bandY, 0),
                    mat4Scaling(0.39, 0.075, 0.39),
                );
                this.drawSolid(
                    shaftMesh,
                    band,
                    viewProjection,
                    isTarget ? colors.error : bandColor,
                );
            });

            if (visibleFeature(item?.beacon)) {
                const beacon = mat4Compose(
                    base,
                    mat4Translation(0.24, -0.02, 0),
                    mat4Scaling(0.14, 0.14, 0.14),
                );
                this.gl.disable(this.gl.DEPTH_TEST);
                this.drawSolid(
                    this.meshes.cube,
                    beacon,
                    viewProjection,
                    isTarget ? colors.error : colors.rule,
                );
                this.gl.enable(this.gl.DEPTH_TEST);
            }
        });
    }

    drawPolycube3D() {
        const data = this.round?.data || {};
        const leftCubes = normaliseCubes(data.left_cubes);
        const rightCubes = normaliseCubes(data.right_cubes);
        if (!leftCubes.length || !rightCubes.length) {
            return;
        }
        const allCoordinates = leftCubes.concat(rightCubes);
        const spans = [0, 1, 2].map((axis) => {
            const values = allCoordinates.map(
                ({coordinates}) => coordinates[axis],
            );
            return Math.max(...values) - Math.min(...values) + 1;
        });
        const modelSpan = Math.max(...spans) * 0.68;
        const panelOffset = Math.max(1.55, modelSpan * 0.82);
        const viewProjection = this.sceneViewProjection(
            (panelOffset * 2) + modelSpan,
            modelSpan + 0.8,
        );
        const colors = this.themeColors();
        const leftColor = mixColor(colors.ink, colors.sheet, 0.12);
        const rightColor = mixColor(colors.ink, colors.muted, 0.24);
        const mismatchIndices = new Set(
            Array.isArray(this.review?.mismatch_indices)
                ? this.review.mismatch_indices
                    .map(Number)
                    .filter(Number.isInteger)
                : [],
        );
        const axis = normalisedAxis(data.spin_axis);
        const speed = limitedSpeed(data.spin_speed_deg_s, 7);
        const rawPhase = data.spin_phase_deg;
        const phases = Array.isArray(rawPhase)
            ? [
                finiteNumber(rawPhase[0], 0),
                finiteNumber(rawPhase[1], finiteNumber(rawPhase[0], 0)),
            ]
            : [
                finiteNumber(rawPhase, 0),
                finiteNumber(rawPhase, 0),
            ];

        [
            {
                cubes: leftCubes,
                centerX: -panelOffset,
                side: 'left',
                phase: phases[0],
                baseColor: leftColor,
            },
            {
                cubes: rightCubes,
                centerX: panelOffset,
                side: 'right',
                phase: phases[1],
                baseColor: rightColor,
            },
        ].forEach((model) => {
            const center = cubeCenter(model.cubes);
            const angle = (
                model.phase + (speed * this.animationElapsedMs / 1000)
            ) * DEG_TO_RAD;
            const base = mat4Compose(
                mat4Translation(model.centerX, 0, 0),
                mat4RotationX(-24 * DEG_TO_RAD),
                mat4AxisRotation(axis, angle),
            );
            model.cubes.forEach(({coordinates, index}) => {
                const isMismatch = (
                    this.review
                    && model.side === 'right'
                    && mismatchIndices.has(index)
                );
                const isConfirmedMatch = (
                    this.review?.matches === true
                );
                let cubeColor = model.baseColor;
                if (isMismatch) {
                    cubeColor = colors.error;
                } else if (isConfirmedMatch) {
                    cubeColor = mixColor(
                        model.baseColor,
                        colors.error,
                        0.48,
                    );
                }
                const cube = mat4Compose(
                    base,
                    mat4Translation(
                        (coordinates[0] - center[0]) * 0.68,
                        (coordinates[1] - center[1]) * 0.68,
                        (coordinates[2] - center[2]) * 0.68,
                    ),
                    mat4Scaling(0.61, 0.61, 0.61),
                );
                this.drawSolid(
                    this.meshes.cube,
                    cube,
                    viewProjection,
                    cubeColor,
                );
            });
        });
    }

    drawDiagnosticOverlay() {
        const gl = this.gl;
        const origin = this.container.getBoundingClientRect();
        const width = Math.max(1, origin.width);
        const height = Math.max(1, origin.height);
        const colors = this.themeColors();
        const guideColor = colors.rule.slice();
        guideColor[3] = 0.58;
        const reviewColor = colors.error;
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

        this.drawLineGeometry(
            reviewFill,
            gl.TRIANGLES,
            [...reviewColor.slice(0, 3), 0.10],
            width,
            height,
        );
        this.drawLineGeometry(
            guideLines,
            gl.LINES,
            guideColor,
            width,
            height,
        );
        this.drawLineGeometry(
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

    drawLineGeometry(positions, primitive, color, width, height) {
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
        this.gl.useProgram(this.lineProgramInfo.program);
        twgl.setBuffersAndAttributes(
            this.gl,
            this.lineProgramInfo,
            bufferInfo,
        );
        twgl.setUniforms(this.lineProgramInfo, {
            u_resolution: [width, height],
            u_color: color,
        });
        twgl.drawBufferInfo(this.gl, bufferInfo, primitive);
        deleteBufferInfo(this.gl, bufferInfo);
    }
}
