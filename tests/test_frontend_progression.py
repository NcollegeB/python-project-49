import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
STATIC_ROOT = PROJECT_ROOT / 'brain_games' / 'static'
PUBLIC_STATIC_ROOT = PROJECT_ROOT / 'public' / 'static'


class FrontendProgressionContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.javascript = (STATIC_ROOT / 'app.js').read_text(
            encoding='utf-8',
        )
        cls.stylesheet = (STATIC_ROOT / 'main.css').read_text(
            encoding='utf-8',
        )
        cls.instrument_javascript = (
            STATIC_ROOT / 'instrument_visuals.js'
        ).read_text(encoding='utf-8')
        cls.template = (
            PROJECT_ROOT / 'brain_games' / 'templates' / 'index.html'
        ).read_text(encoding='utf-8')

    def test_timing_modes_and_level_practice_selector_are_present(self):
        for mode in ('standard', 'self-paced'):
            self.assertIn('value="{}"'.format(mode), self.template)
        self.assertNotIn('value="relaxed"', self.template)
        self.assertIn('>Regular</span>', self.template)
        self.assertIn('>Relaxed</span>', self.template)
        self.assertNotIn('2× answer time', self.template)
        for element_id in (
                'levelValue',
                'levelProgress',
                'difficultyLabel',
                'roundTimer',
                'timerProgress',
                'levelSelector',
                'levelOptions',
                'practiceLevelNote',
        ):
            self.assertIn('id="{}"'.format(element_id), self.template)
        self.assertIn('name="timing-mode"', self.template)
        self.assertIn('timing_mode: timingMode', self.javascript)
        self.assertIn('start_level: startLevel', self.javascript)
        self.assertIn('function renderLevelSelector(maxLevel)', self.javascript)
        self.assertIn('state.startLevel = 1;', self.javascript)
        self.assertIn(
            "'Practice — scores are not saved.'",
            self.javascript,
        )
        self.assertIn("input.name = 'start-level';", self.javascript)
        self.assertIn(
            '`Start at level ${level} of ${maxLevel}`',
            self.javascript,
        )
        self.assertIn('min-height: 46px;', self.stylesheet)
        self.assertIn(
            'grid-template-columns: repeat(5, minmax(44px, 1fr));',
            self.stylesheet,
        )
        self.assertIn(
            "selectedTimingMode() !== 'standard'",
            self.javascript,
        )

    def test_practice_results_are_not_saved_or_benchmarked(self):
        finish_block = self.javascript.split(
            'async function finishRun',
            1,
        )[1].split(
            'function ordinal',
            1,
        )[0]
        self.assertIn(
            ": 'Not saved';",
            finish_block,
        )
        self.assertIn(
            "element.textContent = ranked ? '…' : '—';",
            finish_block,
        )
        self.assertIn('if (ranked) {', finish_block)
        self.assertIn(
            'refreshResultBenchmark(completedGame, score, resultIsCurrent)',
            finish_block,
        )
        self.assertLess(
            finish_block.index('if (ranked) {'),
            finish_block.index(
                'refreshResultBenchmark('
                'completedGame, score, resultIsCurrent)',
            ),
        )

    def test_answer_acknowledgement_and_timeout_are_race_guarded(self):
        self.assertIn(
            "const TIMEOUT_ANSWER = '__brainhacker_timeout__';",
            self.javascript,
        )
        self.assertIn("setAttribute('aria-busy', 'true')", self.javascript)
        self.assertIn("'Still checking…'", self.javascript)
        self.assertIn('if (event.repeat)', self.javascript)
        self.assertIn(
            '!dom.activeState.contains(document.activeElement)',
            self.javascript,
        )
        self.assertIn('state.busy = true;', self.javascript)

    def test_timer_pauses_when_hidden_and_dense_visuals_are_supported(self):
        self.assertIn(
            'pauseCountdownForVisibility();',
            self.javascript,
        )
        self.assertIn(
            'resumeCountdownFromVisibility();',
            self.javascript,
        )
        self.assertIn(
            '.arrow-row[data-columns="6"]',
            self.stylesheet,
        )
        self.assertIn(
            '(Array.isArray(data.items) && data.items.length > 0)',
            self.javascript,
        )
        self.assertIn('token.rotation_deg', self.javascript)
        for rotation in (
                20, 40, 50, 130, 140, 220, 230, 310, 320):
            self.assertIn(
                '.arrow-token[data-rotation="{}"]'.format(rotation),
                self.stylesheet,
            )
        self.assertIn(
            'grid-template-columns: repeat(6, minmax(0, 1fr));',
            self.stylesheet,
        )
        self.assertIn('max-width: 374px;', self.stylesheet)
        self.assertIn('.round-visual--direction', self.stylesheet)
        self.assertIn(
            'directionData.arrows.forEach((arrow, index) => {',
            self.javascript,
        )
        self.assertIn('.symbol-sequence', self.stylesheet)

    def test_extended_direction_and_symbol_contract_is_rendered(self):
        for rotation in range(0, 360, 15):
            self.assertIn(
                '.arrow-token[data-rotation="{}"]'.format(rotation),
                self.stylesheet,
            )
            self.assertIn(
                '.symbol-token[data-rotation="{}"]'.format(rotation),
                self.stylesheet,
            )
        for source in (
                'game.max_level',
                'max_level: maxLevel',
                'round.source_level',
                'round.data?.instruction',
                'data.accessible_instruction',
                "token.dataset.frame = frame;",
                "token.dataset.marker = marker;",
                "'arrow-token__marker'",
                "'symbol-token__glyph'",
                'data.pattern_columns',
                'group.dataset.columns',
        ):
            self.assertIn(source, self.javascript)
        symbol_data_block = self.javascript.split(
            'function symbolVisualData',
            1,
        )[1].split(
            'function symbolAccessibilityLabel',
            1,
        )[0]
        self.assertLess(
            symbol_data_block.index('data.left_tokens'),
            symbol_data_block.index('data.left_symbols'),
        )
        for source in (
                '.arrow-token[data-frame="round"]',
                '.arrow-token[data-frame="square"]',
                '.arrow-token__marker',
                '.symbol-token__glyph',
                '.symbol-sequence[data-columns="3"]',
        ):
            self.assertIn(source, self.stylesheet)

    def test_memory_preview_waits_for_paint_and_resumes_remaining_time(self):
        for source in (
                'state.preview.totalMs',
                'state.preview.remainingMs',
                'state.preview.lastTick',
                'state.preview.startFrame',
                'scheduleMemoryPreviewAfterPaint',
                'paintedFrames < 2',
                'pauseMemoryPreviewForVisibility();',
                'resumeMemoryPreviewFromVisibility();',
        ):
            self.assertIn(source, self.javascript)
        visibility_block = self.javascript.split(
            "document.addEventListener('visibilitychange'",
            1,
        )[1].split(
            "window.addEventListener('popstate'",
            1,
        )[0]
        self.assertNotIn('clearPreviewTimer();', visibility_block)
        self.assertNotIn('startMemoryPreview(state.round)', visibility_block)

    def test_symbol_labels_and_finished_result_writes_are_guarded(self):
        for source in (
                'data.left_tokens',
                'data.right_tokens',
                'token.accessible_label',
                'Left sequence:',
                'Right sequence:',
                'resultRunIsCurrent',
                'completedRunId',
                'completedGame',
                'shouldApply',
                'if (resultIsCurrent())',
        ):
            self.assertIn(source, self.javascript)
        finish_block = self.javascript.split(
            'async function finishRun',
            1,
        )[1].split(
            'function ordinal',
            1,
        )[0]
        self.assertLess(
            finish_block.index('window.setTimeout'),
            finish_block.index('await Promise.all'),
        )
        self.assertEqual(1, finish_block.count('dom.retryButton?.focus()'))

    def test_answer_focus_is_restored_and_directions_are_described(self):
        for source in (
                'currentEnabledAnswerControl',
                'restoreCurrentAnswerFocus',
                "if (!shouldLeave) {\n            restoreCurrentAnswerFocus();",
                "addEventListener('close', () => {",
                'arrow.accessible_label',
                'data.accessible_sequence',
                'data.accessible_instruction',
                'round.prompt',
                'Row by row:',
        ):
            self.assertIn(source, self.javascript)
        self.assertNotIn(
            'Find the odd arrow. Row by row:',
            self.javascript,
        )
        self.assertNotIn(
            'Angles in degrees, row by row:',
            self.javascript,
        )

    def test_async_leaderboard_and_native_key_repeat_are_guarded(self):
        for source in (
                'leaderboardRequestSequence',
                'invalidateLeaderboardRequests',
                'requestSequence !== state.leaderboardRequestSequence',
                'const repeatIsOnActiveAnswer',
                (
                    'if (repeatIsOnActiveAnswer) {'
                    '\n                event.preventDefault();'
                ),
        ):
            self.assertIn(source, self.javascript)
        self.assertGreaterEqual(
            self.javascript.count(
                'requestSequence !== state.leaderboardRequestSequence',
            ),
            2,
        )

    def test_scramble_hint_and_memory_curtain_are_accessible(self):
        for source in (
                'if (data.hint)',
                "'scramble-hint'",
                '`Hint · ${data.hint}`',
                "curtainDots.setAttribute('aria-hidden', 'true')",
        ):
            self.assertIn(source, self.javascript)
        self.assertIn('.scramble-hint', self.stylesheet)

    def test_expired_rounds_retry_only_the_timeout_sentinel(self):
        for source in (
                'const TIMEOUT_RETRY_DELAYS',
                'timeoutRetryMatches',
                'lockTimedOutRound',
                'scheduleTimedOutRetry',
                'recoverTimedOutRun',
                'returnExpiredRunToBriefing',
                "mode = 'answer'",
                "mode === 'recover'",
                'retry: true',
                'setControlsDisabled(true)',
        ):
            self.assertIn(source, self.javascript)
        self.assertIn(
            'state.timeoutRetry.roundId === state.round.round_id',
            self.javascript,
        )

    def test_early_ended_runs_do_not_claim_all_lives_were_lost(self):
        finish_block = self.javascript.split(
            'async function finishRun',
            1,
        )[1].split(
            'function ordinal',
            1,
        )[0]
        for source in (
                'result.quit_early ?? state.run.quit_early',
                'remainingLives > 0',
                'This run ended early with',
                'life\' : \'lives',
        ):
            self.assertIn(source, finish_block)
        self.assertIn('before losing three lives.', finish_block)

    def test_mobile_number_memory_stays_on_one_line(self):
        for source in (
                '.round-visual--memory .prompt-value',
                'font-size: clamp(1.75rem, 8.8vw, 3.2rem);',
                'letter-spacing: 0;',
                'white-space: nowrap;',
        ):
            self.assertIn(source, self.stylesheet)

    def test_answer_feedback_uses_fixed_slots_without_collapsing_timer(self):
        feedback_rule = self.stylesheet.split(
            '.feedback-region {',
            1,
        )[1].split('}', 1)[0]
        for source in (
                'height: 96px;',
                'overflow-y: auto;',
                'overflow-wrap: anywhere;',
                'scrollbar-gutter: stable;',
        ):
            self.assertIn(source, feedback_rule)
        self.assertNotIn('min-height:', feedback_rule)
        mobile_styles = self.stylesheet.split(
            '@media (max-width: 680px)',
            1,
        )[1]
        self.assertIn(
            'height: 118px;',
            mobile_styles,
        )
        self.assertIn(
            'const preserveTimerSlot = '
            'options.preserveTimerSlot === true;',
            self.javascript,
        )
        self.assertIn(
            'clearCountdown({preserveTimerSlot: true})',
            self.javascript,
        )
        self.assertIn(
            'role="status" aria-live="polite" aria-atomic="true"',
            self.template,
        )

    def test_wrong_answers_use_game_specific_review_states(self):
        for source in (
                'const CORRECT_ADVANCE_MS = 420;',
                'const WRONG_REVIEW_MS = {',
                "'direction-focus': 2200",
                "'symbol-match': 2300",
                "'word-scramble': 2300",
                'answerReviewDelay(answeredRound, grading, runResult)',
                'showWrongAnswerReview',
                'grading.review',
                'REVIEW_SKIP_DELAY_MS',
                'skipRemainingMs',
                'pauseAnswerTransitionForVisibility();',
                'resumeAnswerTransitionFromVisibility();',
                'advanceAnswerTransition({manual: true})',
                'dom.activeState.contains(document.activeElement)',
                'pauseGameForDialog',
                'resumeGameAfterDialog',
        ):
            self.assertIn(source, self.javascript)
        self.assertNotIn('const FEEDBACK_DELAY', self.javascript)
        self.assertIn('data-review="true"', self.stylesheet)
        self.assertIn('.feedback-continue', self.stylesheet)
        self.assertIn('id="reviewContinue"', self.template)
        feedback_markup = self.template.split(
            'id="feedbackRegion"',
            1,
        )[1].split('</div>', 1)[0]
        self.assertNotIn('reviewContinue', feedback_markup)

    def test_twgl_instrument_layer_is_local_and_progressively_enhanced(self):
        self.assertIn(
            "filename='vendor/twgl-7.0.0.min.js'",
            self.template,
        )
        self.assertIn(
            "import {InstrumentVisuals} from './instrument_visuals.js';",
            self.javascript,
        )
        for source in (
                "new Set(['symbol-match'])",
                "this.canvas.getContext('webgl'",
                'twgl.createProgramInfo',
                'twgl.createBufferInfoFromArrays',
                "addEventListener('webglcontextlost'",
                'this.canvas.setAttribute(\'aria-hidden\', \'true\')',
                'Math.min(2, window.devicePixelRatio || 1)',
                "new Set(['polycube_3d'])",
                'depth: true',
                'SOLID_VERTEX_SHADER',
                'function arrowMeshArrays(profile, headStyle, shaftStyle)',
                'directionArrowStyle(item)',
                'const directionArrows = {};',
                'directionArrowMesh(style)',
                'drawDirection3D()',
                'drawPolycube3D()',
                "'(prefers-reduced-motion: reduce)'",
                "document.visibilityState !== 'hidden'",
        ):
            self.assertIn(source, self.instrument_javascript)
        self.assertNotIn('Math.random(', self.instrument_javascript)
        self.assertNotIn(
            'directionShaftMesh(solid)',
            self.instrument_javascript,
        )
        self.assertNotIn('this.meshes.bandCollar', self.instrument_javascript)

    def test_direction_overlay_has_no_per_arrow_guide_artifacts(self):
        direction_geometry = self.instrument_javascript.split(
            'directionGeometry(origin, guideLines, reviewLines, reviewFill) {',
            1,
        )[1].split(
            'symbolGeometry(origin, guideLines, reviewLines, reviewFill) {',
            1,
        )[0]
        self.assertNotIn('tokens.forEach(', direction_geometry)
        self.assertNotIn('rect.top - 5', direction_geometry)
        self.assertIn(
            'addCornerFrame(guideLines, field, 9, 12);',
            direction_geometry,
        )
        self.assertIn(
            'addFilledRectangle(reviewFill, target, 4);',
            direction_geometry,
        )

    def test_spatial_arrows_are_one_mesh_with_direction_gated_depth_cues(
            self,
    ):
        renderer = self.instrument_javascript.split(
            'drawDirection3D() {',
            1,
        )[1].split(
            'drawPolycube3D() {',
            1,
        )[0]
        self.assertEqual(1, renderer.count('this.drawSolid('))
        self.assertNotIn('this.meshes.cube', renderer)
        self.assertNotIn('bandCollar', renderer)
        self.assertNotIn('DEPTH_TEST', renderer)
        for source in (
                'const DEPTH_REVEAL_ANGLE = 42 * DEG_TO_RAD;',
                (
                    'return mat4RotationX('
                    '(-Math.PI / 2) - DEPTH_REVEAL_ANGLE);'
                ),
                'attribute float a_surface_cue;',
                'uniform float u_cue_mode;',
                '* step(0.5, u_cue_mode);',
                '* step(u_cue_mode, -0.5);',
                'surfaceCues.push(surfaceCue);',
                'const tipRadius =',
                'addFace(tailCap, -1);',
                'addFace(tipCap.reverse(), 1);',
                (
                    "headStyle = legacyBand === 'split' "
                    "? 'wide' : 'narrow';"
                ),
                (
                    "shaftStyle = legacyBeacon === 'dot' "
                    "? 'long' : 'short';"
                ),
        ):
            self.assertIn(source, self.instrument_javascript)

    def test_spatial_rounds_have_webgl_and_static_accessible_renderers(self):
        for source in (
                "new Set(['polycube_3d'])",
                'renderPolycube3DFallback',
                'renderMotionDirection',
                "namedRenderMode === 'motion_direction_2d'",
                'renderMemoryMatrix',
                "namedRenderMode === 'memory_matrix'",
                'renderPinballRecall',
                "namedRenderMode === 'pinball_recall'",
                "'spatial-3d-fallback polycube-fallback'",
                "renderCubeProjection(cubes, 'FRONT', 0, 1)",
                "renderCubeProjection(cubes, 'SIDE', 2, 1)",
                "renderCubeProjection(cubes, 'TOP', 0, 2)",
                "round.data?.render_mode === 'polycube_3d'",
        ):
            self.assertIn(source, self.javascript)
        for source in (
                '.round-visual[data-instrument="twgl-3d"]',
                '.motion-arrow',
                '.memory-matrix__grid',
                '.pinball-board',
                '.polycube-projection',
                '.polycube-projection__cell[data-review-state="mismatch"]',
        ):
            self.assertIn(source, self.stylesheet)

    def test_direction_arrows_use_crisp_css_geometry(self):
        for source in (
                'function renderMotionDirection(round, visual)',
                "arrow.classList.add('motion-arrow');",
                "'animateTransform'",
                "animation.setAttribute(\n                'values'",
                "arrow.setAttribute(\n            'points'",
                "arrow.setAttribute(\n            'transform'",
                "item?.visual_role === 'distractor'",
                'field.dataset.hasDistractors',
        ):
            self.assertIn(source, self.javascript)
        for source in (
                '.motion-arrow',
                'fill: currentcolor;',
                '.motion-target-ring',
                '.motion-item[data-role="target"]',
                '.motion-trails circle',
                '.round-visual[data-review="true"] .motion-trails',
                'opacity: 0;',
        ):
            self.assertIn(source, self.stylesheet)
        self.assertNotIn('style.setProperty', self.javascript)
        self.assertIn(
            "const THREE_D_RENDER_MODES = new Set(['polycube_3d']);",
            self.javascript,
        )
        self.assertIn(
            "const SPATIAL_GAMES = new Set(['symbol-match']);",
            self.instrument_javascript,
        )

    def test_vercel_assets_match_local_assets(self):
        for name in (
                'app.js',
                'instrument_visuals.js',
                'main.css',
        ):
            self.assertEqual(
                (STATIC_ROOT / name).read_bytes(),
                (PUBLIC_STATIC_ROOT / name).read_bytes(),
            )


if __name__ == '__main__':
    unittest.main()
