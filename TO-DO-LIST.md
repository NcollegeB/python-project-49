# BrainHacker to-do list

This is the working roadmap for taking BrainHacker from its current beta to a
stable public release. Tasks are ordered by priority inside each section.

## Started

- [x] Keep the current game work on `agent/gui-experiment`.
- [x] Sync `agent/gui-experiment` with the latest `main`.
- [x] Add a complete GitHub README with setup, gameplay, API, storage, and
  deployment notes.
- [x] Add this tracked roadmap.
- [x] Add GitHub Actions checks for tests, linting, browser scripts, package
  validation, and package builds.
- [x] Confirm the new checks pass on pull request #3.
- [ ] Merge pull request #3 into `main` after the checks and final playtest.
- [ ] Set `main` as the Vercel production branch after the merge.

## Release-blocking playtest

Test every game on desktop and mobile in both Regular and Relaxed modes. For
each game, check keyboard and pointer input, three-life behavior, level
progression, the practice selector, time limits, sound, answer review, score
saving, and the end-of-run report.

- [ ] Even or Odd
- [ ] Calculator
- [ ] Greatest Common Divisor
- [ ] Missing Progression
- [ ] Prime Number
- [ ] Number Memory
- [ ] Verbal Memory
- [ ] Direction Focus
- [ ] Symbol Match
- [ ] Word Scramble
- [ ] Memory Matrix
- [ ] Pinball Recall
- [ ] Culmination Test
- [ ] Verify light, dark, grey, and high-contrast themes throughout.
- [ ] Verify reduced-motion behavior and complete keyboard navigation.
- [ ] Check the fixed game area at common phone, tablet, laptop, and desktop
  sizes.

## Gameplay and scoring

- [ ] Run a small friend playtest and record completion rates by game and
  level.
- [ ] Tune difficulty, preview times, answer limits, and level curves from
  playtest results.
- [ ] Recalculate the fixed averages and percentiles after balancing is final.
- [ ] Version the scoring rules so results from different rule sets are never
  compared as if they were equivalent.
- [ ] Reset or migrate old Memory Matrix scores because its recall rules
  changed.
- [ ] Confirm every generated round is randomized while avoiding immediate
  repeats.
- [ ] Confirm every Culmination Test cycle contains each standalone game once.

## Accounts, scores, and security

- [ ] Reject impossible or tampered leaderboard submissions with server-side
  validation.
- [ ] Add rate limits to login, registration, run, answer, and leaderboard
  endpoints.
- [ ] Add password recovery, or clearly label accounts as beta accounts until
  recovery exists.
- [ ] Add session-management controls for signing out other devices.
- [ ] Configure automated PostgreSQL backups.
- [ ] Perform and document a test database restore.
- [ ] Review CSRF, cookie, content-security, and account-enumeration behavior
  before launch.

## Reliability and maintenance

- [ ] Add production error reporting and alerting.
- [ ] Add privacy-respecting product analytics and performance monitoring.
- [ ] Create a repeatable smoke test for the live site after each deployment.
- [ ] Remove unused legacy Direction Focus and old 3D-rendering code.
- [ ] Remove obsolete build artifacts and prevent them from returning.
- [ ] Choose Poetry or uv as the single lockfile authority, then remove or
  regenerate the other lockfile so local, CI, and Vercel installs agree.
- [ ] Review Python and browser dependencies for updates and security notices.
- [ ] Document the score-data migration process for future game changes.

## Repository independence

- [ ] Save the current pull request description and any notes that must be
  retained.
- [ ] Detach the repository from its fork network.
- [ ] Rename the repository to `NcollegeB/BrainHacker`.
- [ ] Update the local `origin`, Vercel connection, documentation links, and
  deployment settings after the rename.
- [ ] Enable GitHub Issues after detachment, then convert suitable items from
  this file into focused issues.

Detaching is permanent and removes repository metadata such as pull requests,
issues, stars, watchers, comments, and the wiki. Commit history remains. Do
this only after the current work is merged and the notes worth keeping have
been copied. See
[GitHub's detaching-a-fork guide](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/detaching-a-fork).

The detachment and repository rename require Nathan's GitHub approval.

## Launch, legal, and revenue

- [ ] Finish the Terms and Privacy pages for accounts, analytics, cookies, and
  advertising.
- [ ] Add consent controls before enabling services that require them.
- [ ] Apply for AdSense and add the production publisher identifier.
- [ ] Verify side-rail ads never overlap games or reduce mobile usability.
- [ ] Buy and connect the BrainHacker domain.
- [ ] Add canonical redirects from the Vercel address to the final domain.
- [ ] Verify social previews, page titles, descriptions, sitemap, and robots
  rules.
- [ ] Publish a changelog and the first versioned release.

AdSense approval, the publisher identifier, and the domain purchase require
Nathan.

## Definition of public-release ready

- [ ] All automated checks pass on `main`.
- [ ] All 13 catalog options pass the release-blocking playtest.
- [ ] No open critical security, data-loss, or scoring-integrity issues remain.
- [ ] Database backup and restore have both been tested.
- [ ] Production monitoring and post-deployment smoke tests are active.
- [ ] Legal and consent pages match the services actually enabled.
- [ ] The custom domain, repository, and Vercel production branch all point to
  the final release.
