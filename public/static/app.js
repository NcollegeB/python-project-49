import {ArcadeAudio} from './audio.js';


const PLAYER_STORAGE_KEY = 'brainhacker-player-name';
const GUEST_PREFIX = 'Guest#';
const FEEDBACK_DELAY = 620;
const STILL_CHECKING_DELAY = 1000;
const TIMEOUT_ANSWER = '__brainhacker_timeout__';
const TIMEOUT_RETRY_DELAYS = [500, 1000, 2000, 4000, 5000];
const SUPPORTED_ARROW_ROTATIONS = new Set([
    0, 20, 30, 40, 45, 50, 60, 70,
    90, 110, 120, 130, 135, 140, 150, 160,
    180, 200, 210, 220, 225, 230, 240, 250,
    270, 290, 300, 310, 315, 320, 330, 340,
]);

const iconBySlug = {
    even: '02',
    calc: '×+',
    gcd: '∩',
    progression: '…',
    prime: 'P',
    'number-memory': '739',
    'verbal-memory': 'Aa',
    'direction-focus': '↗',
    'symbol-match': '◇◆',
    'word-scramble': 'A?',
    culmination: '10×',
};

const instructionBySlug = {
    even: 'Is this number even?',
    calc: 'Solve the expression.',
    gcd: 'Find the greatest common divisor.',
    progression: 'Fill in the missing number.',
    prime: 'Is this number prime?',
    'number-memory': 'Memorize this number.',
    'verbal-memory': 'Have you seen this word in this run?',
    'direction-focus': 'Which way does the odd arrow point?',
    'symbol-match': 'Do these symbols match?',
    'word-scramble': 'Unscramble the letters.',
};

const dom = {};
const state = {
    catalog: [],
    selected: null,
    run: null,
    round: null,
    roundNumber: 0,
    busy: false,
    preview: {
        timer: null,
        startFrame: null,
        roundId: null,
        totalMs: 0,
        remainingMs: 0,
        lastTick: null,
        paused: false,
    },
    transitionTimer: null,
    pendingTimer: null,
    pendingRoundId: null,
    pendingControl: null,
    focusRestoreFrame: null,
    leaderboardRequestSequence: 0,
    timeoutRetry: {
        timer: null,
        runId: null,
        roundId: null,
        startSequence: null,
        attempts: 0,
        mode: null,
    },
    countdown: {
        frame: null,
        startFrame: null,
        roundId: null,
        totalMs: 0,
        remainingMs: 0,
        lastTick: null,
        paused: false,
        lowTimeAnnounced: false,
        renderedTenths: null,
    },
    startSequence: 0,
    navigating: false,
    personalBests: new Map(),
    benchmarks: new Map(),
};

let audio;
let guestPlayerName;


function scrollBehavior() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth';
}


function getElement(id) {
    return document.getElementById(id);
}


function cacheDom() {
    [
        'homeView', 'gameView', 'gameGrid',
        'leaderboardButton', 'soundToggle', 'backButton',
        'stageCategory', 'stageTitle', 'runStatus',
        'stageRules', 'scoreValue', 'livesValue', 'levelValue',
        'levelProgress', 'roundValue',
        'cycleTrack', 'briefingState', 'activeState', 'resultState',
        'briefingIcon', 'briefingTitle', 'briefingDescription',
        'timingMode', 'startRunButton', 'roundSource', 'difficultyLabel',
        'roundPrompt', 'roundTimer', 'timerText', 'timerProgress',
        'timerAnnouncement', 'roundVisual',
        'memoryCurtain', 'answerForm', 'answerInput', 'submitAnswer',
        'choiceControls', 'answerRow', 'feedbackRegion', 'resultScore', 'resultBest',
        'resultAverage', 'resultPercentile', 'resultRank',
        'resultMessage', 'retryButton', 'resultMenuButton',
        'leaderboardDialog', 'leaderboardRows', 'leaderboardFilter',
        'closeLeaderboard', 'briefingFeedback',
    ].forEach((id) => {
        dom[id] = getElement(id);
    });
}


async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: {
            Accept: 'application/json',
            ...(options.body ? {'Content-Type': 'application/json'} : {}),
            ...(options.headers || {}),
        },
        ...options,
    });
    let payload = {};
    try {
        payload = await response.json();
    } catch (_error) {
        payload = {};
    }
    if (!response.ok) {
        const error = new Error(
            payload.message || payload.error || 'Something went wrong.',
        );
        error.status = response.status;
        throw error;
    }
    return payload;
}


function readPlayerName() {
    if (guestPlayerName) {
        return guestPlayerName;
    }
    try {
        const stored = window.localStorage.getItem(PLAYER_STORAGE_KEY);
        if (/^Guest#[0-9a-f]{12}$/.test(stored || '')) {
            guestPlayerName = stored;
            return guestPlayerName;
        }
    } catch (_error) {
        // A temporary guest identity still works without browser storage.
    }
    const bytes = new Uint8Array(6);
    if (window.crypto?.getRandomValues) {
        window.crypto.getRandomValues(bytes);
    } else {
        bytes.forEach((_value, index) => {
            bytes[index] = Math.floor(Math.random() * 256);
        });
    }
    const suffix = Array.from(
        bytes,
        (value) => value.toString(16).padStart(2, '0'),
    ).join('');
    guestPlayerName = `${GUEST_PREFIX}${suffix}`;
    try {
        window.localStorage.setItem(PLAYER_STORAGE_KEY, guestPlayerName);
    } catch (_error) {
        // The in-memory identity remains stable for this page load.
    }
    return guestPlayerName;
}


function currentPlayerName() {
    const accountName = document.body.dataset.currentUser;
    if (accountName) {
        return accountName;
    }
    return readPlayerName();
}


function unwrapGames(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }
    return payload.games || payload.catalog || [];
}


function unwrapRun(payload) {
    return payload.run || payload;
}


function unwrapLeaders(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }
    return payload.entries || payload.leaders || payload.scores || [];
}


function categoryClass(category) {
    return String(category || 'General').toLowerCase().replace(/\s+/g, '-');
}


function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = text;
    return element;
}


function findGame(slug) {
    return state.catalog.find((game) => game.slug === slug) || null;
}


function renderCards() {
    if (!dom.gameGrid) {
        return;
    }
    dom.gameGrid.replaceChildren();

    state.catalog.forEach((game) => {
        const card = document.createElement('a');
        card.className = 'game-card';
        card.href = `/play/${encodeURIComponent(game.slug)}`;
        card.dataset.category = categoryClass(game.category);
        card.dataset.game = game.slug;
        const picture = createTextElement(
            'span',
            'game-card__picture',
            game.icon || iconBySlug[game.slug] || '•',
        );
        picture.setAttribute('aria-hidden', 'true');
        card.append(
            picture,
            createTextElement('h3', 'game-card__title', game.name),
            createTextElement(
                'p',
                'game-card__description',
                game.description || game.rules,
            ),
        );
        card.addEventListener('click', (event) => {
            if (
                event.defaultPrevented
                || event.button !== 0
                || event.metaKey
                || event.ctrlKey
                || event.shiftKey
                || event.altKey
            ) {
                return;
            }
            event.preventDefault();
            openBriefing(game.slug);
        });
        dom.gameGrid.append(card);
    });
}


function showState(name) {
    const mapping = {
        briefing: dom.briefingState,
        active: dom.activeState,
        result: dom.resultState,
    };
    Object.entries(mapping).forEach(([key, element]) => {
        if (element) {
            element.hidden = key !== name;
        }
    });
}


function showView(name) {
    if (dom.homeView) {
        dom.homeView.hidden = name !== 'home';
    }
    if (dom.gameView) {
        dom.gameView.hidden = name !== 'game';
    }
    document.body.dataset.view = name;
    window.scrollTo({top: 0, behavior: scrollBehavior()});
}


function updateHistory(slug = null, replace = false) {
    const path = slug ? `/play/${encodeURIComponent(slug)}` : '/';
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({game: slug}, '', path);
}


