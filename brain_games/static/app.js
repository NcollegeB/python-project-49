import {ArcadeAudio} from './audio.js';


const PLAYER_STORAGE_KEY = 'brainhacker-player-name';
const GUEST_PREFIX = 'Guest#';
const FEEDBACK_DELAY = 620;

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
    previewTimer: null,
    previewRoundId: null,
    transitionTimer: null,
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
        'stageCategory', 'stageTitle',
        'stageRules', 'scoreValue', 'livesValue', 'roundValue',
        'cycleTrack', 'briefingState', 'activeState', 'resultState',
        'briefingIcon', 'briefingTitle', 'briefingDescription',
        'startRunButton', 'roundSource', 'roundPrompt', 'roundVisual',
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


function openBriefing(slug, options = {}) {
    const game = findGame(slug);
    if (!game) {
        return;
    }
    clearPreviewTimer();
    clearTransitionTimer();
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
    updateHud({score: 0, lives: 3});
    dom.roundValue.textContent = 'Ready';
    dom.cycleTrack.replaceChildren();
    setFeedback('', 'neutral');
    if (!options.fromHistory) {
        updateHistory(slug, options.replaceHistory);
    }
    window.setTimeout(() => dom.startRunButton?.focus(), 0);
}


function clearPreviewTimer() {
    if (state.previewTimer) {
        window.clearTimeout(state.previewTimer);
        state.previewTimer = null;
    }
    state.previewRoundId = null;
}


function clearTransitionTimer() {
    if (state.transitionTimer) {
        window.clearTimeout(state.transitionTimer);
        state.transitionTimer = null;
    }
}


function updateHud(run = state.run) {
    if (!run) {
        return;
    }
    dom.scoreValue.textContent = String(run.score ?? 0);
    const lives = Math.max(0, Number(run.lives ?? 0));
    dom.livesValue.textContent = `${'♥'.repeat(lives)}${'♡'.repeat(3 - lives)}`;
    dom.livesValue.setAttribute('aria-label', `${lives} of 3 lives remaining`);
}


async function startRun() {
    if (!state.selected || state.busy) {
        return;
    }
    clearTransitionTimer();
    const selectedSlug = state.selected.slug;
    const requestSequence = state.startSequence + 1;
    state.startSequence = requestSequence;
    state.busy = true;
    dom.startRunButton.disabled = true;
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
            button.append(
                createTextElement(
                    'span',
                    'choice-button__shortcut',
                    choice.shortcut,
                ),
            );
        }
        button.addEventListener('click', () => submitAnswer(choice.value));
        dom.choiceControls.append(button);
    });
    window.setTimeout(() => dom.choiceControls.querySelector('button')?.focus(), 0);
}


