#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/four.py

import re
import time


# 4-player chess on a 14x14 board with the 3x3 corners cut off. Turns go clockwise: red (bottom), blue (left), yellow (top), green (right).
SIZE      = 14
FILES     = 'abcdefghijklmn'
COLORS    = ('r', 'b', 'y', 'g')
NAMES     = {'r': 'Red', 'b': 'Blue', 'y': 'Yellow', 'g': 'Green'}
TEAMS     = {'r': 0, 'y': 0, 'b': 1, 'g': 1}                                    # 2v2: players sitting opposite are partners
FORWARD   = {'r': (0, 1), 'b': (1, 0), 'y': (0, -1), 'g': (-1, 0)}            # (file, rank) step of each color's pawns
PROMOTION = ('Q', 'R', 'B', 'N')
UCI_RE    = re.compile(r'^([a-n]\d+)([a-n]\d+)([qrbn]?)$')
ORTHO     = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAG      = ((1, 1), (1, -1), (-1, 1), (-1, -1))
KNIGHT    = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
MOVES     = {'N': (KNIGHT, False), 'B': (DIAG, True), 'R': (ORTHO, True), 'Q': (ORTHO + DIAG, True), 'K': (ORTHO + DIAG, False)}
VALID     = [not ((r < 3 or r > 10) and (f < 3 or f > 10)) for r in range(SIZE) for f in range(SIZE)]


def advance(state: dict) -> list:
	'''Pass the turn clockwise to the next live player. Players with no legal move when their turn comes are out: checkmated, or stalemated.'''

	out = []
	while len(state['alive']) > 1 and not team_won(state):
		i = COLORS.index(state['turn'])
		state['turn'] = next(c for c in COLORS[i + 1:] + COLORS[:i + 1] if c in state['alive'])
		color = state['turn']
		if legal_moves(state, color):
			return out
		why = 'checkmate' if in_check(state, color) else 'stalemate'
		out.append((color, why))
		eliminate(state, color, why)
	return out


def apply_move(board: list, move: tuple) -> list:
	'''Return the board after a move. A king moving two squares castles with the rook on that side.'''

	frm, to, promo = move
	b     = board[:]
	piece = b[frm]
	b[frm] = None
	b[to]  = piece[0] + promo if promo else piece
	if piece[1] == 'K':
		ff, fr, tf, tr = frm % SIZE, frm // SIZE, to % SIZE, to // SIZE
		if abs(tf - ff) == 2 or abs(tr - fr) == 2:
			df, dr = (tf > ff) - (tf < ff), (tr > fr) - (tr < fr)
			f, r = tf + df, tr + dr
			while b[r * SIZE + f] != piece[0] + 'R':
				f, r = f + df, r + dr
			b[r * SIZE + f] = None
			b[(fr + dr) * SIZE + ff + df] = piece[0] + 'R'
	return b


def attacked(board: list, sq: int, attackers: set) -> bool:
	'''Return whether any piece of the given colors attacks a square.'''

	f, r = sq % SIZE, sq // SIZE
	for kind, (vectors, slides) in MOVES.items():
		for df, dr in vectors:
			nf, nr = f + df, r + dr
			while on_board(nf, nr):
				q = board[nr * SIZE + nf]
				if q is not None:
					if q[0] in attackers and q[1] == kind:
						return True
					break
				if not slides:
					break
				nf, nr = nf + df, nr + dr
	# A pawn attacks the two squares diagonally ahead of it, so look diagonally behind the target from each attacker's side
	for c in attackers:
		fdf, fdr = FORWARD[c]
		for side in (-1, 1):
			pf, pr = f - fdf - (side if fdf == 0 else 0), r - fdr - (side if fdr == 0 else 0)
			if on_board(pf, pr) and board[pr * SIZE + pf] == c + 'P':
				return True
	return False


def castle_moves(board: list, color: str, rights: list, enemies: set) -> list:
	'''Return castling moves: the king steps two squares towards an unmoved rook if everything between is empty and it doesn't pass through check.'''

	king = board.index(color + 'K') if color + 'K' in board else None
	if king is None or not rights:
		return []
	out = []
	kf, kr = king % SIZE, king // SIZE
	for rook in rights:
		if board[rook] != color + 'R':
			continue
		rf, rr = rook % SIZE, rook // SIZE
		df, dr = (rf > kf) - (rf < kf), (rr > kr) - (rr < kr)
		between, f, r = [], kf + df, kr + dr
		while (f, r) != (rf, rr):
			between.append(r * SIZE + f)
			f, r = f + df, r + dr
		if len(between) < 2 or any(board[s] is not None for s in between):
			continue
		path = [king, between[0], between[1]]
		if any(attacked(board, s, enemies) for s in path):
			continue
		out.append((king, between[1], None))
	return out


