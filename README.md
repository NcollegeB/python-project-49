# Brain Games Arcade

Brain Games Arcade is a collection of ten endless terminal challenges. Every
correct answer adds one point, every mistake costs one of your three lives,
and the run ends when no lives remain. Scores are saved to a persistent
leaderboard, so each game can be replayed to improve your personal best.

The `brain-games` command opens a terminal hub where you can launch any game
and view the leaderboard without leaving the arcade.

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

Choose a numbered game from the menu, enter `l` to view the leaderboard, or
enter `q` to quit. A game continues until all three lives are gone or you
return to the hub, and its score is saved in either case.

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
```

## Leaderboard data

Each player's best result for each game is retained. By default, scores are
stored at:

```text
~/.brain_games/leaderboard.json
```

Set `BRAIN_GAMES_DATA_DIR` to choose a different data directory.

## Tests and checks

Run the test suite with:

```console
make test
```

Optional project checks are also available:

```console
make lint
make selfcheck
```

The test suite covers the endless three-life loop, answer aliases, scoring,
leaderboard persistence and ordering, game generators, and terminal hub flow.
