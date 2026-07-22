install:
	poetry install

test:
	poetry run python -m unittest discover -s tests -v

lint:
	poetry run flake8 brain_games

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