def eliminate(state: dict, color: str, reason: str):
	'''Knock a player out. Their pieces stay on the board frozen, and anyone may capture them.'''

	if color in state['alive']:
		state['alive'].remove(color)
		state['out'].append([color, reason])


def enemies_of(color: str, alive: list, teams: bool) -> set:
	'''Return the colors that can attack a player: every other live player, or only the other team in 2v2.'''

	return {c for c in alive if c != color and (not teams or TEAMS[c] != TEAMS[color])}


def finished(state: dict) -> dict:
	'''Return the result once the game is decided, else None.

	Free-for-all ends with one player left. 2v2 ends as soon as any player is out, their team loses.
	'''

	if state['teams']:
		if not state['out']:
			return None
		loser = TEAMS[state['out'][0][0]]
		return {'winners': [c for c in COLORS if TEAMS[c] != loser], 'reason': state['out'][0][1]}
	if len(state['alive']) > 1:
		return None
	return {'winners': list(state['alive']), 'reason': state['out'][-1][1] if state['out'] else 'resignation'}


def in_check(state: dict, color: str) -> bool:
	'''Return whether a player's king is attacked by a live enemy.'''

	board = state['board']
	if color + 'K' not in board:
		return False
	return attacked(board, board.index(color + 'K'), enemies_of(color, state['alive'], state['teams']))


def legal_moves(state: dict, color: str) -> list:
	'''Return every legal move for a color: pseudo-legal moves that don't leave its own king attacked by a live enemy.'''

	board   = state['board']
	enemies = enemies_of(color, state['alive'], state['teams'])
	out     = []
	for move in pseudo_moves(board, color, state['teams']) + castle_moves(board, color, state['rights'][color], enemies):
		after = apply_move(board, move)
		king  = after.index(color + 'K') if color + 'K' in after else None
		if king is not None and attacked(after, king, enemies):
			continue
		out.append(move)
	return out


def move_from_uci(text: str) -> tuple:
	'''Parse a move like h2h4 or h7h8q.'''

	m = UCI_RE.match((text or '').strip())
	if not m:
		raise ValueError('bad move')
	return (square_index(m.group(1)), square_index(m.group(2)), m.group(3).upper() or None)


def move_to_uci(move: tuple) -> str:
	'''Return the text form of a move.'''

	return square_name(move[0]) + square_name(move[1]) + (move[2].lower() if move[2] else '')


def new_board() -> list:
	'''Return the starting board. Each army reads rook, knight, bishop, queen, king, bishop, knight, rook from its own left.'''

	b    = [None] * (SIZE * SIZE)
	back = 'RNBQKBNR'
	for i, kind in enumerate(back):
		b[0 * SIZE + 3 + i]         = 'r' + kind # red, bottom, left is the a-side
		b[1 * SIZE + 3 + i]         = 'rP'
		b[13 * SIZE + 10 - i]       = 'y' + kind # yellow, top, left is the n-side
		b[12 * SIZE + 10 - i]       = 'yP'
		b[(10 - i) * SIZE + 0]      = 'b' + kind # blue, left edge, left is the top
		b[(10 - i) * SIZE + 1]      = 'bP'
		b[(3 + i) * SIZE + 13]      = 'g' + kind # green, right edge, left is the bottom
		b[(3 + i) * SIZE + 12]      = 'gP'
	return b


def new_state(teams: bool) -> dict:
	'''Return the starting game state.'''

	return {
		'board'  : new_board(),
		'turn'   : 'r',
		'alive'  : list(COLORS),
		'out'    : [],     # eliminated colors in order, with how
		'rights' : start_rights(),
		'teams'  : teams,
	}


def on_board(f: int, r: int) -> bool:
	'''Return whether a file and rank is a playable square.'''

	return 0 <= f < SIZE and 0 <= r < SIZE and VALID[r * SIZE + f]


def placements(state: dict) -> dict:
	'''Return color -> finishing place, 1 is best. Winners share first, the rest rank by how long they lasted.'''

	result = finished(state) or {'winners': []}
	places = {c: 1 for c in result['winners']}
	order  = [c for c, _ in state['out'] if c not in places]
	for i, c in enumerate(reversed(order)):
		places[c] = len(result['winners']) + 1 + i if not state['teams'] else 2
	for c in COLORS:
		places.setdefault(c, 2)
	return places


