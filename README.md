# BallsDex V3 Leaderboard Package

Leaderboard system for **BallsDex V3**. Players can view the leaderboard of people with the most caught countryballs.

## Commands

| Command | Description |
|---|---|
| `/balls leaderboard` | Show the leaderboard of players with the most caught countryballs, currency or XP |

## Installation

### 1 — Important Notes

You can change `EXCLUDE_BOTS`, `EXCLUDE_IDS`, `ITEMS_PER_PAGE`, and `TOP_PLAYER_LIMIT` in the code to control who is excluded from the leaderboard, how many players are shown on each page, and the available `top` choices.

### 2 — Configure extra.toml

**If the file doesn't exist:** Create a new file `extra.toml` in your `config` folder under the BallsDex directory.

**If you already have other packages installed:** Simply add the following configuration to your existing `extra.toml` file. Each package is defined by a `[[ballsdex.packages]]` section, so you can have multiple packages installed.

Add the following configuration:

```toml
[[ballsdex.packages]]
location = "git+https://github.com/MapsDex-Team/BallsDex-Leaderboard-Pack.git@0.0.1#master"
path = "leaderboard"
enabled = true
```

**Example of multiple packages:**

```toml
# First package
[[ballsdex.packages]]
location = "git+https://github.com/example/other-package.git"
path = "other"
enabled = true

# Leaderboard Package
[[ballsdex.packages]]
location = "git+https://github.com/MapsDex-Team/BallsDex-Leaderboard-Pack.git@0.0.1#master"
path = "leaderboard"
enabled = true
```

### 3 — Rebuild and start the bot

```bash
docker compose build
docker compose up -d
```

This will install the package and start the bot.
