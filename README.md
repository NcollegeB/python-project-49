# BrainHacker

BrainHacker is a deliberately simple, paper-inspired browser home for ten
endless brain games plus a mixed Culmination Test. Every correct answer adds
one point, every mistake costs one of three lives, and the run ends when no
lives remain. Create an account to keep a personal best for every test, or
play without an account under a temporary display name.

The original `brain-games` terminal hub remains available with the same games,
three-life rules, and persistent leaderboard.

## Browser app

The Paper Test interface keeps the gameplay ahead of decoration: a ruled game
directory, a clean test sheet, restrained sound cues, and a score report at the
end. Each report shows the run score, saved personal best, fixed BrainHacker
average, percentile, and equivalent rank out of 100. The `/stats` page lists
the same stable references for all eleven tests and, when signed in, compares
them with the account's saved bests.

Sound cues are synthesized locally with the Web Audio API and can be muted
from the header. The interface does not download fonts, media, trackers, or
other third-party assets.

Install the project and start the development server:

```console
poetry install
make web
```

Then open <http://127.0.0.1:5000>. Direct game links use
`/play/<game-slug>`, such as <http://127.0.0.1:5000/play/number-memory>.
The JSON health check is available at <http://127.0.0.1:5000/healthz>.

For a production-style local process, Gunicorn can serve the same app:

```console
poetry run gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 4 brain_games.app:app
```

Use one worker because active browser runs are intentionally held in memory;
accounts and best scores are file-backed and persistent.

## Fixed averages and percentiles

BrainHacker does not use the live leaderboard to calculate statistics. Every
game has a fixed reference round-accuracy assumption. Because a run ends after
three misses, its score reference is a negative-binomial model with:

```text
average score = 3p / (1 - p)
```

The score percentile is the cumulative probability from that same fixed
model, rounded to a rank out of 100. These are **BrainHacker benchmarks**:
stable product baselines for comparison, not measured population norms,
scientific results, IQ scores, or medical claims. Changing players or
leaderboard scores never changes them.

## Accounts and saved scores

Register at `/register` with a 3–24 character username and a password of at
least eight characters. Usernames are case-insensitive and reserved for their
account. Passwords are stored only as Werkzeug password hashes, and signed-in
runs are attributed on the server rather than trusting a player name sent by
the browser.

For a public HTTPS deployment, set a persistent random session key and secure
cookies:

```console
export BRAIN_GAMES_SECRET_KEY='replace-with-a-long-random-secret'
export BRAIN_GAMES_SECURE_COOKIES=1
```

The current account and leaderboard backends use local files, which is useful
for development and a single server with a persistent disk. Vercel Functions
do not provide durable local filesystem storage; connect these stores to a
managed database before the public Vercel deployment so logins and scores
survive redeploys and scale across instances.

## Games

| Game | Category | Command | Game module |
| --- | --- | --- | --- |
| Even or Odd | Math | `brain-even` | `brain_games.games.brain_even` |
| Calculator | Math | `brain-calc` | `brain_games.games.brain_calc` |
| Greatest Common Divisor | Math | `brain-gcd` | `brain_games.games.brain_gcd` |
| Missing Progression | Reasoning | `brain-progression` | `brain_games.games.brain_progression` |
| Prime Number | Math | `brain-prime` | `brain_games.games.brain_prime` |
| Number Memory | Memory | `brain-number-memory` | `brain_games.games.brain_number_memory` |
| Verbal Memory | Memory | `brain-verbal-memory` | `brain_games.games.brain_verbal_memory` |
| Direction Focus | Attention | `brain-direction-focus` | `brain_games.games.brain_direction_focus` |
| Symbol Match | Attention | `brain-symbol-match` | `brain_games.games.brain_symbol_match` |
| Word Scramble | Language | `brain-word-scramble` | `brain_games.games.brain_word_scramble` |

The separate **Culmination Test** is menu option 11. It combines all ten games
into one endless run with a shared score and three shared lives. Each
ten-round cycle is a shuffled bag containing one round from every source game,
so all ten appear once before the next shuffled cycle begins. Culmination Test
scores are recorded on their own leaderboard.

The newer challenges draw on familiar memory, attention, speed, and language
game formats. They are original terminal implementations for practice and
entertainment; this project is not affiliated with any benchmark or training
service and does not claim medical or cognitive benefits.

## Short answers and controls

- For every yes/no game, enter `y` or `yes`, and `n` or `no`.
- In Direction Focus, enter `u`, `d`, `l`, or `r` instead of `up`, `down`,
  `left`, or `right`. Arrow characters also work.
- Enter `q` or `quit` during a game to save the current score and return to
  the hub.

Answers are case-insensitive. Games that require a number or a word still
expect the complete answer, and any incorrect non-quit answer costs a life.

## Install from this repository

Poetry creates an isolated environment and installs every project command:

```console
poetry install
```

To build and install the wheel into your user environment instead:

```console
make build
make package-install
```

## Run the arcade

After a regular installation, launch the hub with:

```console
brain-games
```

From the Poetry development environment, use:

```console
poetry run brain-games
```

Choose one of the ten standalone games or option 11 for the Culmination Test,
enter `l` to view the leaderboard, or enter `q` to quit. A run continues until
all three lives are gone or you return to the hub, and its score is saved in
either case.

## Run one game directly

Every game has its own command. Prefix a command with `poetry run` when using
the Poetry environment:

```console
brain-even
brain-calc
brain-gcd
brain-progression
brain-prime
brain-number-memory
brain-verbal-memory
brain-direction-focus
brain-symbol-match
brain-word-scramble
brain-culmination
```

## Leaderboard data

Each player's best result for every standalone game and the Culmination Test is
retained. By default, scores are stored at:

```text
~/.brain_games/leaderboard.json
```

Set `BRAIN_GAMES_DATA_DIR` to choose a different data directory.

Registered accounts are stored separately at:

```text
~/.brain_games/accounts.json
```

The account file is written with owner-only permissions on POSIX systems.

## Tests and checks

Run the test suite with:

```console
make test
```

Optional project checks are also available:

```console
make lint
make selfcheck
make web-check
```

Run the complete verification set with `make check`.

The test suite covers the endless three-life loop, answer aliases, scoring,
leaderboard persistence and ordering, game generators, the shuffled
Culmination Test cycle, terminal hub flow, isolated browser runs, and API
validation.
