# acidchess

## Live demo: [chess.supernets.org](https://chess.supernets.org)

Online chess in the browser, built with Flask. Standard chess first, then a computer opponent, then new modes, pieces and layouts that bend the rules. See [ROADMAP.md](ROADMAP.md) for what is done and what is next.

## Features

- Own rules engine *(castling, en passant, underpromotion, checkmate, stalemate, insufficient material, threefold repetition, 50-move rule)*, checked against the standard perft positions
- Modes: **Classic**, **Reconnaissance Blind**, **Big Board 10x8**, **Big Board 10x10**, **4-Player** and **4-Player 2v2** *(see below)*, each with its own Elo and leaderboard
- Twists you can stack on a created game: holes, random armies, piece swaps, king of the hill, three-check, explosive captures, drops and bonus squares. Twisted games are always casual
- Quick play pairs you with the next player waiting on the same mode and time control
- Play the computer at 8 levels, from beginner to full strength *(powered by [Fairy-Stockfish](https://github.com/fairy-stockfish/Fairy-Stockfish))*
- Create a room and share its 4-character code, or list it in the public lobby
- Spectators *(open `/<room>?watch`)*
- Clocks: untimed, 1+0, 3+0, 3+2, 5+0, 10+0, 10+5, 15+10 and 30+0. Clocks start after both sides have moved. Running out of time loses, unless the opponent has no way to mate, which is a draw.
- Resign, draw offers, abort before the first moves, rematch with colors swapped
- Drag-and-drop or click-to-move, legal move dots, promotion picker, move list with replay, PGN copy, room chat *(last 100 messages)* with sounds and desktop notifications
- A help popup explaining the modes, twists and new pieces, and an in-game version showing only what applies to that game
- Optional accounts *(username, password and a captcha)* with Elo ratings, a leaderboard and a win/loss record against each computer level

## Rating

Rated games need two signed-in players. Ratings start at 1200 and use Elo with FIDE's K factors:

| Player                    | K  |
|---------------------------|----|
| Fewer than 30 rated games | 40 |
| 30 or more rated games    | 20 |
| Has ever reached 2400     | 10 |

## New pieces

| Letter | Piece       | Moves                                                                         |
|--------|-------------|-------------------------------------------------------------------------------|
| A      | Archbishop  | Bishop + knight                                                               |
| C      | Chancellor  | Rook + knight                                                                 |
| M      | Amazon      | Queen + knight                                                                |
| O      | Cannon      | Moves like a rook, captures only by jumping exactly one piece of either color |
| G      | Grasshopper | Must hop the first piece on a queen line and lands right behind it            |
| H      | Nightrider  | Repeats a knight jump in a straight line until blocked                        |
| L      | Camel       | Leaps 3 squares one way and 1 the other                                       |

Big Board 10x8 starts `rnabqkbcnr`. Big Board 10x10 adds a second rank of cannon, camel, nightrider and grasshopper, with pawns on the third rank. Pawns can promote to any piece their side started with.

## Twists

| Twist              | What it does                                                                                          |
|--------------------|-------------------------------------------------------------------------------------------------------|
| Holes              | 4 walls in the middle of the board, mirrored through the centre. Nothing can enter or pass them       |
| Random armies      | Everything on the back rank except the king and corner rooks is rolled at random, about equal value   |
| Swaps              | Knights become nightriders or grasshoppers, bishops become camels, rooks cannons, the queen an amazon |
| King of the hill   | Reaching one of the four centre squares with your king wins                                           |
| Three-check        | Giving check three times wins                                                                         |
| Explosive captures | Atomic rules: a capture destroys both pieces and every non-pawn around them. Blow up the king to win  |
| Drops              | Crazyhouse rules: captured pieces join your hand and can be dropped on an empty square                |
| Bonus squares      | 4 stars. The first piece to land on one uses it up, and knights, bishops, rooks and queens upgrade    |

Holes, random armies and bonus squares are rolled again for every game, including rematches. Explosive captures and drops can't be combined. The computer only plays classic chess for now.

## 4-Player

Four armies on a 14x14 board with the corners cut off, Red, Blue, Yellow and Green taking turns clockwise. Your own army is always drawn at the bottom.

- **Free-for-all**: last king standing wins. A player who is checkmated, stalemated, runs out of time or resigns is out, and their army stays on the board frozen in grey, where anyone can capture it.
- **2v2**: partners sit opposite each other *(Red with Yellow, Blue with Green)* and can't capture each other. The first player out loses the game for their team.
- A king left in check can be captured by another player before its owner gets to move, which also knocks that player out.
- Pawns promote on the centre line, 8 ranks from their own side. There is no en passant.
- Each player has their own clock, which starts once everyone has moved. Ratings move pairwise by finishing place.

## Reconnaissance Blind

Reconnaissance Blind follows the rules of [Reconnaissance Blind Chess](https://rbc.jhuapl.edu/gameRules) from Johns Hopkins APL. You never see the enemy pieces.

- Each turn you first sense: pick any square and you see the 3x3 window around it. Your opponent is not told where you looked. You can skip it.
- Then you move or pass. A move that is impossible on the real board fails and your turn is over. A pawn, rook, bishop or queen that runs into a hidden piece stops there and captures it.
- When a capture happens both players learn the square, never what was captured or what captured it.
- There is no check or checkmate. Capture the king to win. Running out of time always loses, and 50 moves each without a capture or pawn move is a draw.

Enemy pieces you have sensed stay on your board as faded ghosts marked with how many turns ago you saw them. Spectators watch the real board 4 moves behind, so a player can't open a second tab to peek. Once the game ends, both players can replay it with every sense shown.

## Computer levels

The levels use the same engine settings as lichess. Each move searches to a depth and time limit, and the engine's skill level makes it pick weaker moves on purpose at the low end. Games against the computer never change your Elo.

| Level | Name        | Skill | Depth | Time per move |
|-------|-------------|-------|-------|---------------|
| 1     | Beginner    | -9    | 5     | 50 ms         |
| 2     | Novice      | -5    | 5     | 100 ms        |
| 3     | Casual      | -1    | 5     | 150 ms        |
| 4     | Club        | 3     | 5     | 200 ms        |
| 5     | Strong club | 7     | 5     | 300 ms        |
| 6     | Expert      | 11    | 8     | 400 ms        |
| 7     | Master      | 16    | 13    | 500 ms        |
| 8     | Maximum     | 20    | 22    | 1000 ms       |

## Requirements

- Python 3.12+
- [Flask](https://pypi.org/project/Flask/)
- [gunicorn](https://pypi.org/project/gunicorn/) with the [gevent](https://pypi.org/project/gevent/) worker
- [Fairy-Stockfish](https://github.com/fairy-stockfish/Fairy-Stockfish) for the computer opponent *(optional, the Computer tab is hidden without it)*

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd acidchess
../.venv/bin/gunicorn --worker-class gevent --workers 1 --graceful-timeout 5 --bind 127.0.0.1:20001 app:app
```

Game state lives in memory, so always run a single worker.

To enable the computer opponent, build Fairy-Stockfish into `engines/` *(or point `ACIDCHESS_ENGINE` at an existing binary)*:

```bash
git clone https://github.com/fairy-stockfish/Fairy-Stockfish.git .build/Fairy-Stockfish
make -C .build/Fairy-Stockfish/src -j build ARCH=x86-64-modern largeboards=yes all=yes
mkdir -p engines && cp .build/Fairy-Stockfish/src/stockfish engines/fairy-stockfish
```

`largeboards=yes all=yes` turns on boards bigger than 8x8 and every variant, which the variant cross-checks in the tests need.

## Running with Docker

```bash
./setup.sh
```

This builds the `acidchess` image *(including Fairy-Stockfish)* and starts a container bound to `127.0.0.1:20001` with the `acidchess_data` volume mounted at `/data`.

## Tests

```bash
python3 tests/test_engine.py
.venv/bin/python tests/test_app.py
python3 tests/test_variants.py
python3 tests/test_four.py
PERFT_DEPTH=5 python3 -m unittest tests.test_engine.TestEngine.test_perft
```

`test_variants.py` plays random games in each test variant *(holes, 10x8, 10x10, custom pieces, king capture, three-check, king of the hill, explosive captures, drops, bonus squares and stacks of them)* and checks every position's legal moves against Fairy-Stockfish, so it needs the engine binary. The last command runs the deep perft counts and takes a couple of minutes.

## Code layout

| Path                    | Contents                                                                                              |
|-------------------------|-------------------------------------------------------------------------------------------------------|
| `acidchess/app.py`      | Flask routes, rooms, lobby, quick play, live updates                                                  |
| `acidchess/game.py`     | Game flow: moves, clocks, results, PGN                                                                |
| `acidchess/ai.py`       | Computer opponent, talks UCI to Fairy-Stockfish                                                       |
| `acidchess/engine.py`   | Rules engine for any variant: board size, walls, custom pieces, move generation, SAN, FEN, draw rules |
| `acidchess/four.py`     | 4-player rules: board, moves, castling, check, knock-outs                                             |
| `acidchess/fourgame.py` | 4-player game flow: turns, clocks, resigning, results                                                 |
| `acidchess/recon.py`    | Reconnaissance Blind rules: requested moves, how they resolve on the real board, sensing              |
| `acidchess/toggles.py`  | Twists that change the start position: holes, random armies, swaps, bonus squares                     |
| `acidchess/storage.py`  | SQLite storage for users, games, rooms and Elo                                                        |
| `acidchess/auth.py`     | Sessions and captcha                                                                                  |
| `acidchess/static/`     | `utils.js`, `style.css` and piece images                                                              |
| `acidchess/templates/`  | `index.html`                                                                                          |
| `tests/`                | Perft, variant cross-checks against Fairy-Stockfish, 4-player rules and HTTP API tests                |

## Data

Everything is written to `ACIDCHESS_DATA_DIR`, which defaults to `data/` at the repo root. `acidchess.db` holds accounts, sessions, finished games and active rooms, so games survive a restart. Finished and unstarted rooms are removed after an hour of inactivity, and any room after a day.

---

###### Mirrors: [SuperNETs](https://git.supernets.org/acidvegas/) • [GitHub](https://github.com/acidvegas/) • [GitLab](https://gitlab.com/acidvegas/) • [Codeberg](https://codeberg.org/acidvegas/)
