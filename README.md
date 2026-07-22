# Brain Games Arcade

Brain Games Arcade is a collection of five endless terminal games. Every
correct answer earns one point. Every mistake costs one of your three lives,
and a run ends when no lives remain.

The `brain-games` command opens a terminal game hub where you can launch any
game and view the persistent leaderboard.

## Games

- **Even or Odd** — decide whether a number is even.
- **Calculator** — solve a generated arithmetic expression.
- **Greatest Common Divisor** — find the GCD of two numbers.
- **Missing Progression** — find the hidden number in a progression.
- **Prime Number** — decide whether a number is prime.

## Install from this repository

Poetry creates an isolated environment and installs all project commands:

```console
poetry install
```

To build and install the wheel into your user environment instead:

```console
make build
make package-install
```

## Run the arcade

```console
brain-games
```

From a Poetry development environment, use:

```console
poetry run brain-games
```

The hub lets you choose all five games, view the overall leaderboard, return
to the menu with `q`, or quit the arcade. Scores are saved automatically when
a run ends or you return to the menu.

## Run one game directly

The individual commands still work:

```console
brain-even
brain-calc
brain-gcd
brain-progression
brain-prime
```

## Leaderboard data

Each player's best result for each game is retained. By default, scores are
stored at:

```text
~/.brain_games/leaderboard.json
```

Set `BRAIN_GAMES_DATA_DIR` to choose a different data directory.

## Tests

```console
make test
```

The test suite covers the endless three-life loop, scoring, persistence,
leaderboard ordering, the game-generator contract, and terminal hub flow.