function renderGenericVisual(round) {
    const visual = dom.roundVisual;
    const data = round.data || {};
    const kind = round.kind || 'text';
    visual.replaceChildren();
    visual.className = `round-visual round-visual--${kind}`;
    visual.setAttribute('aria-label', round.prompt || 'Current challenge');

    if (kind === 'direction' || Array.isArray(data.arrows)) {
        const arrows = data.arrows || [];
        const row = document.createElement('div');
        row.className = 'arrow-row';
        arrows.forEach((arrow) => row.append(
            createTextElement('span', 'arrow-token', arrow),
        ));
        visual.append(row);
        return;
    }

    if (Array.isArray(data.symbols)) {
        const symbols = data.symbols || [data.left, data.right];
        const pair = document.createElement('div');
        pair.className = 'symbol-pair';
        symbols.filter(Boolean).forEach((symbol, index) => {
            pair.append(createTextElement('span', 'symbol-token', symbol));
            if (index === 0) {
                pair.append(createTextElement('span', 'symbol-divider', '|'));
            }
        });
        visual.append(pair);
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
        const row = document.createElement('div');
        row.className = 'letter-row';
        Array.from(letters).forEach((letter) => row.append(
            createTextElement('span', 'letter-tile', letter),
        ));
        visual.append(row);
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
    dom.roundVisual.classList.add('is-hidden');
    dom.roundVisual.setAttribute('aria-hidden', 'true');
    dom.roundVisual.removeAttribute('aria-label');
    dom.roundVisual.replaceChildren();
    dom.memoryCurtain.hidden = false;
    const hiddenPrompt = round.hidden_prompt || 'What did you see?';
    dom.memoryCurtain.replaceChildren(
        createTextElement('span', '', '● ● ●'),
        createTextElement('strong', '', hiddenPrompt),
    );
    dom.roundPrompt.textContent = hiddenPrompt;
    dom.answerForm.hidden = false;
    dom.choiceControls.hidden = true;
    dom.answerRow.hidden = false;
    dom.answerInput.value = '';
    dom.answerInput.inputMode = 'numeric';
    dom.answerInput.focus();
    state.previewTimer = null;
}


function startMemoryPreview(round) {
    clearPreviewTimer();
    state.previewRoundId = round.round_id;
    dom.roundPrompt.textContent = instructionBySlug[round.source_slug]
        || 'Memorize this.';
    dom.memoryCurtain.hidden = true;
    dom.answerForm.hidden = true;
    const delay = Math.max(300, Number(round.preview_ms || 1500));
    state.previewTimer = window.setTimeout(
        () => revealMemoryAnswer(round),
        delay,
    );
}


function renderRound(round) {
    if (!round) {
        return;
    }
    clearPreviewTimer();
    state.round = round;
    state.roundNumber += 1;
    state.busy = false;
    dom.activeState.dataset.feedback = 'idle';
    dom.roundSource.textContent = round.source_name || state.selected.name;
    dom.roundSource.dataset.category = categoryClass(
        round.source_category || state.selected.category,
    );
    dom.roundPrompt.textContent = instructionBySlug[round.source_slug]
        || round.prompt
        || round.rules;
    dom.stageRules.textContent = round.rules || state.selected.rules;
    dom.roundValue.textContent = String(state.roundNumber);
    dom.answerInput.value = '';
    dom.answerInput.disabled = false;
    dom.submitAnswer.disabled = false;
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
    } else if (!dom.answerRow.hidden) {
        const numericGames = new Set([
            'calc', 'gcd', 'progression', 'number-memory',
        ]);
        dom.answerInput.inputMode = numericGames.has(round.source_slug)
            ? 'numeric'
            : 'text';
        dom.answerInput.autocomplete = 'off';
        window.setTimeout(() => dom.answerInput.focus(), 0);
    }
}


function setControlsDisabled(disabled) {
    dom.answerInput.disabled = disabled;
    dom.submitAnswer.disabled = disabled;
    dom.choiceControls.querySelectorAll('button').forEach((button) => {
        button.disabled = disabled;
    });
}


