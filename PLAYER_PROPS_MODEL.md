# MLB Player Props V1.1

## Purpose

Produce a separate morning Player Props report for hits, total bases, RBIs, and
pitcher strikeouts. The model uses dynamic thresholds and statistics only.

## Dynamic thresholds

The model calculates probabilities for multiple milestones within each category and
selects the highest milestone that clears its category-specific reliability gate.
Examples include 1+/2+/3+ hits and 4+ through 10+ strikeouts.

The threshold gates normalize categories with different natural frequencies. The
final ranking combines absolute reliability, gate clearance, and a controlled
difficulty bonus. No sportsbook
line defines the milestone and no market information enters the score.

Reliability gates:

- Hits: 1+ at 62%, 2+ at 32%, 3+ at 14%
- Total bases: 2+ at 48%, 3+ at 34%, 4+ at 24%
- RBIs: 1+ at 38%, 2+ at 16%, 3+ at 7%
- Strikeouts: 4+ through 10+ at 78%, 68%, 58%, 48%, 38%, 29%, and 21%

## Inputs

- Official MLB same-day schedule and `gamePk`
- Active rosters
- Season hitter production and playing-time rates
- Probable-pitcher season ERA, WHIP, H/9, HR/9, K/9, and innings/start
- Opponent team strikeout rate and runs/game
- Park factors
- Venue-linked game-time weather forecast

## Conservative exclusions

- Unverified schedule, team, venue, or probable pitcher
- Non-playable game status
- Doubleheaders without game-specific lineup confirmation
- Hitters with fewer than 10 games or fewer than 2.5 PA/game
- Pitchers with fewer than three starts or fewer than 3.5 innings/start

## Report structure

- Twelve top props
- Eight watchlist props
- Maximum two props per player
- Maximum three props per game
- No fixed quota by prop category; the strongest statistical profiles rank first

Morning reports verify active-roster status and expected playing time. They do not
claim confirmed lineup status when official starting lineups are not yet available.