function selectedTimingMode() {
    const selected = dom.timingMode?.querySelector(
        'input[name="timing-mode"]:checked',
    );
    return selected?.value || 'standard';
}


function setTimingControlsDisabled(disabled) {
    dom.timingMode?.querySelectorAll('input').forEach((input) => {
        input.disabled = disabled;
    });
}


function openBriefing(slug, options = {}) {
    const game = findGame(slug);
    if (!game) {
        return;
    }
    clearPreviewTimer();
    clearTransitionTimer();
    clearPendingFeedback();
    clearTimeoutRetry();
    clearCountdown();
    invalidateLeaderboardRequests();
    state.startSequence += 1;
    state.selected = game;
    state.run = null;
    state.round = null;
    state.roundNumber = 0;
    state.busy = false;
    showView('game');
    showState('briefing');
    document.body.dataset.category = categoryClass(game.category);
    dom.stageCategory.textContent = game.category;
    dom.stageTitle.textContent = game.name;
    dom.stageRules.textContent = game.rules;
    dom.briefingIcon.textContent = iconBySlug[slug] || '•';
    dom.briefingTitle.textContent = game.name;
    dom.briefingDescription.textContent = game.description || game.rules;
    dom.briefingFeedback.textContent = '';
    dom.briefingFeedback.hidden = true;
    dom.runStatus.textContent = 'Test setup';
    updateHud({
        score: 0,
        lives: 3,
        max_lives: 3,
        level: 1,
        level_progress: 0,
        level_goal: 3,
        max_level: 5,
    });
    dom.roundValue.textContent = 'Ready';
    dom.cycleTrack.replaceChildren();
    setTimingControlsDisabled(false);
    setFeedback('', 'neutral');
    if (!options.fromHistory) {
        updateHistory(slug, options.replaceHistory);
    }
    window.setTimeout(() => dom.startRunButton?.focus(), 0);
}


function clearPreviewTimer() {
    if (state.preview.timer !== null) {
        window.clearTimeout(state.preview.timer);
        state.preview.timer = null;
    }
    if (state.preview.startFrame !== null) {
        window.cancelAnimationFrame(state.preview.startFrame);
        state.preview.startFrame = null;
    }
    state.preview.roundId = null;
    state.preview.totalMs = 0;
    state.preview.remainingMs = 0;
    state.preview.lastTick = null;
    state.preview.paused = false;
}


function clearTransitionTimer() {
    if (state.transitionTimer) {
        window.clearTimeout(state.transitionTimer);
        state.transitionTimer = null;
    }
}


function clearPendingFeedback() {
    if (state.pendingTimer) {
        window.clearTimeout(state.pendingTimer);
        state.pendingTimer = null;
    }
    state.pendingRoundId = null;
    if (state.pendingControl) {
        state.pendingControl.removeAttribute('data-submitted');
        state.pendingControl = null;
    }
    dom.answerForm?.setAttribute('aria-busy', 'false');
}


function clearTimeoutRetry() {
    if (state.timeoutRetry.timer !== null) {
        window.clearTimeout(state.timeoutRetry.timer);
    }
    state.timeoutRetry.timer = null;
    state.timeoutRetry.runId = null;
    state.timeoutRetry.roundId = null;
    state.timeoutRetry.startSequence = null;
    state.timeoutRetry.attempts = 0;
    state.timeoutRetry.mode = null;
}


function updateHud(run = state.run) {
    if (!run) {
        return;
    }
    dom.scoreValue.textContent = String(run.score ?? 0);
    const maxLives = Math.max(1, Number(run.max_lives ?? 3));
    const lives = Math.max(
        0,
        Math.min(maxLives, Number(run.lives ?? maxLives)),
    );
    dom.livesValue.textContent = (
        `${'♥'.repeat(lives)}${'♡'.repeat(maxLives - lives)}`
    );
    dom.livesValue.setAttribute(
        'aria-label',
        `${lives} of ${maxLives} lives remaining`,
    );

    const maxLevel = Math.max(1, Number(run.max_level ?? 5));
    const level = Math.max(
        1,
        Math.min(maxLevel, Number(run.level ?? state.round?.level ?? 1)),
    );
    const levelGoal = Math.max(1, Number(run.level_goal ?? 3));
    const levelProgress = Math.max(
        0,
        Math.min(levelGoal, Number(run.level_progress ?? 0)),
    );
    dom.levelValue.textContent = `${level}/${maxLevel}`;
    dom.levelValue.setAttribute(
        'aria-label',
        `Level ${level} of ${maxLevel}`,
    );
    dom.levelProgress.textContent = `${levelProgress}/${levelGoal}`;
    dom.levelProgress.setAttribute(
        'aria-label',
        level >= maxLevel
            ? `${levelProgress} of ${levelGoal} correct answers at Level ${level}`
            : `${levelProgress} of ${levelGoal} correct answers toward the next level`,
    );
}


function cancelCountdownFrames() {
    if (state.countdown.frame !== null) {
        window.cancelAnimationFrame(state.countdown.frame);
        state.countdown.frame = null;
    }
    if (state.countdown.startFrame !== null) {
        window.cancelAnimationFrame(state.countdown.startFrame);
        state.countdown.startFrame = null;
    }
}


function clearCountdown(options = {}) {
    const preserveTimerSlot = options.preserveTimerSlot === true;
    const snapshot = {
        roundId: state.countdown.roundId,
        totalMs: state.countdown.totalMs,
        remainingMs: state.countdown.remainingMs,
    };
    cancelCountdownFrames();
    state.countdown.roundId = null;
    state.countdown.totalMs = 0;
    state.countdown.remainingMs = 0;
    state.countdown.lastTick = null;
    state.countdown.paused = false;
    state.countdown.lowTimeAnnounced = false;
    state.countdown.renderedTenths = null;
    if (dom.roundTimer) {
        if (!preserveTimerSlot) {
            dom.roundTimer.hidden = true;
            dom.roundTimer.removeAttribute('data-low-time');
        }
    }
    if (dom.timerAnnouncement) {
        dom.timerAnnouncement.textContent = '';
    }
    return snapshot;
}


function updateCountdownDisplay() {
    const remainingMs = Math.max(0, state.countdown.remainingMs);
    const totalMs = Math.max(1, state.countdown.totalMs);
    const tenths = Math.ceil(remainingMs / 100);
    if (tenths !== state.countdown.renderedTenths) {
        const timeText = remainingMs <= 10000
            ? `${(tenths / 10).toFixed(1)}s`
            : `${Math.ceil(remainingMs / 1000)}s`;
        dom.timerText.textContent = timeText;
        state.countdown.renderedTenths = tenths;
    }
    dom.timerProgress.max = totalMs;
    dom.timerProgress.value = remainingMs;
    dom.timerProgress.setAttribute(
        'aria-valuetext',
        `${Math.ceil(remainingMs / 1000)} seconds remaining`,
    );

    const lowTimeThreshold = Math.min(
        5000,
        Math.max(2000, totalMs * 0.25),
    );
    if (
        !state.countdown.lowTimeAnnounced
        && remainingMs > 0
        && remainingMs <= lowTimeThreshold
    ) {
        state.countdown.lowTimeAnnounced = true;
        dom.roundTimer.dataset.lowTime = 'true';
        dom.timerAnnouncement.textContent = (
            `${Math.max(1, Math.ceil(remainingMs / 1000))} seconds remaining.`
        );
    }
}


function countdownTick(timestamp) {
    const countdown = state.countdown;
    if (
        !countdown.roundId
        || countdown.roundId !== state.round?.round_id
    ) {
        clearCountdown();
        return;
    }
    if (document.visibilityState === 'hidden') {
        countdown.frame = null;
        countdown.lastTick = null;
        countdown.paused = true;
        return;
    }

    const elapsed = countdown.lastTick === null
        ? 0
        : Math.max(0, timestamp - countdown.lastTick);
    countdown.lastTick = timestamp;
    countdown.remainingMs = Math.max(0, countdown.remainingMs - elapsed);
    updateCountdownDisplay();

    if (countdown.remainingMs <= 0) {
        countdown.frame = null;
        countdown.lastTick = null;
        if (!state.busy && countdown.roundId === state.round?.round_id) {
            submitAnswer(TIMEOUT_ANSWER, null, {timedOut: true});
        }
        return;
    }
    countdown.frame = window.requestAnimationFrame(countdownTick);
}


