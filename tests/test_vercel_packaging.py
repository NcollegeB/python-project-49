import importlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
ASSET_NAMES = (
    'app.js',
    'audio.js',
    'effects.js',
    'main.css',
    'theme.js',
)


class VercelPackagingTest(unittest.TestCase):
    def test_root_entrypoint_exports_the_brainhacker_app(self):
        brainhacker_module = importlib.import_module('brain_games.app')
        entrypoint = importlib.reload(importlib.import_module('app'))

        self.assertIs(brainhacker_module.app, entrypoint.app)

    def test_public_assets_match_the_local_flask_assets(self):
        local_directory = PROJECT_ROOT / 'brain_games' / 'static'
        public_directory = PROJECT_ROOT / 'public' / 'static'

        self.assertEqual(
            set(ASSET_NAMES),
            {path.name for path in public_directory.iterdir()},
        )
        for name in ASSET_NAMES:
            self.assertEqual(
                (local_directory / name).read_bytes(),
                (public_directory / name).read_bytes(),
            )

    def test_vercel_uses_zero_config_flask_routing(self):
        config = json.loads(
            (PROJECT_ROOT / 'vercel.json').read_text(encoding='utf-8'),
        )

        self.assertEqual('flask', config['framework'])
        self.assertIn('app.py', config['functions'])
        self.assertNotIn('builds', config)
        self.assertNotIn('routes', config)
        self.assertNotIn('rewrites', config)


if __name__ == '__main__':
    unittest.main()