async function submitAnswer(answer) {
    if (!state.run || !state.round || state.busy) {
        return;
    }
    const value = String(answer ?? '').trim();
    if (!value) {
        setFeedback('Enter an answer first.', 'wrong');
        dom.answerInput.focus();
        return;
    }
    state.busy = true;
    clearPreviewTimer();
    setControlsDisabled(true);
    const runId = state.run.run_id;
    const roundId = state.round.round_id;

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
        ) {
            return;
        }
        const runResult = unwrapRun(payload);
        const grading = runResult.result || payload.result || {};
        state.run = {...state.run, ...runResult};
        updateHud();
        const sourceName = state.round.source_name || state.selected.name;
        if (grading.correct) {
            dom.activeState.dataset.feedback = 'correct';
            setFeedback(`${sourceName}: correct — one point added.`, 'correct');
            audio.cue('correct');
        } else {
            dom.activeState.dataset.feedback = 'wrong';
            const expected = grading.expected_answer;
            setFeedback(
                `${sourceName}: not quite. The answer was ${expected}.`,
                'wrong',
            );
            audio.cue('wrong');
        }

        if (runResult.game_over || runResult.ended || !runResult.round) {
            const runId = state.run.run_id;
            state.transitionTimer = window.setTimeout(
                () => {
                    state.transitionTimer = null;
                    if (state.run?.run_id === runId) {
                        finishRun(runResult);
                    }
                },
                FEEDBACK_DELAY + 120,
            );
        } else {
            const runId = state.run.run_id;
            state.transitionTimer = window.setTimeout(
                () => {
                    state.transitionTimer = null;
                    if (state.run?.run_id === runId) {
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
        ) {
            return;
        }
        state.busy = false;
        setControlsDisabled(false);
        setFeedback(error.message, 'wrong');
        if (error.status === 409) {
            setFeedback('That round has already ended. Return to the menu.', 'wrong');
        }
    }
}


async function finishRun(result) {
    clearPreviewTimer();
    state.busy = false;
    const score = Number(result.score ?? state.run.score ?? 0);
    const previousBest = state.personalBests.get(state.selected.slug);
    const isBest = previousBest === undefined || score > previousBest;
    state.run.score = score;
    state.run.lives = Number(result.lives ?? 0);
    state.run.ended = true;
    showState('result');
    dom.resultScore.textContent = String(score);
    dom.resultBest.textContent = isBest ? `${score} NEW` : String(previousBest);
    dom.resultBest.dataset.best = String(isBest);
    dom.resultMessage.textContent = score === 0
        ? 'Every baseline starts somewhere. Take another run.'
        : `You cleared ${score} ${score === 1 ? 'round' : 'rounds'} before losing three lives.`;
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
    await Promise.all([
        refreshPersonalBests(),
        refreshResultBenchmark(state.selected.slug, score),
    ]);
    window.setTimeout(() => dom.retryButton?.focus(), 0);
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


async function refreshResultBenchmark(game, score) {
    try {
        const benchmark = await api(
            `/api/benchmarks/${encodeURIComponent(game)}?score=${score}`,
        );
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
            return;
        }
    }
    state.navigating = true;
    clearPreviewTimer();
    clearTransitionTimer();
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


async function refreshPersonalBests() {
    try {
        const playerName = currentPlayerName();
        const payload = await api(
            `/api/leaderboard?player=${encodeURIComponent(playerName)}&limit=100`,
        );
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


async function renderLeaderboard() {
    const game = dom.leaderboardFilter.value;
    const query = game ? `?game=${encodeURIComponent(game)}&limit=20` : '?limit=20';
    dom.leaderboardRows.replaceChildren(leaderboardMessageRow('Loading scores…'));
    try {
        const payload = await api(`/api/leaderboard${query}`);
        const entries = unwrapLeaders(payload);
        dom.leaderboardRows.replaceChildren();
        if (!entries.length) {
            dom.leaderboardRows.append(leaderboardMessageRow(
                'No scores yet. Your next run can be the first.',
            ));
            return;
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
    } catch (error) {
        dom.leaderboardRows.replaceChildren(leaderboardMessageRow(error.message));
    }
}


async function openLeaderboard() {
    dom.leaderboardFilter.replaceChildren();
    const allOption = new Option('All games', '');
    dom.leaderboardFilter.append(allOption);
    state.catalog.forEach((game) => {
        dom.leaderboardFilter.append(new Option(game.name, game.slug));
    });
    await renderLeaderboard();
    if (typeof dom.leaderboardDialog.showModal === 'function') {
        dom.leaderboardDialog.showModal();
    } else {
        dom.leaderboardDialog.hidden = false;
    }
}


function closeLeaderboard() {
    if (typeof dom.leaderboardDialog.close === 'function') {
        dom.leaderboardDialog.close();
    } else {
        dom.leaderboardDialog.hidden = true;
    }
}


function bindEvents() {
    dom.startRunButton?.addEventListener('click', startRun);
    dom.retryButton?.addEventListener('click', startRun);
    dom.resultMenuButton?.addEventListener('click', () => backToHome());
    dom.backButton?.addEventListener('click', () => backToHome());
    dom.answerForm?.addEventListener('submit', (event) => {
        event.preventDefault();
        submitAnswer(dom.answerInput.value);
    });
    dom.leaderboardButton?.addEventListener('click', openLeaderboard);
    dom.closeLeaderboard?.addEventListener('click', closeLeaderboard);
    dom.leaderboardFilter?.addEventListener('change', renderLeaderboard);
    dom.leaderboardDialog?.addEventListener('click', (event) => {
        if (event.target === dom.leaderboardDialog) {
            closeLeaderboard();
        }
    });

    document.addEventListener('keydown', (event) => {
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
        if (
            document.visibilityState === 'visible'
            && state.round
            && Number(state.round.preview_ms || 0) > 0
            && !dom.answerForm.hidden
        ) {
            return;
        }
        if (
            document.visibilityState === 'visible'
            && state.round
            && Number(state.round.preview_ms || 0) > 0
        ) {
            dom.roundVisual.classList.remove('is-hidden');
            startMemoryPreview(state.round);
        } else if (document.visibilityState === 'hidden') {
            clearPreviewTimer();
        }
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