function beginCountdown() {
    if (
        !state.countdown.roundId
        || state.countdown.roundId !== state.round?.round_id
        || state.busy
    ) {
        return;
    }
    if (document.visibilityState === 'hidden') {
        state.countdown.paused = true;
        return;
    }
    state.countdown.paused = false;
    state.countdown.lastTick = window.performance.now();
    state.countdown.frame = window.requestAnimationFrame(countdownTick);
}


function scheduleCountdownStart(round, remainingOverride = null) {
    clearCountdown();
    const totalMs = Math.max(0, Number(round.time_limit_ms || 0));
    if (
        totalMs <= 0
        || selectedTimingMode() === 'self-paced'
        || round.round_id !== state.round?.round_id
    ) {
        return;
    }
    state.countdown.roundId = round.round_id;
    state.countdown.totalMs = totalMs;
    state.countdown.remainingMs = Math.max(
        0,
        Math.min(totalMs, Number(remainingOverride ?? totalMs)),
    );
    state.countdown.lowTimeAnnounced = false;
    state.countdown.renderedTenths = null;
    dom.roundTimer.hidden = false;
    updateCountdownDisplay();

    if (document.visibilityState === 'hidden') {
        state.countdown.paused = true;
        return;
    }

    // Two animation frames guarantee the challenge and focused answer control
    // have painted before any of the player's response time is consumed.
    state.countdown.startFrame = window.requestAnimationFrame(() => {
        state.countdown.startFrame = window.requestAnimationFrame(() => {
            state.countdown.startFrame = null;
            beginCountdown();
        });
    });
}


function pauseCountdownForVisibility() {
    const countdown = state.countdown;
    if (!countdown.roundId) {
        return;
    }
    if (countdown.lastTick !== null) {
        const elapsed = Math.max(
            0,
            window.performance.now() - countdown.lastTick,
        );
        countdown.remainingMs = Math.max(
            0,
            countdown.remainingMs - elapsed,
        );
        updateCountdownDisplay();
    }
    cancelCountdownFrames();
    countdown.lastTick = null;
    countdown.paused = true;
}


function resumeCountdownFromVisibility() {
    const countdown = state.countdown;
    if (
        !countdown.roundId
        || !countdown.paused
        || countdown.roundId !== state.round?.round_id
        || state.busy
    ) {
        return;
    }
    countdown.paused = false;
    if (countdown.remainingMs <= 0) {
        submitAnswer(TIMEOUT_ANSWER, null, {timedOut: true});
        return;
    }
    countdown.startFrame = window.requestAnimationFrame(() => {
        countdown.startFrame = null;
        beginCountdown();
    });
}


async function startRun() {
    if (!state.selected || state.busy) {
        return;
    }
    clearPreviewTimer();
    clearTransitionTimer();
    clearPendingFeedback();
    clearTimeoutRetry();
    clearCountdown();
    const selectedSlug = state.selected.slug;
    const timingMode = selectedTimingMode();
    const requestSequence = state.startSequence + 1;
    state.startSequence = requestSequence;
    state.busy = true;
    dom.startRunButton.disabled = true;
    setTimingControlsDisabled(true);
    dom.briefingFeedback.textContent = '';
    dom.briefingFeedback.hidden = true;
    audio.unlock();
    audio.cue('start');
    try {
        const payload = await api('/api/runs', {
            method: 'POST',
            body: JSON.stringify({
                game: state.selected.slug,
                player: currentPlayerName(),
                timing_mode: timingMode,
            }),
        });
        const createdRun = unwrapRun(payload);
        if (
            requestSequence !== state.startSequence
            || state.selected?.slug !== selectedSlug
        ) {
            try {
                await api(
                    `/api/runs/${encodeURIComponent(createdRun.run_id)}/quit`,
                    {method: 'POST', body: JSON.stringify({})},
                );
            } catch (_error) {
                // A stale start must not pull the player back into the stage.
            }
            return;
        }
        state.run = createdRun;
        state.roundNumber = 0;
        dom.runStatus.textContent = createdRun.ranked === false
            ? 'Practice run'
            : 'Ranked test';
        showState('active');
        updateHud();
        renderRound(state.run.round);
    } catch (error) {
        if (requestSequence === state.startSequence) {
            dom.briefingFeedback.textContent = error.message;
            dom.briefingFeedback.hidden = false;
        }
    } finally {
        if (requestSequence === state.startSequence) {
            state.busy = false;
            dom.startRunButton.disabled = false;
            setTimingControlsDisabled(false);
        }
    }
}


function setFeedback(message, tone = 'neutral') {
    if (!dom.feedbackRegion) {
        return;
    }
    dom.feedbackRegion.textContent = message;
    dom.feedbackRegion.dataset.tone = tone;
}


function choiceLabel(choice) {
    if (typeof choice === 'string') {
        const pretty = choice.charAt(0).toUpperCase() + choice.slice(1);
        return {value: choice, label: pretty, shortcut: choice.charAt(0)};
    }
    return {
        value: choice.value,
        label: choice.label || String(choice.value),
        shortcut: choice.shortcut || '',
    };
}


function renderChoices(choices) {
    dom.choiceControls.replaceChildren();
    const hasChoices = Array.isArray(choices) && choices.length > 0;
    dom.choiceControls.hidden = !hasChoices;
    dom.answerRow.hidden = hasChoices;
    dom.answerForm.hidden = false;
    if (!hasChoices) {
        return;
    }
    choices.forEach((rawChoice) => {
        const choice = choiceLabel(rawChoice);
        const button = createTextElement(
            'button',
            'choice-button',
            choice.label,
        );
        button.type = 'button';
        button.dataset.value = choice.value;
        button.dataset.shortcut = String(choice.shortcut).toLowerCase();
        if (choice.shortcut) {
            button.setAttribute(
                'aria-keyshortcuts',
                String(choice.shortcut).toUpperCase(),
            );
            button.append(
                createTextElement(
                    'span',
                    'choice-button__shortcut',
                    choice.shortcut,
                ),
            );
        }
        button.addEventListener(
            'click',
            () => submitAnswer(choice.value, button),
        );
        dom.choiceControls.append(button);
    });
}


function visualTokenText(token) {
    if (token === null || token === undefined) {
        return '';
    }
    if (typeof token !== 'object') {
        return String(token);
    }
    const directValue = (
        token.glyph
        ?? token.symbol
        ?? token.value
        ?? token.label
        ?? token.character
    );
    if (directValue !== null && directValue !== undefined) {
        return String(directValue);
    }

    const direction = String(token.direction || '').toLowerCase();
    const directionGlyphs = {
        up: '↑',
        north: '↑',
        'up-right': '↗',
        northeast: '↗',
        'north-east': '↗',
        right: '→',
        east: '→',
        'down-right': '↘',
        southeast: '↘',
        'south-east': '↘',
        down: '↓',
        south: '↓',
        'down-left': '↙',
        southwest: '↙',
        'south-west': '↙',
        left: '←',
        west: '←',
        'up-left': '↖',
        northwest: '↖',
        'north-west': '↖',
    };
    if (directionGlyphs[direction]) {
        return directionGlyphs[direction];
    }

    const angle = Number(token.angle ?? token.rotation);
    if (Number.isFinite(angle)) {
        const arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'];
        const index = Math.round((((angle % 360) + 360) % 360) / 45) % 8;
        return arrows[index];
    }
    return '•';
}