def play(state: dict, move: tuple) -> list:
	'''Play a legal move for the side to move and advance the turn. Returns [(color, reason)] for every player knocked out by it.'''

	color = state['turn']
	board = state['board']
	taken = board[move[1]]
	update_rights(state['rights'], board, move)
	state['board'] = apply_move(board, move)
	out = []
	# A king left in check can be taken by another player before its owner gets to move
	if taken and taken[1] == 'K' and taken[0] in state['alive']:
		out.append((taken[0], 'king captured'))
		eliminate(state, taken[0], 'king captured')
	out.extend(advance(state))
	return out


def promotes(color: str, sq: int) -> bool:
	'''Return whether a pawn of a color promotes on a square: the centre line, eight ranks from its own side.'''

	f, r = sq % SIZE, sq // SIZE
	return {'r': r == 7, 'y': r == 6, 'b': f == 7, 'g': f == 6}[color]


def pseudo_moves(board: list, color: str, teams: bool) -> list:
	'''Return moves that follow the piece rules, ignoring whether they leave the king attacked.

	Any piece that isn't the mover's or, in 2v2, their partner's can be captured, frozen pieces of eliminated players included.
	'''

	friend = lambda q: q[0] == color or (teams and TEAMS[q[0]] == TEAMS[color])
	out    = []
	for sq, piece in enumerate(board):
		if piece is None or piece[0] != color:
			continue
		f, r = sq % SIZE, sq // SIZE
		if piece[1] == 'P':
			fdf, fdr = FORWARD[color]
			targets  = []
			nf, nr   = f + fdf, r + fdr
			if on_board(nf, nr) and board[nr * SIZE + nf] is None:
				targets.append(nr * SIZE + nf)
				start = {'r': r == 1, 'y': r == 12, 'b': f == 1, 'g': f == 12}[color]
				if start and on_board(nf + fdf, nr + fdr) and board[(nr + fdr) * SIZE + nf + fdf] is None:
					targets.append((nr + fdr) * SIZE + nf + fdf)
			for side in (-1, 1):
				cf, cr = nf + (side if fdf == 0 else 0), nr + (side if fdr == 0 else 0)
				if on_board(cf, cr):
					q = board[cr * SIZE + cf]
					if q is not None and not friend(q):
						targets.append(cr * SIZE + cf)
			for t in targets:
				if promotes(color, t):
					out.extend((sq, t, p) for p in PROMOTION)
				else:
					out.append((sq, t, None))
			continue
		vectors, slides = MOVES[piece[1]]
		for df, dr in vectors:
			nf, nr = f + df, r + dr
			while on_board(nf, nr):
				q = board[nr * SIZE + nf]
				if q is None:
					out.append((sq, nr * SIZE + nf, None))
				else:
					if not friend(q):
						out.append((sq, nr * SIZE + nf, None))
					break
				if not slides:
					break
				nf, nr = nf + df, nr + dr
	return out


def san(board: list, move: tuple) -> str:
	'''Return a long algebraic name for a move, e.g. Ng1-f3, e2xe4=Q, O-O.'''

	frm, to, promo = move
	piece = board[frm]
	if piece[1] == 'K' and max(abs(to % SIZE - frm % SIZE), abs(to // SIZE - frm // SIZE)) == 2:
		return 'O-O'
	text = ('' if piece[1] == 'P' else piece[1]) + square_name(frm) + ('x' if board[to] else '-') + square_name(to)
	return text + ('=' + promo if promo else '')


def square_index(name: str) -> int:
	'''Return the board index of a square name like h1 or a10.'''

	if len(name) < 2 or name[0] not in FILES or not name[1:].isdigit() or not 1 <= int(name[1:]) <= SIZE:
		raise ValueError('bad square')
	return (int(name[1:]) - 1) * SIZE + FILES.index(name[0])


def square_name(sq: int) -> str:
	'''Return the name of a board index.'''

	return FILES[sq % SIZE] + str(sq // SIZE + 1)


def start_rights() -> dict:
	'''Return each color's castling rights as the squares of its unmoved rooks.'''

	b = new_board()
	return {c: [sq for sq, q in enumerate(b) if q == c + 'R'] for c in COLORS}


def team_won(state: dict) -> bool:
	'''Return whether a 2v2 game is already decided.'''

	return state['teams'] and bool(state['out'])


def update_rights(rights: dict, board: list, move: tuple):
	'''Drop castling rights when a king or rook moves or a rook is captured.'''

	frm, to, _ = move
	piece = board[frm]
	if piece[1] == 'K':
		rights[piece[0]] = []
	for c in COLORS:
		rights[c] = [sq for sq in rights[c] if sq not in (frm, to)]
