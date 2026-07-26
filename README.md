# BrainHacker

BrainHacker is a paper-inspired browser and terminal collection of 12
standalone brain games plus the mixed Culmination Test: 13 catalog options in
total. Every solved round adds one point, every failed round costs one of
three lives, and a run continues until all three lives are gone or the player
quits.

Most games have five authored levels. Direction Focus, Symbol Match, and the
Culmination Test continue through Level 10. Every three correct answers
advances one level, and the final level repeats for as long as the player
survives. Misses do not erase level progress.

The hosted app is available at
[brainhacker.vercel.app](https://brainhacker.vercel.app/).

## Browser app

The browser interface keeps the games central: a compact directory, fixed
play area, keyboard and pointer controls, restrained local sound cues, and
light, dark, grey, and high-contrast themes. Signed-in players can keep a
personal best for every catalog option. Guests can play under a temporary
display name.

Install the project and start the development server:

```console
poetry install
make web
```

Then open <http://127.0.0.1:5000>. A game can also be opened directly at
`/play/<game-slug>`, for example
<http://127.0.0.1:5000/play/memory-matrix>. The health check is available at
<http://127.0.0.1:5000/healthz>.

For a production-style local process:

```console
poetry run gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 4 brain_games.app:app
```

Without `DATABASE_URL`, active browser runs are held in memory. Use one
Gunicorn worker in that configuration so a run is not split between separate
processes.

## Games

| Game | Category | What it tests | Direct command |
| --- | --- | --- | --- |
| Even or Odd | Math | parity under time pressure | `brain-even` |
| Calculator | Math | mental arithmetic | `brain-calc` |
| Greatest Common Divisor | Math | factor reasoning | `brain-gcd` |
| Missing Progression | Reasoning | number-pattern completion | `brain-progression` |
| Prime Number | Math | primality recognition | `brain-prime` |
| Number Memory | Memory | digit-sequence recall | `brain-number-memory` |
| Verbal Memory | Memory | seen/new word recognition | `brain-verbal-memory` |
| Direction Focus | Attention | tracking 2D motion while ignoring arrow facing | `brain-direction-focus` |
| Symbol Match | Attention | detailed symbol comparison and spatial matching | `brain-symbol-match` |
| Word Scramble | Language | timed word reconstruction | `brain-word-scramble` |
| Memory Matrix | Memory | recalling highlighted grid cells | hub or browser |
| Pinball Recall | Memory | remembering mirrors and tracing a hidden route | hub or browser |

Direction Focus is motion-based at every level. Early rounds teach the
difference between movement and arrow facing; later rounds add marked groups,
balanced distractor motion, and denser 2D fields. Choosing the direction most
arrowheads face is not a shortcut.

Memory Matrix briefly highlights a randomized set of cells, hides the pattern,
and grades each recalled tile as soon as it is clicked. Every tile has a short
sound cue, and the third miss in one pattern costs a life. Pinball Recall shows
a grid of slash mirrors before hiding them, reveals an entry port, and asks
where the ball exits.

Symbol Match progresses from compact 2D comparisons to rotating 3D polycube
comparisons in its final levels. Its WebGL view has a static accessible
fallback and honors reduced-motion preferences.

The Culmination Test is catalog option 13. Each 12-round cycle is a shuffled
bag containing one round from every standalone game, so every source appears
once before the next cycle begins. It has a shared score, three shared lives,
and its own saved best and leaderboard.

## Levels, timing, and practice

The level selector can start a run at any authored difficulty. Starting above
Level 1 creates an unranked practice run. It continues progressing normally
from the selected level, but it does not update personal bests or leaderboard
scores.

There are two timing modes:

- **Regular** uses each game's normal response deadline. A Regular run is
  ranked only when it starts at Level 1.
- **Relaxed** removes response deadlines and always creates an unranked
  practice run.

Preview phases remain intentional in both modes. Number Memory hides its
number after its encoding period; Memory Matrix hides highlighted cells; and
Pinball Recall hides its mirror layout before recall begins.

## Fixed averages and percentiles

The end-of-run report shows the score, saved personal best when eligible, a
fixed BrainHacker average, percentile, and equivalent rank out of 100. The
`/stats` page lists the same references for all 13 catalog options and compares
them with a signed-in player's saved bests.

These statistics do not depend on live players or leaderboard activity. Each
game has fixed round-accuracy assumptions for its authored levels. The model
uses the same three-lives, three-correct-to-advance rules as gameplay and
calculates a deterministic score distribution.

BrainHacker benchmarks are stable product baselines. They are not measured
population norms, scientific results, IQ scores, diagnoses, or medical
claims.

## JSON API

The browser is backed by the same JSON API available to other clients:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | service health |
| `GET` | `/api/games` | game catalog and level metadata |
| `GET` | `/api/me` | current account state |
| `GET` | `/api/benchmarks` | all fixed benchmark summaries |
| `GET` | `/api/benchmarks/<slug>?score=<n>` | one benchmark and optional percentile |
| `POST` | `/api/runs` | start a run |
| `POST` | `/api/runs/<run-id>/answers` | submit an answer for the active round |
| `POST` | `/api/runs/<run-id>/quit` | finish a run early |
| `GET` | `/api/leaderboard` | filter saved scores by game or player |

Start-run JSON accepts `game`, `player`, `timing_mode`, and `start_level`.
`timing_mode` is `standard` for Regular or `self-paced` for Relaxed. Answer
submissions include the current `round_id` and `answer`. Errors use JSON
responses with stable error codes and appropriate HTTP status codes.

## Accounts and durable storage

Register at `/register` with a 3–24 character username and a password of at
least eight characters. Usernames are case-insensitive. Passwords are stored
as Werkzeug password hashes, and signed-in run attribution is resolved on the
server.

For a public HTTPS deployment, configure a stable random session key and
secure cookies:

```console
export BRAIN_GAMES_SECRET_KEY='replace-with-a-long-random-secret'
export BRAIN_GAMES_SECURE_COOKIES=1
```

`BRAIN_GAMES_SECRET_KEY` is required on Vercel. Keeping it stable preserves
login sessions across deployments.

Set `DATABASE_URL` to a PostgreSQL connection string to store accounts,
personal bests, leaderboards, and active runs durably. This allows gameplay to
continue across Vercel Function instances. The
[Neon integration for Vercel](https://vercel.com/marketplace/neon/neon) can
provide a managed PostgreSQL database and connection variable.

Without `DATABASE_URL`, local accounts and scores use files under
`BRAIN_GAMES_DATA_DIR`, while active browser runs stay in memory.

## Advertising

Google AdSense Auto ads can be enabled on game pages by setting the public
publisher identifier:

```console
export BRAIN_GAMES_ADSENSE_CLIENT='ca-pub-1234567890123456'
```

When this variable is absent, BrainHacker does not load Google ad code. When
present, `/ads.txt` publishes the matching authorized-seller record. Scope the
variable to Production on Vercel so preview deployments remain ad-free.

Side rails are configured in AdSense under **Auto ads → Side rail ads**. Their
availability depends on desktop viewport space; they do not reduce the game
area on smaller screens.

## Terminal hub

After installation, launch the terminal hub with:

```console
brain-games
```

From the Poetry environment:

```console
poetry run brain-games
```

The hub lists all 12 standalone games and the Culmination Test. It also
provides the leaderboard and quit actions. Direct launcher commands are
available for the games shown in the table above, plus:

```console
brain-culmination
```

During play:

- enter `y`/`yes` or `n`/`no` for yes-or-no games;
- enter `u`, `r`, `d`, or `l` for Direction Focus;
- enter `q` or `quit` to save the current score and return to the hub.

Answers are case-insensitive. Number and word games still require the complete
answer, and every incorrect non-quit answer costs one life.

## Local leaderboard files

When PostgreSQL is not configured, best scores are stored at:

```text
~/.brain_games/leaderboard.json
```

Registered accounts are stored separately at:

```text
~/.brain_games/accounts.json
```

Set `BRAIN_GAMES_DATA_DIR` to choose a different directory. On POSIX systems,
the account file is written with owner-only permissions.

## Build and verification

Build and install the wheel into the user environment:

```console
make build
make package-install
```

Run the test suite and complete project checks:

```console
make test
make check
```

Individual checks are available through `make lint`, `make selfcheck`, and
`make web-check`.

## Project status and roadmap

BrainHacker is in active beta. The browser app is live, while gameplay
balancing, account hardening, deployment cleanup, and launch preparation are
still in progress.

Current priorities and release blockers are tracked in
[TO-DO-LIST.md](TO-DO-LIST.md). Pull requests run the Python test suite,
linting, package validation, browser script checks, and a package build before
they are merged.

The games are intended for practice and entertainment. BrainHacker is not
affiliated with a cognitive benchmark or training service and does not claim
medical benefits.
