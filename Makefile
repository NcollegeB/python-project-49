.PHONY: install test lint selfcheck build publish package-install \
	brain-games brain-even brain-calc brain-gcd brain-progression \
	brain-prime brain-number-memory brain-verbal-memory \
	brain-direction-focus brain-symbol-match brain-word-scramble \
	brain-culmination web web-check check

install:
	poetry install

test:
	poetry run python -m unittest discover -s tests -v

web:
	poetry run flask --app brain_games.app run --debug

web-check:
	node --check brain_games/static/app.js
	node --check brain_games/static/audio.js
	node --check brain_games/static/effects.js

check: test lint selfcheck web-check

lint:
	poetry run flake8 brain_games tests

selfcheck:
	poetry check

build:
	poetry build
	
publish:
	publish --dry-run
	
package-install:
	python3 -m pip install --user dist/*.whl --force-reinstall

brain-games:
	poetry run brain-games

brain-even:
	poetry run brain-even

brain-calc:
	poetry run brain-calc

brain-gcd:
	poetry run brain-gcd

brain-progression:
	poetry run brain-progression

brain-prime:
	poetry run brain-prime

brain-number-memory:
	poetry run brain-number-memory

brain-verbal-memory:
	poetry run brain-verbal-memory

brain-direction-focus:
	poetry run brain-direction-focus

brain-symbol-match:
	poetry run brain-symbol-match

brain-word-scramble:
	poetry run brain-word-scramble

brain-culmination:
	poetry run brain-culmination