function directionVisualData(data) {
    let arrows = (
        (Array.isArray(data.items) && data.items.length > 0)
            ? data.items
            : (data.arrows ?? data.grid ?? [])
    );
    if (!Array.isArray(arrows)) {
        arrows = [];
    }
    const nested = Array.isArray(arrows[0]);
    const flattened = nested ? arrows.flat() : arrows;
    let columns = Number(
        data.columns
        ?? data.grid_columns
        ?? data.grid_size
        ?? (nested ? arrows[0]?.length : 0),
    );
    if (!Number.isFinite(columns) || columns < 1) {
        const square = Math.sqrt(flattened.length);
        columns = Number.isInteger(square) ? square : 0;
    }
    return {
        arrows: flattened,
        columns: Math.max(0, Math.min(6, Math.round(columns))),
    };
}


function arrowTokenData(token) {
    const rawRotation = typeof token === 'object' && token !== null
        ? token.rotation_deg ?? token.angle ?? token.rotation
        : null;
    const numericRotation = Number(rawRotation);
    if (rawRotation !== null && Number.isFinite(numericRotation)) {
        const rotation = Math.round(
            ((numericRotation % 360) + 360) % 360,
        );
        if (SUPPORTED_ARROW_ROTATIONS.has(rotation)) {
            return {
                glyph: visualTokenText(token),
                rotation,
            };
        }
        const arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'];
        return {
            glyph: arrows[Math.round(rotation / 45) % arrows.length],
            rotation: null,
        };
    }
    return {
        glyph: visualTokenText(token),
        rotation: null,
    };
}


function symbolVisualData(data) {
    if (Array.isArray(data.sequences) && data.sequences.length >= 2) {
        return [data.sequences[0], data.sequences[1]].map((sequence) => (
            Array.isArray(sequence) ? sequence : [sequence]
        ));
    }

    const left = (
        data.left_sequence
        ?? data.left_symbols
        ?? (
            Array.isArray(data.left_tokens)
                ? data.left_tokens.map((token) => token.symbol)
                : undefined
        )
        ?? data.left
    );
    const right = (
        data.right_sequence
        ?? data.right_symbols
        ?? (
            Array.isArray(data.right_tokens)
                ? data.right_tokens.map((token) => token.symbol)
                : undefined
        )
        ?? data.right
    );
    if (left !== undefined || right !== undefined) {
        return [left, right].map((sequence) => (
            Array.isArray(sequence) ? sequence : [sequence]
        ));
    }

    if (Array.isArray(data.symbols)) {
        if (
            data.symbols.length === 2
            && data.symbols.some((symbol) => Array.isArray(symbol))
        ) {
            return data.symbols.map((sequence) => (
                Array.isArray(sequence) ? sequence : [sequence]
            ));
        }
        if (data.symbols.length === 2) {
            return [[data.symbols[0]], [data.symbols[1]]];
        }
    }
    return [[], []];
}


function symbolAccessibilityLabel(data) {
    const accessibleSequence = (tokens) => {
        if (!Array.isArray(tokens)) {
            return [];
        }
        return tokens.map((token) => (
            typeof token === 'object' && token !== null
                ? token.accessible_label || visualTokenText(token)
                : String(token)
        ));
    };
    const leftLabels = accessibleSequence(data.left_tokens);
    const rightLabels = accessibleSequence(data.right_tokens);
    if (!leftLabels.length || !rightLabels.length) {
        return null;
    }
    return (
        `Left sequence: ${leftLabels.join(', ')}. `
        + `Right sequence: ${rightLabels.join(', ')}. `
        + 'Do these symbol sequences match?'
    );
}


function renderGenericVisual(round) {
    const visual = dom.roundVisual;
    const data = round.data || {};
    const kind = round.kind || 'text';
    visual.replaceChildren();
    visual.className = `round-visual round-visual--${kind}`;
    visual.setAttribute('role', 'img');
    visual.setAttribute('aria-label', round.prompt || 'Current challenge');

    if (
        kind === 'direction'
        || Array.isArray(data.arrows)
        || Array.isArray(data.grid)
    ) {
        const directionData = directionVisualData(data);
        const itemLabels = directionData.arrows
            .map((arrow) => (
                typeof arrow === 'object' && arrow !== null
                    ? arrow.accessible_label
                    : null
            ))
            .filter((label) => (
                typeof label === 'string' && label.trim()
            ));
        const sequenceLabels = Array.isArray(data.accessible_sequence)
            ? data.accessible_sequence.filter((label) => (
                typeof label === 'string' && label.trim()
            ))
            : [];
        const accessibleDirections = (
            itemLabels.length === directionData.arrows.length
                ? itemLabels
                : sequenceLabels
        );
        if (accessibleDirections.length === directionData.arrows.length) {
            visual.setAttribute(
                'aria-label',
                `Find the odd arrow. Row by row: ${accessibleDirections.join('; ')}.`,
            );
        }
        const row = document.createElement('div');
        row.className = 'arrow-row';
        if (directionData.columns >= 2) {
            row.dataset.columns = String(directionData.columns);
        }
        row.setAttribute('aria-hidden', 'true');
        directionData.arrows.forEach((arrow) => {
            const tokenData = arrowTokenData(arrow);
            const token = document.createElement('span');
            token.className = 'arrow-token';
            if (tokenData.rotation !== null) {
                token.dataset.rotation = String(tokenData.rotation);
            }
            token.append(createTextElement(
                'span',
                'arrow-token__glyph',
                tokenData.glyph,
            ));
            row.append(token);
        });
        visual.append(row);
        return;
    }

    if (
        Array.isArray(data.symbols)
        || Array.isArray(data.sequences)
        || data.left_sequence !== undefined
        || data.left_symbols !== undefined
        || data.left_tokens !== undefined
        || data.right_tokens !== undefined
        || data.left !== undefined
        || data.right !== undefined
    ) {
        const sequences = symbolVisualData(data);
        const accessibleLabel = symbolAccessibilityLabel(data);
        if (accessibleLabel) {
            visual.setAttribute('aria-label', accessibleLabel);
        }
        const comparison = document.createElement('div');
        comparison.className = 'symbol-comparison';
        comparison.setAttribute('aria-hidden', 'true');
        sequences.forEach((sequence, index) => {
            const group = document.createElement('div');
            group.className = 'symbol-sequence';
            sequence.filter((symbol) => symbol !== null).forEach((symbol) => {
                group.append(createTextElement(
                    'span',
                    'symbol-token',
                    visualTokenText(symbol),
                ));
            });
            comparison.append(group);
            if (index === 0) {
                comparison.append(
                    createTextElement('span', 'symbol-divider', '|'),
                );
            }
        });
        visual.append(comparison);
        return;
    }

    if (Array.isArray(data.sequence)) {
        const sequence = data.sequence || [];
        const row = document.createElement('div');
        row.className = 'sequence-row';
        sequence.forEach((number) => row.append(
            createTextElement(
                'span',
                number === '..' || number === null
                    ? 'sequence-token sequence-token--missing'
                    : 'sequence-token',
                number === null ? '…' : String(number),
            ),
        ));
        visual.append(row);
        return;
    }

    if (data.scrambled) {
        const letters = data.letters
            || String(data.word || data.scrambled || '').split('');
        const scramble = document.createElement('div');
        scramble.className = 'scramble-visual';
        const row = document.createElement('div');
        row.className = 'letter-row';
        Array.from(letters).forEach((letter) => row.append(
            createTextElement('span', 'letter-tile', letter),
        ));
        scramble.append(row);
        if (data.hint) {
            scramble.append(createTextElement(
                'p',
                'scramble-hint',
                `Hint · ${data.hint}`,
            ));
        }
        visual.append(scramble);
        return;
    }

    const value = (kind === 'memory' ? round.prompt : null)
        ?? data.value
        ?? data.expression
        ?? data.number
        ?? data.word
        ?? (Array.isArray(data.numbers) ? data.numbers.join('  ·  ') : null)
        ?? round.display
        ?? '';
    visual.append(createTextElement('div', 'prompt-value', String(value)));
}


