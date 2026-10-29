# acidchess roadmap

Same idea as [scrabble](https://github.com/acidvegas/scrabble): an open-source take on a classic, playable online, then bent with new modes, pieces and layouts. Items are checked off only after they are tested.

## Phase 0 - Research & groundwork

- [x] Study the scrabble project layout *(Flask, vanilla JS, room codes, SSE, SQLite, captcha accounts, single gevent worker)*
- [x] Research the full rules ([FIDE Laws of Chess 2023](https://handbook.fide.com/chapter/E012023)): castling conditions, en passant timing, promotion to any piece, stalemate, dead position, threefold/fivefold repetition, 50/75-move rules, flag fall vs insufficient material
- [x] Research move generator validation ([perft results](https://www.chessprogramming.org/Perft_Results): start position, Kiwipete, positions 3-6)
- [x] Research Elo *(E = 1 / (1 + 10^((Rb - Ra) / 400)), K = 40 for the first 30 games, 20 after, 10 once 2400 has been reached)*
- [x] Research variant ideas for later phases *(lichess: Chess960, Crazyhouse, Atomic, Three-Check, King of the Hill, Antichess, Horde, Racing Kings; fairy pieces: Seirawan, Capablanca, Wildebeest)*
- [x] Decisions: own rules engine, room codes + public lobby + quick-play matching, Elo leaderboard, untimed + preset clocks

## Phase 1 - Standard chess online

### Rules engine (`engine.py`)
- [x] Board representation, FEN load/save
- [x] Pseudo-legal move generation for every piece *(data-driven piece definitions so new pieces can be added later)*
- [x] Legal move filtering *(pins, checks, king safety)*
- [x] Castling *(king + rook unmoved, empty squares between, king not in/through/into check)*
- [x] En passant *(only on the move right after the double step; includes the horizontal-pin edge case)*
- [x] Promotion to queen, rook, bishop or knight *(underpromotion)*
- [x] Checkmate and stalemate
- [x] Dead position / insufficient material *(K v K, K+minor v K, K+B v K+B with same-coloured bishops)*
- [x] Threefold repetition and 50-move rule *(drawn automatically, as most online sites do)*
- [x] SAN move notation *(disambiguation, +, #, =Q, O-O)* and PGN export
- [x] Perft test suite matches the reference counts *(start, Kiwipete, positions 3-6)*, plus ~250k random positions cross-checked against python-chess

### Server (`app.py`, `game.py`)
- [x] Rooms with 4-character codes, join as white/black, spectators
- [x] Public lobby listing open games
- [x] Quick play queue that pairs players with the same time control
- [x] Live updates over Server-Sent Events, polling fallback
- [x] Clocks: untimed, 1+0, 3+0, 3+2, 5+0, 10+0, 10+5, 15+10, 30+0 *(flag fall loses, unless the opponent has no mating material: draw)*
- [x] Resign, draw offer / accept / decline, abort before the first moves, rematch
- [x] Room chat
- [x] Rooms persisted to SQLite so games survive a restart, stale rooms reaped

### Accounts & leaderboard (`auth.py`, `storage.py`)
- [x] Sign up / log in with username, password and captcha, sessions
- [x] Rated games between two signed-in players, Elo updates *(stats count rated games only)*
- [x] Per-player stats *(games, wins, losses, draws, streaks, peak rating)*
- [x] Leaderboard

### Frontend (`index.html`, `style.css`, `script.js`)
- [x] Board with click-to-move and drag-and-drop
- [x] Legal move dots, last move, check highlight
- [x] Promotion picker
- [x] Board flips for black, move list in SAN, captured pieces / material diff
- [x] Clocks, game result screen, PGN copy
- [x] Landing screen: create, join, lobby, quick play, sign in, leaderboard
- [x] Works on phones

### Ship
- [x] Run over a private network
- [x] README, Dockerfile, setup.sh

## Phase 2 - Play against the computer

- [x] Research options: own alpha-beta search vs Stockfish vs Fairy-Stockfish. Picked [Fairy-Stockfish](https://github.com/fairy-stockfish/Fairy-Stockfish), built from source with large boards and all variants, since its `variants.ini` can also describe Phase 3 twists *(custom pieces, board sizes, start positions)*
- [x] 8 difficulty levels using the [lichess fishnet](https://github.com/lichess-org/fishnet) table *(Skill Level -9 to 20, depth 5 to 22, 50 ms to 1 s per move)*, verified with bot-vs-bot matches where every higher level beat the lower one *(35.5/36)*
- [x] Pool of long-lived engine processes *(startup costs ~0.3 s, a pooled search ~15 ms)*, with a watchdog that kills a stuck engine and falls back to a random legal move
- [x] Computer tab: pick level, color and time control. The computer never takes draws, plays again instantly, and resumes thinking after a server restart
- [x] Computer games count toward a per-level win/loss/draw record on the profile, never Elo
- [x] Docker image builds Fairy-Stockfish in a separate stage

## Phase 3 - The twist

Picked: holes, bigger boards, new pieces, explosive captures, drops, alternative win conditions, 4-player chess and reconnaissance blind chess. Big rule changes are named modes *(Classic, Reconnaissance Blind, Big Board, 4-Player)*, and smaller twists are toggles that stack on top. Every mode gets its own Elo. 4-player has both free-for-all and 2v2 teams, and a checkmated army stays on the board frozen *(it can be captured but never moves)*.

### 3a - Variant-aware rules engine
- [x] Variant description: board size *(up to 12 files)*, walls, start position, piece set from movement definitions *(leap or slide, move-only or capture-only)*, castling worked out from the start position, promotion pieces
- [x] King capture instead of checkmate *(needed by Reconnaissance Blind)*
- [x] Every variant checked against Fairy-Stockfish: 18,000 random-game positions across holes, 10x8 with archbishop and chancellor, 10x10, a move-like-rook / capture-like-bishop piece, and king capture all match move for move *(`tests/test_variants.py`)*
- [x] Classic still passes every existing test *(perft to depth 5, ~200k positions against python-chess, API and browser tests)*

### 3b - Reconnaissance Blind Chess
- [x] Hidden information: each player gets a board with only their own pieces, opponent moves show as `?` *(or `?xe5` when they captured)*, no replaying a game in progress, and the PGN only appears once the game ends
- [x] Sense phase *(click a square, or skip)*, failed and shortened moves, pass, capture notices without piece types, king capture wins, 50-move draw, timeout always loses. Rules checked against the reference [reconchess](https://github.com/reconnaissanceblindchess/reconchess) library on ~106k random turns *(requested moves, resolved moves, capture squares, resulting positions, sense windows)*
- [x] Faded ghosts of every enemy piece you have sensed, with how many turns ago, plus a `?` where something took your piece. Finished games and spectators replay each move with the sense window shown
- [x] Spectators see the true board 4 plies behind
- [ ] Computer opponent *(postponed)*
- [x] Own Elo, leaderboard tab and profile row, separate from classic

### 3c - New pieces, Big Board and toggles

Pieces: archbishop *(bishop + knight)*, chancellor *(rook + knight)*, amazon *(queen + knight)*, cannon *(moves like a rook, captures by jumping exactly one piece)*, grasshopper *(must hop the first piece on a queen line, lands right behind it)*, nightrider *(repeats a knight jump in a line)*, camel *(3+1 leaper)*. Only the named modes are rated, any game with a toggle on is casual.

- [x] Engine: hopper, rider and camel movement, pawn start rank, checked against Fairy-Stockfish *(32,000 positions incl. an all-fairy army, hoppers next to walls and both Big Boards)*
- [x] Piece art for the 7 new pieces *(compounds built from the cburnett set, cannon, grasshopper and camel drawn in the same style)*
- [x] Board size in the frontend, walls, promotion picker and captured pieces worked out from the actual pieces
- [x] Big Board 10x8 mode *(rnabqkbcnr)*, rated
- [x] Big Board 10x10 mode *(second rank of cannon, camel, nightrider, grasshopper, pawns on the third rank)*, rated
- [x] Toggle: holes *(4 random walls in the middle ranks, mirrored through the centre, new layout every game)*
- [x] Toggle: random armies *(king and corner rooks stay, the rest is rolled within 2 points of the normal value, mirrored)*
- [x] Toggle: swaps *(knights to nightriders or grasshoppers, bishops to camels, rooks to cannons, queen to amazon)*
- [x] Toggle: king of the hill *(the four centre squares on any board)*
- [x] Toggle: three-check
- [x] Toggle: explosive captures *(atomic rules, can't be combined with drops)*
- [x] Toggle: drops *(click a piece in your hand next to your name, then a square)*
- [x] Toggle: bonus squares *(4 mirrored stars, each works once: knight or bishop to archbishop, rook to chancellor, queen to amazon. Human only)*
- [x] Toggles that stack are checked against Fairy-Stockfish in random combinations *(plus python-chess for three-check, king of the hill, atomic and crazyhouse: ~250k positions in total)*

- [ ] Computer opponent for twisted games and the other modes *(Fairy-Stockfish can play all of them except bonus squares)*

### 3d - 4-Player
- [x] Cross board *(14x14, corners cut, 160 squares)*, 4 seats, clockwise turns, a clock per player that starts after the first round, your army always drawn at the bottom
- [x] Free-for-all *(last king standing)* and 2v2 *(partners sit opposite, the first player out loses it for the team)*, frozen grey armies after checkmate, stalemate, timeout or resignation, a king left in check can be taken by another player, pawns promote on the centre line, no en passant
- [x] Rated per mode with pairwise Elo by finishing place, rematch moves everyone one seat clockwise, quick play fills a room with four
- [x] Rules checked by rotating 1,000+ random positions a quarter turn *(every army must get exactly the same moves)*, king safety on 1,000+ moves, castling and team captures
- [ ] Computer opponent *(postponed, games need four people)*

### Brainstorm and research notes

**Reconnaissance Blind Chess** *([JHU APL rules](https://rbc.jhuapl.edu/gameRules), [reconchess rules](https://reconchess.readthedocs.io/en/latest/rules.html))*
- You never see the enemy pieces. Each turn: learn whether and where you lost a piece, then sense one 3x3 window anywhere *(the enemy is not told where)*, then move or pass
- No check, checkmate or stalemate. You win by capturing the king. Castling through or into check is allowed
- A move that is illegal on the real board fails and your turn is over *(e.g. a pawn moving diagonally onto an empty square)*. A queen, rook or bishop that hits a hidden enemy piece stops there and captures it. A pawn double step that is blocked moves one square if it can
- Captures are announced with the square but never the piece type
- 15 minutes + 5 seconds per turn, automatic draw after 50 turns without a pawn move or capture
- Fairy-Stockfish cannot play hidden information. The usual computer approach is to keep a best guess of the enemy position, sense where the guess is least certain, and ask Stockfish for a move on the guessed board

**4-player chess** *([Wikibooks](https://en.wikibooks.org/wiki/Four-Player_Chess/How_to_play%3F))*
- 14x14 board with the 3x3 corners cut off *(160 squares)*, one full army per side, turns go clockwise
- Free-for-all *(last king standing, or points for captures)* or 2v2 teams sitting opposite each other
- Open questions for us: what happens to an eliminated player's pieces *(frozen, removed, or taken over by whoever mated them)*, where pawns promote, and whether to allow 3-player games
- Fairy-Stockfish cannot play this either, so the computer would be our own simple search

**Fairy-Stockfish support** *(computer opponent)*: holes *(walls, tested)*, boards up to 12x10, custom pieces, drops, explosions, three-check, king of the hill, shuffled or random start positions. Bonus squares that upgrade pieces may work through promotion zones, but they need more testing.

### Ideas

**Board**
- Holes: a few walls placed symmetrically that nothing can enter or slide through, randomized per game like scrabble's blocked cells
- Bigger boards: 10x8 and 10x10, with room for the new pieces
- Bonus squares: landing on a star square upgrades the piece *(knight to archbishop, bishop to cardinal, and so on)*, scrabble's bonus squares turned into chess
- 4-player cross board

**Armies and layouts**
- Shuffled back rank, the same for both sides
- Random armies: each side gets random pieces worth the same total, mirrored or not *(the closest thing to scrabble's Random mode)*

**Pieces**
- Compounds: archbishop *(bishop + knight)*, chancellor *(rook + knight)*, amazon *(queen + knight)*
- Our own designs, kept within what Fairy-Stockfish can describe *(e.g. a grasshopper that hops over a piece, a cannon that captures by jumping, a camel that leaps 3+1)*
- Needs new piece art that matches the current set

**Rules** *(toggles that could stack)*
- Explosive captures
- Drops
- Three-check
- King of the hill
- King capture instead of checkmate *(no check rules, the same as reconnaissance chess)*

**Hidden information**
- Reconnaissance blind chess
- A lighter fog-of-war option: you only see squares your pieces can reach *(no sensing)*

### What has to change first
- The rules engine is hard-coded to 8x8 standard chess. It needs a variant description *(board size, walls, piece set, castling, promotion, win rules, drops, explosions, check or king capture)*, with every variant checked against Fairy-Stockfish move counts the same way standard chess was checked against the perft tables
- Reconnaissance chess needs the server to send each player only what they are allowed to see, plus a sense step in the turn
- 4-player needs rooms with 4 seats, a 4-color turn order and elimination, which is the largest change
- Ratings, leaderboard and stats get split by mode

