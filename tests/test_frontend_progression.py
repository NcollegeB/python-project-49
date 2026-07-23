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
        cls.template = (
            PROJECT_ROOT / 'brain_games' / 'templates' / 'index.html'
        ).read_text(encoding='utf-8')

    def test_timing_modes_and_level_hud_are_present(self):
        for mode in ('standard', 'relaxed', 'self-paced'):
            self.assertIn('value="{}"'.format(mode), self.template)
        for element_id in (
                'levelValue',
                'levelProgress',
                'difficultyLabel',
                'roundTimer',
                'timerProgress',
        ):
            self.assertIn('id="{}"'.format(element_id), self.template)
        self.assertIn('name="timing-mode"', self.template)
        self.assertIn('timing_mode: timingMode', self.javascript)
        self.assertIn('Relaxed · 2× answer time', self.template)
        self.assertIn('Self-paced · No answer deadline', self.template)

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
            'directionData.arrows.forEach((arrow) => {',
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
                'height: 64px;',
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
            '.feedback-region {\n        height: 80px;\n    }',
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

    def test_vercel_assets_match_local_assets(self):
        for name in ('app.js', 'main.css'):
            self.assertEqual(
                (STATIC_ROOT / name).read_bytes(),
                (PUBLIC_STATIC_ROOT / name).read_bytes(),
            )


if __name__ == '__main__':
    unittest.main()