function updateCycle(round) {
    dom.cycleTrack.replaceChildren();
    const total = Number(round.cycle_total || 0);
    const position = Number(round.cycle_position || 0);
    if (!total || state.selected?.slug !== 'culmination') {
        dom.cycleTrack.hidden = true;
        return;
    }
    dom.cycleTrack.hidden = false;
    for (let index = 1; index <= total; index += 1) {
        const segment = document.createElement('span');
        segment.className = 'cycle-segment';
        if (index < position) {
            segment.dataset.state = 'complete';
        } else if (index === position) {
            segment.dataset.state = 'current';
        }
        segment.setAttribute('aria-hidden', 'true');
        dom.cycleTrack.append(segment);
    }
    dom.cycleTrack.setAttribute(
        'aria-label',
        `Culmination cycle round ${position} of ${total}`,
    );
}


function revealMemoryAnswer(round) {
    if (state.round?.round_id !== round.round_id) {
        return;
    }
    if (
        state.preview.roundId
        && state.preview.roundId !== round.round_id
    ) {
        return;
    }
    clearPreviewTimer();
    dom.roundVisual.classList.add('is-hidden');
    dom.roundVisual.setAttribute('aria-hidden', 'true');
    dom.roundVisual.removeAttribute('aria-label');
    dom.roundVisual.replaceChildren();
    dom.memoryCurtain.hidden = false;
    const hiddenPrompt = round.hidden_prompt || 'What did you see?';
    const curtainDots = createTextElement('span', '', '● ● ●');
    curtainDots.setAttribute('aria-hidden', 'true');
    dom.memoryCurtain.replaceChildren(
        curtainDots,
        createTextElement('strong', '', hiddenPrompt),
    );
    dom.roundPrompt.textContent = hiddenPrompt;
    dom.answerForm.hidden = false;
    dom.choiceControls.hidden = true;
    dom.answerRow.hidden = false;
    dom.answerInput.value = '';
    dom.answerInput.inputMode = 'numeric';
    dom.answerInput.focus({preventScroll: true});
    scheduleCountdownStart(round);
}


function memoryPreviewMatches(roundId) {
    return (
        state.preview.roundId === roundId
        && state.round?.round_id === roundId
        && dom.answerForm.hidden
    );
}


function beginMemoryPreviewTimer(roundId) {
    const preview = state.preview;
    if (!memoryPreviewMatches(roundId)) {
        return;
    }
    if (document.visibilityState === 'hidden') {
        preview.paused = true;
        return;
    }
    if (preview.remainingMs <= 0) {
        revealMemoryAnswer(state.round);
        return;
    }

    preview.paused = false;
    preview.lastTick = window.performance.now();
    preview.timer = window.setTimeout(() => {
        preview.timer = null;
        if (!memoryPreviewMatches(roundId)) {
            return;
        }
        const elapsed = Math.max(
            0,
            window.performance.now() - preview.lastTick,
        );
        preview.remainingMs = Math.max(0, preview.remainingMs - elapsed);
        preview.lastTick = null;
        if (preview.remainingMs > 0) {
            beginMemoryPreviewTimer(roundId);
            return;
        }
        revealMemoryAnswer(state.round);
    }, preview.remainingMs);
}


function scheduleMemoryPreviewAfterPaint(roundId, paintedFrames = 0) {
    if (!memoryPreviewMatches(roundId)) {
        return;
    }
    if (document.visibilityState === 'hidden') {
        state.preview.paused = true;
        return;
    }
    state.preview.startFrame = window.requestAnimationFrame(() => {
        state.preview.startFrame = null;
        if (!memoryPreviewMatches(roundId)) {
            return;
        }
        if (paintedFrames < 2) {
            scheduleMemoryPreviewAfterPaint(roundId, paintedFrames + 1);
            return;
        }
        beginMemoryPreviewTimer(roundId);
    });
}


function pauseMemoryPreviewForVisibility() {
    const preview = state.preview;
    if (!preview.roundId) {
        return;
    }
    if (preview.lastTick !== null) {
        const elapsed = Math.max(
            0,
            window.performance.now() - preview.lastTick,
        );
        preview.remainingMs = Math.max(0, preview.remainingMs - elapsed);
    }
    if (preview.timer !== null) {
        window.clearTimeout(preview.timer);
        preview.timer = null;
    }
    if (preview.startFrame !== null) {
        window.cancelAnimationFrame(preview.startFrame);
        preview.startFrame = null;
    }
    preview.lastTick = null;
    preview.paused = true;
}


function resumeMemoryPreviewFromVisibility() {
    const preview = state.preview;
    if (
        !preview.roundId
        || !preview.paused
        || !memoryPreviewMatches(preview.roundId)
    ) {
        return;
    }
    preview.paused = false;
    scheduleMemoryPreviewAfterPaint(preview.roundId);
}


function startMemoryPreview(round) {
    clearPreviewTimer();
    const delay = Math.max(300, Number(round.preview_ms || 1500));
    state.preview.roundId = round.round_id;
    state.preview.totalMs = delay;
    state.preview.remainingMs = delay;
    state.preview.paused = document.visibilityState === 'hidden';
    dom.roundPrompt.textContent = instructionBySlug[round.source_slug]
        || 'Memorize this.';
    dom.memoryCurtain.hidden = true;
    dom.answerForm.hidden = true;
    if (!state.preview.paused) {
        scheduleMemoryPreviewAfterPaint(round.round_id);
    }
}


function renderRound(round) {
    if (!round) {
        return;
    }
    clearPreviewTimer();
    clearPendingFeedback();
    clearTimeoutRetry();
    clearCountdown();
    state.round = round;
    state.roundNumber += 1;
    state.busy = false;
    dom.activeState.dataset.feedback = 'idle';
    delete dom.activeState.dataset.levelUp;
    dom.roundSource.textContent = round.source_name || state.selected.name;
    dom.roundSource.dataset.category = categoryClass(
        round.source_category || state.selected.category,
    );
    const roundLevel = Number(round.level ?? state.run?.level ?? 1);
    const difficulty = round.difficulty_label || 'Foundation';
    dom.difficultyLabel.textContent = `Level ${roundLevel} · ${difficulty}`;
    dom.roundPrompt.textContent = instructionBySlug[round.source_slug]
        || round.prompt
        || round.rules;
    dom.stageRules.textContent = round.rules || state.selected.rules;
    dom.roundValue.textContent = String(state.roundNumber);
    dom.answerInput.value = '';
    dom.answerInput.disabled = false;
    dom.submitAnswer.disabled = false;
    dom.answerForm.setAttribute('aria-busy', 'false');
    dom.choiceControls.querySelectorAll('button').forEach((button) => {
        button.disabled = false;
    });
    dom.memoryCurtain.hidden = true;
    dom.roundVisual.classList.remove('is-hidden');
    dom.roundVisual.removeAttribute('aria-hidden');
    setFeedback('', 'neutral');
    updateCycle(round);
    renderGenericVisual(round);
    renderChoices(round.choices || []);

    if (Number(round.preview_ms || 0) > 0) {
        startMemoryPreview(round);
        return;
    }

    const numericGames = new Set([
        'calc', 'gcd', 'progression', 'number-memory',
    ]);
    dom.answerInput.inputMode = numericGames.has(round.source_slug)
        ? 'numeric'
        : 'text';
    dom.answerInput.autocomplete = 'off';
    const firstChoice = dom.choiceControls.querySelector('button');
    const focusTarget = firstChoice || dom.answerInput;
    focusTarget.focus({preventScroll: true});
    scheduleCountdownStart(round);
}


function setControlsDisabled(disabled) {
    dom.answerInput.disabled = disabled;
    dom.submitAnswer.disabled = disabled;
    dom.choiceControls.querySelectorAll('button').forEach((button) => {
        button.disabled = disabled;
    });
}


function currentEnabledAnswerControl() {
    if (
        !state.run
        || !state.round
        || state.busy
        || dom.gameView.hidden
        || dom.activeState.hidden
        || dom.answerForm.hidden
    ) {
        return null;
    }
    const choice = dom.choiceControls.querySelector(
        'button:not(:disabled)',
    );
    if (!dom.choiceControls.hidden && choice) {
        return choice;
    }
    if (!dom.answerRow.hidden && !dom.answerInput.disabled) {
        return dom.answerInput;
    }
    return null;
}


function restoreCurrentAnswerFocus() {
    if (state.focusRestoreFrame !== null) {
        window.cancelAnimationFrame(state.focusRestoreFrame);
    }
    const runId = state.run?.run_id;
    const roundId = state.round?.round_id;
    state.focusRestoreFrame = window.requestAnimationFrame(() => {
        state.focusRestoreFrame = null;
        if (
            state.run?.run_id !== runId
            || state.round?.round_id !== roundId
        ) {
            return;
        }
        currentEnabledAnswerControl()?.focus({preventScroll: true});
    });
}


function beginPendingFeedback(control, roundId, timedOut) {
    clearPendingFeedback();
    state.pendingRoundId = roundId;
    state.pendingControl = control;
    if (control) {
        control.dataset.submitted = 'true';
    }
    dom.answerForm.setAttribute('aria-busy', 'true');
    dom.activeState.dataset.feedback = 'pending';
    setFeedback(
        timedOut ? 'Time is up — checking…' : 'Checking…',
        'pending',
    );
    if (!timedOut) {
        audio.cue('click');
    }
    state.pendingTimer = window.setTimeout(() => {
        state.pendingTimer = null;
        if (
            state.busy
            && state.pendingRoundId === roundId
            && state.round?.round_id === roundId
        ) {
            setFeedback(
                timedOut
                    ? 'Time is up — still checking…'
                    : 'Still checking…',
                'pending',
            );
        }
    }, STILL_CHECKING_DELAY);
}


function waitForInputPaint() {
    return new Promise((resolve) => {
        window.requestAnimationFrame(() => resolve());
    });
}


function timeoutRetryMatches(runId, roundId, startSequence) {
    return (
        state.timeoutRetry.runId === runId
        && state.timeoutRetry.roundId === roundId
        && state.timeoutRetry.startSequence === startSequence
        && state.run?.run_id === runId
        && state.round?.round_id === roundId
        && state.startSequence === startSequence
        && state.run.ended !== true
    );
}


function lockTimedOutRound(runId, roundId, startSequence) {
    clearTimeoutRetry();
    state.timeoutRetry.runId = runId;
    state.timeoutRetry.roundId = roundId;
    state.timeoutRetry.startSequence = startSequence;
}


function returnExpiredRunToBriefing(runId, roundId, startSequence) {
    if (!timeoutRetryMatches(runId, roundId, startSequence)) {
        return;
    }
    const game = state.selected?.slug;
    clearPendingFeedback();
    clearTimeoutRetry();
    state.busy = false;
    if (!game) {
        return;
    }
    openBriefing(game, {replaceHistory: true});
    dom.briefingFeedback.textContent = (
        'That run expired while reconnecting. Start a new test when ready.'
    );
    dom.briefingFeedback.hidden = false;
}


function scheduleTimedOutRetry(
        runId,
        roundId,
        startSequence,
        mode = 'answer',
) {
    if (!timeoutRetryMatches(runId, roundId, startSequence)) {
        return;
    }
    if (state.timeoutRetry.timer !== null) {
        window.clearTimeout(state.timeoutRetry.timer);
    }
    const delayIndex = Math.min(
        state.timeoutRetry.attempts,
        TIMEOUT_RETRY_DELAYS.length - 1,
    );
    const delay = TIMEOUT_RETRY_DELAYS[delayIndex];
    state.timeoutRetry.attempts += 1;
    state.timeoutRetry.mode = mode;
    state.busy = false;
    setControlsDisabled(true);
    dom.answerForm.setAttribute('aria-busy', 'true');
    dom.activeState.dataset.feedback = 'pending';
    setFeedback(
        mode === 'recover'
            ? 'Time is up — reconnecting to your result…'
            : 'Time is up — connection interrupted. Retrying…',
        'pending',
    );
    state.timeoutRetry.timer = window.setTimeout(() => {
        state.timeoutRetry.timer = null;
        if (
            !timeoutRetryMatches(runId, roundId, startSequence)
            || state.timeoutRetry.mode !== mode
        ) {
            return;
        }
        if (mode === 'recover') {
            recoverTimedOutRun(runId, roundId, startSequence);
        } else {
            submitAnswer(TIMEOUT_ANSWER, null, {
                timedOut: true,
                retry: true,
            });
        }
    }, delay);
}


async function recoverTimedOutRun(runId, roundId, startSequence) {
    if (
        !timeoutRetryMatches(runId, roundId, startSequence)
        || state.busy
    ) {
        return;
    }
    state.busy = true;
    setControlsDisabled(true);
    dom.answerForm.setAttribute('aria-busy', 'true');
    dom.activeState.dataset.feedback = 'pending';
    setFeedback('Time is up — recovering your result…', 'pending');
    try {
        const payload = await api(
            `/api/runs/${encodeURIComponent(runId)}/quit`,
            {method: 'POST', body: JSON.stringify({})},
        );
        if (!timeoutRetryMatches(runId, roundId, startSequence)) {
            return;
        }
        const recoveredRun = unwrapRun(payload);
        clearPendingFeedback();
        clearTimeoutRetry();
        state.run = {
            ...state.run,
            ...recoveredRun,
            ended: true,
        };
        await finishRun(state.run);
    } catch (error) {
        if (!timeoutRetryMatches(runId, roundId, startSequence)) {
            return;
        }
        clearPendingFeedback();
        state.busy = false;
        setControlsDisabled(true);
        if (error.status >= 400 && error.status < 500) {
            returnExpiredRunToBriefing(runId, roundId, startSequence);
            return;
        }
        scheduleTimedOutRetry(
            runId,
            roundId,
            startSequence,
            'recover',
        );
    }
}


async function submitAnswer(answer, control = null, options = {}) {
    if (!state.run || !state.round || state.busy) {
        return;
    }
    const value = String(answer ?? '').trim();
    const timedOut = options.timedOut === true || value === TIMEOUT_ANSWER;
    if (
        !timedOut
        && state.timeoutRetry.roundId === state.round.round_id
    ) {
        setControlsDisabled(true);
        return;
    }
    if (!value && !timedOut) {
        setFeedback('Enter an answer first.', 'wrong');
        dom.answerInput.focus();
        return;
    }

    state.busy = true;
    clearPreviewTimer();
    const countdownSnapshot = clearCountdown({preserveTimerSlot: true});
    const submittedControl = control;
    const runId = state.run.run_id;
    const roundId = state.round.round_id;
    const requestSequence = state.startSequence;
    if (timedOut) {
        if (options.retry === true) {
            if (!timeoutRetryMatches(runId, roundId, requestSequence)) {
                state.busy = false;
                return;
            }
        } else {
            lockTimedOutRound(runId, roundId, requestSequence);
        }
    }
    beginPendingFeedback(submittedControl, roundId, timedOut);
    setControlsDisabled(true);

    // Let the pressed state and checking message paint before network work.
    await waitForInputPaint();
    if (
        state.run?.run_id !== runId
        || state.round?.round_id !== roundId
        || state.startSequence !== requestSequence
        || !state.busy
    ) {
        return;
    }

    try {
        const payload = await api(
            `/api/runs/${encodeURIComponent(runId)}/answers`,
            {
                method: 'POST',
                body: JSON.stringify({
                    round_id: roundId,
                    answer: value,
                }),
            },
        );
        if (
            state.run?.run_id !== runId
            || state.round?.round_id !== roundId
            || state.startSequence !== requestSequence
        ) {
            return;
        }
        clearTimeoutRetry();
        clearPendingFeedback();
        const runResult = unwrapRun(payload);
        const grading = runResult.result || payload.result || {};
        state.run = {...state.run, ...runResult};
        updateHud();
        const sourceName = state.round.source_name || state.selected.name;
        if (grading.correct) {
            dom.activeState.dataset.feedback = 'correct';
            if (grading.leveled_up) {
                dom.activeState.dataset.levelUp = 'true';
                setFeedback(
                    `${sourceName}: correct — Level ${grading.level_after ?? runResult.level} unlocked.`,
                    'correct',
                );
            } else {
                setFeedback(
                    `${sourceName}: correct — one point added.`,
                    'correct',
                );
            }
            audio.cue('correct');
        } else {
            dom.activeState.dataset.feedback = 'wrong';
            const expected = grading.expected_answer;
            const message = grading.timed_out
                ? `${sourceName}: time ran out. The answer was ${expected}.`
                : `${sourceName}: not quite. The answer was ${expected}.`;
            setFeedback(message, 'wrong');
            audio.cue('wrong');
        }

        if (runResult.game_over || runResult.ended || !runResult.round) {
            const completedRunId = state.run.run_id;
            state.transitionTimer = window.setTimeout(
                () => {
                    state.transitionTimer = null;
                    if (state.run?.run_id === completedRunId) {
                        finishRun(runResult);
                    }
                },
                FEEDBACK_DELAY + 120,
            );
        } else {
            const activeRunId = state.run.run_id;
            state.transitionTimer = window.setTimeout(
                () => {
                    state.transitionTimer = null;
                    if (state.run?.run_id === activeRunId) {
                        renderRound(runResult.round);
                    }
                },
                FEEDBACK_DELAY,
            );
        }
    } catch (error) {
        if (
            state.run?.run_id !== runId
            || state.round?.round_id !== roundId
            || state.startSequence !== requestSequence
        ) {
            return;
        }
        clearPendingFeedback();
        if (timedOut) {
            state.busy = false;
            setControlsDisabled(true);
            if (!timeoutRetryMatches(runId, roundId, requestSequence)) {
                return;
            }
            if (error.status === 404) {
                returnExpiredRunToBriefing(
                    runId,
                    roundId,
                    requestSequence,
                );
                return;
            }
            if (error.status >= 400 && error.status < 500) {
                await recoverTimedOutRun(
                    runId,
                    roundId,
                    requestSequence,
                );
                return;
            }
            scheduleTimedOutRetry(
                runId,
                roundId,
                requestSequence,
            );
            return;
        }
        state.busy = false;
        setControlsDisabled(false);
        dom.activeState.dataset.feedback = 'wrong';
        setFeedback(error.message, 'wrong');
        if (error.status === 409) {
            setFeedback(
                'That round has already ended. Return to the menu.',
                'wrong',
            );
        } else if (
            countdownSnapshot.roundId === roundId
            && countdownSnapshot.remainingMs > 0
        ) {
            scheduleCountdownStart(
                state.round,
                countdownSnapshot.remainingMs,
            );
        }
        submittedControl?.focus({preventScroll: true});
    }
}


function resultRunIsCurrent(runId, game, startSequence) {
    return (
        state.run?.run_id === runId
        && state.run.ended === true
        && state.selected?.slug === game
        && state.startSequence === startSequence
        && state.busy === false
        && !dom.gameView.hidden
        && !dom.resultState.hidden
    );
}


async function finishRun(result) {
    clearPreviewTimer();
    clearPendingFeedback();
    clearTimeoutRetry();
    clearCountdown();
    state.busy = false;
    const completedRunId = state.run.run_id;
    const completedGame = state.selected.slug;
    const completedStartSequence = state.startSequence;
    const resultIsCurrent = () => resultRunIsCurrent(
        completedRunId,
        completedGame,
        completedStartSequence,
    );
    const score = Number(result.score ?? state.run.score ?? 0);
    const previousBest = state.personalBests.get(completedGame);
    const ranked = state.run.ranked !== false;
    const isBest = ranked && (
        previousBest === undefined || score > previousBest
    );
    state.run.score = score;
    state.run.lives = Number(result.lives ?? 0);
    state.run.ended = true;
    dom.runStatus.textContent = 'Test complete';
    showState('result');
    dom.resultScore.textContent = String(score);
    dom.resultBest.textContent = isBest
        ? `${score} NEW`
        : String(previousBest ?? '—');
    dom.resultBest.dataset.best = String(isBest);
    const remainingLives = Math.max(
        0,
        Number(result.lives ?? state.run.lives ?? 0),
    );
    const endedEarly = Boolean(
        result.quit_early ?? state.run.quit_early,
    ) || remainingLives > 0;
    let resultMessage;
    if (endedEarly) {
        resultMessage = (
            `This run ended early with ${score} `
            + `${score === 1 ? 'point' : 'points'} and ${remainingLives} `
            + `${remainingLives === 1 ? 'life' : 'lives'} remaining.`
        );
    } else {
        resultMessage = score === 0
            ? 'Every baseline starts somewhere. Take another run.'
            : `You cleared ${score} ${score === 1 ? 'round' : 'rounds'} before losing three lives.`;
    }
    dom.resultMessage.textContent = ranked
        ? resultMessage
        : `${resultMessage} Practice scores are not ranked.`;
    if (dom.resultAverage) {
        dom.resultAverage.textContent = '…';
    }
    if (dom.resultPercentile) {
        dom.resultPercentile.textContent = '…';
    }
    if (dom.resultRank) {
        dom.resultRank.textContent = '…';
    }
    if (isBest) {
        audio.cue('best');
    } else {
        audio.cue('gameover');
    }
    window.setTimeout(() => {
        if (resultIsCurrent()) {
            dom.retryButton?.focus();
        }
    }, 0);
    await Promise.all([
        refreshPersonalBests({shouldApply: resultIsCurrent}),
        refreshResultBenchmark(completedGame, score, resultIsCurrent),
    ]);
}


function ordinal(number) {
    const value = Number(number);
    const mod100 = value % 100;
    if (mod100 >= 11 && mod100 <= 13) {
        return `${value}th`;
    }
    const suffix = {1: 'st', 2: 'nd', 3: 'rd'}[value % 10] || 'th';
    return `${value}${suffix}`;
}


async function refreshResultBenchmark(game, score, shouldApply = () => true) {
    try {
        const benchmark = await api(
            `/api/benchmarks/${encodeURIComponent(game)}?score=${score}`,
        );
        if (!shouldApply()) {
            return;
        }
        state.benchmarks.set(game, benchmark);
        if (dom.resultAverage) {
            dom.resultAverage.textContent = String(benchmark.average_score);
        }
        if (dom.resultPercentile) {
            dom.resultPercentile.textContent = ordinal(benchmark.percentile);
        }
        if (dom.resultRank) {
            dom.resultRank.textContent = `${benchmark.rank_out_of_100}/100`;
        }
    } catch (_error) {
        if (!shouldApply()) {
            return;
        }
        [dom.resultAverage, dom.resultPercentile, dom.resultRank]
            .filter(Boolean)
            .forEach((element) => {
                element.textContent = '—';
            });
    }
}


async function quitRun() {
    if (!state.run || state.run.ended) {
        return;
    }
    const quittingRun = state.run;
    try {
        await api(`/api/runs/${encodeURIComponent(quittingRun.run_id)}/quit`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
    } catch (_error) {
        // Leaving the stage should not trap the player if the run expired.
    }
    if (state.run?.run_id === quittingRun.run_id) {
        state.run.ended = true;
    }
    await refreshPersonalBests();
}


async function backToHome(options = {}) {
    if (state.navigating) {
        return;
    }
    if (state.run && !state.run.ended && !options.skipConfirm) {
        const shouldLeave = window.confirm(
            'Leave this run? Your current score will be saved.',
        );
        if (!shouldLeave) {
            restoreCurrentAnswerFocus();
            return;
        }
    }
    state.navigating = true;
    invalidateLeaderboardRequests();
    clearPreviewTimer();
    clearTransitionTimer();
    clearPendingFeedback();
    clearTimeoutRetry();
    clearCountdown();
    state.startSequence += 1;
    state.busy = false;
    dom.startRunButton.disabled = false;
    try {
        await quitRun();
        state.selected = null;
        state.run = null;
        state.round = null;
        showView('home');
        showState('briefing');
        document.body.dataset.category = '';
        if (!options.fromHistory) {
            updateHistory(null, options.replaceHistory);
        }
        renderCards();
        window.setTimeout(
            () => dom.gameGrid?.querySelector('.game-card')?.focus(),
            0,
        );
    } finally {
        state.navigating = false;
    }
}


async function refreshPersonalBests(options = {}) {
    const shouldApply = options.shouldApply || (() => true);
    try {
        const playerName = currentPlayerName();
        const payload = await api(
            `/api/leaderboard?player=${encodeURIComponent(playerName)}&limit=100`,
        );
        if (!shouldApply()) {
            return;
        }
        const entries = unwrapLeaders(payload);
        const player = playerName.toLocaleLowerCase();
        state.personalBests.clear();
        entries.forEach((entry) => {
            if (String(entry.player || '').toLocaleLowerCase() !== player) {
                return;
            }
            const current = state.personalBests.get(entry.game);
            const score = Number(entry.score || 0);
            if (current === undefined || score > current) {
                state.personalBests.set(entry.game, score);
            }
        });
        renderCards();
    } catch (_error) {
        // The games remain playable if leaderboard storage is unavailable.
    }
}


function leaderboardMessageRow(message) {
    const row = document.createElement('tr');
    row.className = 'empty-row';
    const cell = createTextElement('td', '', message);
    cell.colSpan = 4;
    row.append(cell);
    return row;
}


function invalidateLeaderboardRequests() {
    state.leaderboardRequestSequence += 1;
}


async function renderLeaderboard() {
    const requestSequence = state.leaderboardRequestSequence + 1;
    state.leaderboardRequestSequence = requestSequence;
    const game = dom.leaderboardFilter.value;
    const query = game ? `?game=${encodeURIComponent(game)}&limit=20` : '?limit=20';
    dom.leaderboardRows.replaceChildren(leaderboardMessageRow('Loading scores…'));
    try {
        const payload = await api(`/api/leaderboard${query}`);
        if (requestSequence !== state.leaderboardRequestSequence) {
            return false;
        }
        const entries = unwrapLeaders(payload);
        dom.leaderboardRows.replaceChildren();
        if (!entries.length) {
            dom.leaderboardRows.append(leaderboardMessageRow(
                'No scores yet. Your next run can be the first.',
            ));
            return true;
        }
        entries.forEach((entry, index) => {
            const row = document.createElement('tr');
            row.className = 'leaderboard-row';
            const gameName = findGame(entry.game)?.name || entry.game;
            const rankCell = document.createElement('td');
            rankCell.append(createTextElement(
                'span',
                'rank-badge',
                `#${index + 1}`,
            ));
            row.append(
                rankCell,
                createTextElement('td', 'leaderboard-player', entry.player),
                createTextElement('td', 'leaderboard-game', gameName),
                createTextElement('td', 'leaderboard-score', entry.score),
            );
            dom.leaderboardRows.append(row);
        });
        return true;
    } catch (error) {
        if (requestSequence !== state.leaderboardRequestSequence) {
            return false;
        }
        dom.leaderboardRows.replaceChildren(leaderboardMessageRow(error.message));
        return true;
    }
}


async function openLeaderboard() {
    dom.leaderboardFilter.replaceChildren();
    const allOption = new Option('All games', '');
    dom.leaderboardFilter.append(allOption);
    state.catalog.forEach((game) => {
        dom.leaderboardFilter.append(new Option(game.name, game.slug));
    });
    const rendered = await renderLeaderboard();
    if (!rendered) {
        return;
    }
    if (typeof dom.leaderboardDialog.showModal === 'function') {
        dom.leaderboardDialog.showModal();
    } else {
        dom.leaderboardDialog.hidden = false;
    }
}


function closeLeaderboard() {
    invalidateLeaderboardRequests();
    if (typeof dom.leaderboardDialog.close === 'function') {
        dom.leaderboardDialog.close();
    } else {
        dom.leaderboardDialog.hidden = true;
        restoreCurrentAnswerFocus();
    }
}


function bindEvents() {
    dom.startRunButton?.addEventListener('click', startRun);
    dom.retryButton?.addEventListener('click', startRun);
    dom.resultMenuButton?.addEventListener('click', () => backToHome());
    dom.backButton?.addEventListener('click', () => backToHome());
    dom.answerForm?.addEventListener('submit', (event) => {
        event.preventDefault();
        submitAnswer(dom.answerInput.value, dom.submitAnswer);
    });
    dom.leaderboardButton?.addEventListener('click', openLeaderboard);
    dom.closeLeaderboard?.addEventListener('click', closeLeaderboard);
    dom.leaderboardFilter?.addEventListener('change', renderLeaderboard);
    dom.leaderboardDialog?.addEventListener('click', (event) => {
        if (event.target === dom.leaderboardDialog) {
            closeLeaderboard();
        }
    });
    dom.leaderboardDialog?.addEventListener('close', () => {
        invalidateLeaderboardRequests();
        restoreCurrentAnswerFocus();
    });

    document.addEventListener('keydown', (event) => {
        if (event.repeat) {
            const focusedTag = document.activeElement?.tagName;
            const repeatIsOnActiveAnswer = (
                !dom.gameView.hidden
                && !dom.activeState.hidden
                && dom.activeState.contains(document.activeElement)
                && focusedTag !== 'INPUT'
                && focusedTag !== 'TEXTAREA'
            );
            if (repeatIsOnActiveAnswer) {
                event.preventDefault();
            }
            return;
        }
        if (event.target?.closest?.('#themeSelect')) {
            return;
        }
        if (event.key === 'Escape' && dom.leaderboardDialog?.open) {
            return;
        }
        if (event.key === 'Escape' && !dom.gameView.hidden) {
            event.preventDefault();
            backToHome();
            return;
        }
        if (dom.gameView.hidden || dom.activeState.hidden || state.busy) {
            return;
        }
        if (!dom.activeState.contains(document.activeElement)) {
            return;
        }
        const focusedTag = document.activeElement?.tagName;
        if (focusedTag === 'INPUT' || focusedTag === 'TEXTAREA') {
            return;
        }
        const key = event.key.toLowerCase();
        const directionKeys = {
            arrowup: 'up',
            arrowdown: 'down',
            arrowleft: 'left',
            arrowright: 'right',
        };
        const button = Array.from(
            dom.choiceControls.querySelectorAll('button'),
        ).find((choiceButton) => {
            return choiceButton.dataset.shortcut === key
                || choiceButton.dataset.value === directionKeys[key];
        });
        if (button) {
            event.preventDefault();
            button.click();
        }
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            pauseCountdownForVisibility();
            pauseMemoryPreviewForVisibility();
            return;
        }
        resumeCountdownFromVisibility();
        resumeMemoryPreviewFromVisibility();
    });

    window.addEventListener('popstate', (event) => {
        const slug = event.state?.game
            || window.location.pathname.match(/^\/play\/([^/]+)$/)?.[1];
        if (slug) {
            openBriefing(decodeURIComponent(slug), {fromHistory: true});
        } else {
            backToHome({fromHistory: true, skipConfirm: true});
        }
    });
}


async function initialise() {
    cacheDom();
    audio = new ArcadeAudio(dom.soundToggle);
    bindEvents();

    try {
        const [catalogPayload, benchmarkPayload] = await Promise.all([
            api('/api/games'),
            api('/api/benchmarks'),
        ]);
        state.catalog = unwrapGames(catalogPayload);
        (benchmarkPayload.benchmarks || []).forEach((benchmark) => {
            state.benchmarks.set(benchmark.slug, benchmark);
        });
        await refreshPersonalBests();
        renderCards();
        const initialSlug = document.body.dataset.initialGame;
        if (initialSlug) {
            openBriefing(initialSlug, {
                fromHistory: true,
                replaceHistory: true,
            });
        } else {
            showView('home');
        }
    } catch (error) {
        dom.gameGrid.replaceChildren(
            createTextElement(
                'p',
                'page-error',
                `BrainHacker could not load: ${error.message}`,
            ),
        );
    }
}


initialise();
