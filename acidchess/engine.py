#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/engine.py

import re


FILES     = 'abcdefghijkl'
WHITE     = 'w'
BLACK     = 'b'
WALL      = '*'
START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
UCI_RE    = re.compile(r'^([a-l]\d+)([a-l]\d+)([a-z]?)$')
DROP_RE   = re.compile(r'^([A-Z])@([a-l]\d+)$')
DROP      = -1 # from square of a drop move, which is (DROP, to, piece kind)

ORTHO  = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAG   = ((1, 1), (1, -1), (-1, 1), (-1, -1))
KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
CAMEL  = ((1, 3), (3, 1), (3, -1), (1, -3), (-1, -3), (-3, -1), (-3, 1), (-1, 3))

# Every non-pawn piece is a list of (direction vectors, slides, mode). Modes:
#   mc  moves and captures      m  moves only      c  captures only
#   p   captures by jumping exactly one piece of either color (cannon)
#   g   must hop the first piece on the line and lands right behind it, capturing an enemy there (grasshopper)
PIECES = {
	'N' : {'value': 3, 'moves': ((KNIGHT, False, 'mc'),)},
	'B' : {'value': 3, 'moves': ((DIAG, True, 'mc'),)},
	'R' : {'value': 5, 'moves': ((ORTHO, True, 'mc'),)},
	'Q' : {'value': 9, 'moves': ((ORTHO + DIAG, True, 'mc'),)},
	'K' : {'value': 0, 'moves': ((ORTHO + DIAG, False, 'mc'),)},
}

# Fairy pieces, used by the Big Board modes and the piece toggles
FAIRY = {
	'A' : {'value': 7,  'moves': ((DIAG, True, 'mc'), (KNIGHT, False, 'mc'))},      # archbishop
	'C' : {'value': 8,  'moves': ((ORTHO, True, 'mc'), (KNIGHT, False, 'mc'))},     # chancellor
	'M' : {'value': 12, 'moves': ((ORTHO + DIAG, True, 'mc'), (KNIGHT, False, 'mc'))}, # amazon
	'O' : {'value': 4,  'moves': ((ORTHO, True, 'm'), (ORTHO, True, 'p'))},         # cannon
	'G' : {'value': 2,  'moves': ((ORTHO + DIAG, True, 'g'),)},                     # grasshopper
	'H' : {'value': 5,  'moves': ((KNIGHT, True, 'mc'),)},                          # nightrider
	'L' : {'value': 3,  'moves': ((CAMEL, False, 'mc'),)},                          # camel
}
ALL_PIECES = {**PIECES, **FAIRY}


class Variant:
	'''A rule set: board size, start position, pieces, castling, promotion and how the game is won.'''

	def __init__(self, name: str = 'chess', width: int = 8, height: int = 8, start_fen: str = START_FEN, pieces: dict = None, promotion: tuple = None, castling: bool = True, king_capture: bool = False, pawn_rank: int = 1, koth: bool = False, check_limit: int = 0, atomic: bool = False, drops: bool = False, upgrades: dict = None):
		'''Build a variant and precompute its move tables.

		:param name: variant name
		:param width: number of files *(up to 12)*
		:param height: number of ranks
		:param start_fen: starting position, walls are written as *
		:param pieces: non-pawn piece definitions, defaults to the standard set *(must include K)*
		:param promotion: piece letters a pawn may promote to, defaults to every piece in the start position except the king, most valuable first
		:param castling: whether castling exists
		:param king_capture: no check rules, the game is won by capturing the king
		:param pawn_rank: rank pawns start on and may double step from, counted from each side's edge *(0 based)*
		:param koth: king of the hill, a king reaching one of the four centre squares wins
		:param check_limit: checks that win the game *(3 for three-check)*, 0 for none
		:param atomic: captures explode, removing the capturing piece and every non-pawn next to the target square
		:param drops: captured pieces join the capturer's hand and can be dropped on any empty square instead of moving
		:param upgrades: bonus squares, piece kind -> what it becomes when it lands on a star. Each star works once
		'''

		self.name         = name
		self.width        = width
		self.height       = height
		self.size         = width * height
		self.start_fen    = start_fen
		self.pieces       = pieces or PIECES
		self.king_capture = king_capture
		self.pawn_rank    = pawn_rank
		self.check_limit  = check_limit
		self.atomic       = atomic
		self.drops        = drops
		self.upgrades     = upgrades or {}
		self.adjacent     = [[r * width + f for r in range(sq // width - 1, sq // width + 2) for f in range(sq % width - 1, sq % width + 2) if 0 <= r < height and 0 <= f < width and r * width + f != sq] for sq in range(width * height)]
		self.hill         = {r * width + f for r in (height // 2 - 1, height // 2) for f in (width // 2 - 1, width // 2)} if koth else set()
		start             = {q.upper() for q in start_fen.split()[0] if q.isalpha() and q.upper() not in ('K', 'P')}
		self.promotion    = promotion or tuple(sorted(start, key=lambda k: (-self.pieces[k]['value'], k)))
		self.moves        = {}  # kind -> per square list of (ray, mode)
		self.attacks      = {}  # kind -> per square list of rays walked backwards from a target, for pieces that can capture that way
		for kind, info in self.pieces.items():
			self.moves[kind]   = [self.build_rays(sq, info['moves'], 1) for sq in range(self.size)]
			self.attacks[kind] = [[(ray, mode) for ray, mode in self.build_rays(sq, info['moves'], -1) if mode != 'm'] for sq in range(self.size)]
		self.castling = {}
		self.castling = self.build_castling() if castling else {}


	def build_castling(self) -> dict:
		'''Work out castling from the start position: the king castles with the corner rooks and ends two files in from the edge, at least two files from where it started.

		Returns castling right -> (king from, king to, rook from, rook to, squares that must be empty, squares that must not be attacked).
		'''

		board = Position(self.start_fen, self).board
		out   = {}
		w     = self.width
		for right, rank, king, rook in (('K', 0, 'K', 'R'), ('Q', 0, 'K', 'R'), ('k', self.height - 1, 'k', 'r'), ('q', self.height - 1, 'k', 'r')):
			row = [board[rank * w + f] for f in range(w)]
			if king not in row:
				continue
			kf = row.index(king)
			rf = w - 1 if right.upper() == 'K' else 0
			if row[rf] != rook:
				continue
			kt   = w - 2 if right.upper() == 'K' else 2
			rt   = kt - 1 if right.upper() == 'K' else kt + 1
			if abs(kt - kf) < 2:
				continue
			span = set(range(min(kf, kt), max(kf, kt) + 1)) | set(range(min(rf, rt), max(rf, rt) + 1))
			out[right] = (rank * w + kf, rank * w + kt, rank * w + rf, rank * w + rt, tuple(sorted(rank * w + f for f in span if f not in (kf, rf))), tuple(rank * w + f for f in range(min(kf, kt), max(kf, kt) + 1)))
		return out


	def build_rays(self, sq: int, moves: tuple, sign: int) -> list:
		'''Return the rays a piece travels from a square as (list of squares, mode) pairs.

		:param sq: square index
		:param moves: piece movement definition
		:param sign: 1 for the piece's own direction, -1 to walk backwards when looking for attackers
		'''

		f, r = sq % self.width, sq // self.width
		out  = []
		for vectors, slides, mode in moves:
			for df, dr in vectors:
				df, dr = df * sign, dr * sign
				ray    = []
				nf, nr = f + df, r + dr
				while 0 <= nf < self.width and 0 <= nr < self.height:
					ray.append(nr * self.width + nf)
					if not slides:
						break
					nf, nr = nf + df, nr + dr
				if ray:
					out.append((ray, mode))
		return out


	def square_index(self, name: str) -> int:
		'''Return the board index for a square name like e4 or a10.'''

		if len(name) < 2 or name[0] not in FILES[:self.width] or not name[1:].isdigit():
			raise ValueError('bad square')
		r = int(name[1:]) - 1
		if not 0 <= r < self.height:
			raise ValueError('bad square')
		return r * self.width + FILES.index(name[0])


	def square_name(self, sq: int) -> str:
		'''Return the square name like e4 for a board index.'''

		return FILES[sq % self.width] + str(sq // self.width + 1)


class Position:
	'''A position: board, side to move, castling rights, en passant square and move counters.'''

	__slots__ = ('variant', 'board', 'turn', 'castling', 'ep', 'halfmove', 'fullmove', 'checks', 'hand', 'promoted', 'stars')

	def __init__(self, fen: str = None, variant: Variant = None):
		'''Load a position from FEN.

		:param fen: FEN string, defaults to the variant's start position
		:param variant: rule set, defaults to classic chess
		'''

		self.variant = variant = variant or CLASSIC
		parts = (fen or variant.start_fen).split()
		if len(parts) < 4:
			raise ValueError('bad fen')
		# Pieces in hand follow the board in brackets, e.g. [NPp], and promoted pieces carry a ~ so they return to hand as pawns
		placement, _, pocket = parts[0].partition('[')
		self.hand     = {WHITE: {}, BLACK: {}}
		self.promoted = set()
		for ch in pocket.rstrip(']'):
			if ch.upper() not in variant.pieces and ch.upper() != 'P' or ch.upper() == 'K':
				raise ValueError('bad fen')
			side = self.hand[WHITE if ch.isupper() else BLACK]
			side[ch.upper()] = side.get(ch.upper(), 0) + 1
		rows = placement.split('/')
		if len(rows) != variant.height:
			raise ValueError('bad fen')
		self.board = [None] * variant.size
		for i, row in enumerate(rows):
			r      = variant.height - 1 - i
			f      = 0
			digits = ''
			for ch in row + ' ':
				if ch.isdigit():
					digits += ch
					continue
				if digits:
					f += int(digits)
					digits = ''
				if ch == ' ':
					break
				if ch == '~':
					self.promoted.add(r * variant.width + f - 1)
					continue
				if ch != WALL and ch.upper() not in variant.pieces and ch.upper() != 'P':
					raise ValueError('bad fen')
				if f >= variant.width:
					raise ValueError('bad fen')
				self.board[r * variant.width + f] = ch
				f += 1
			if f != variant.width:
				raise ValueError('bad fen')
		if parts[1] not in (WHITE, BLACK):
			raise ValueError('bad fen')
		self.turn     = parts[1]
		self.castling = '' if parts[2] == '-' else ''.join(c for c in parts[2] if c in variant.castling)
		self.ep       = None if parts[3] == '-' else variant.square_index(parts[3])
		# Bonus squares are our own extension, written as a last field like {c4,f5}
		self.stars = set()
		if parts[-1].startswith('{'):
			self.stars = {variant.square_index(name) for name in parts.pop()[1:-1].split(',') if name}
		# Check counting variants write the checks each side still needs after the en passant square, e.g. 3+3
		self.checks = [variant.check_limit, variant.check_limit]
		if len(parts) > 4 and '+' in parts[4]:
			self.checks = [int(n) for n in parts.pop(4).split('+')]
		self.halfmove = int(parts[4]) if len(parts) > 4 else 0
		self.fullmove = int(parts[5]) if len(parts) > 5 else 1


	def copy(self) -> 'Position':
		'''Return a copy of this position.'''

		p = Position.__new__(Position)
		p.variant, p.board, p.turn, p.castling, p.ep, p.halfmove, p.fullmove, p.checks = self.variant, self.board[:], self.turn, self.castling, self.ep, self.halfmove, self.fullmove, self.checks[:]
		p.hand     = {WHITE: dict(self.hand[WHITE]), BLACK: dict(self.hand[BLACK])}
		p.promoted = set(self.promoted)
		p.stars    = set(self.stars)
		return p


CLASSIC = Variant()


def apply_move(pos: Position, move: tuple) -> Position:
	'''Return the position after a move, without checking legality.

	:param pos: position to move from
	:param move: (from, to, promotion kind or None)
	'''

	frm, to, promo = move
	v      = pos.variant
	p      = pos.copy()
	b      = p.board
	if frm == DROP:
		mover = pos.turn
		b[to] = promo if mover == WHITE else promo.lower()
		p.hand[mover][promo] -= 1
		if not p.hand[mover][promo]:
			del p.hand[mover][promo]
		p.ep        = None
		p.halfmove += 1
		if mover == BLACK:
			p.fullmove += 1
		p.turn = BLACK if mover == WHITE else WHITE
		if v.check_limit and in_check(p):
			p.checks[0 if mover == WHITE else 1] -= 1
		return p
	piece  = b[frm]
	kind   = piece.upper()
	white  = piece.isupper()
	target = b[to]
	p.ep   = None
	if v.drops:
		# What was taken goes to the capturer's hand, a promoted piece goes back as a pawn
		taken = to if target is not None else (to - v.width if white else to + v.width) if kind == 'P' and to == pos.ep else None
		if taken is not None:
			got = 'P' if taken in p.promoted else b[taken].upper()
			hand = p.hand[WHITE if white else BLACK]
			hand[got] = hand.get(got, 0) + 1
			p.promoted.discard(taken)
		if frm in p.promoted:
			p.promoted.discard(frm)
			p.promoted.add(to)
		elif kind == 'P' and promo:
			p.promoted.add(to)
	if kind == 'P':
		if to == pos.ep and target is None:
			b[to - v.width if white else to + v.width] = None
		elif abs(to - frm) == 2 * v.width:
			p.ep = (frm + to) // 2
		if promo:
			piece = promo if white else promo.lower()
	elif kind == 'K' and abs(to % v.width - frm % v.width) >= 2:
		# A king only moves two or more files when castling
		for kf, kt, rf, rt, _, _ in v.castling.values():
			if (kf, kt) == (frm, to):
				b[rt], b[rf] = b[rf], None
				break
	if to in p.stars:
		# The first piece to land on a star uses it up, and some pieces are upgraded by it
		p.stars.discard(to)
		up = v.upgrades.get(piece.upper())
		if up:
			piece = up if white else up.lower()
	b[frm] = None
	b[to]  = piece
	if v.atomic and (target is not None or (kind == 'P' and to == pos.ep)):
		# The capturing piece, the captured piece and every non-pawn around them are destroyed
		b[to] = None
		for s in v.adjacent[to]:
			if b[s] not in (None, WALL) and b[s].upper() != 'P':
				b[s] = None
		p.castling = ''.join(right for right in p.castling if b[v.castling[right][0]] == ('K' if right.isupper() else 'k') and b[v.castling[right][2]] == ('R' if right.isupper() else 'r'))
	if p.castling:
		lost = ''.join(right for right in p.castling if frm in (v.castling[right][0], v.castling[right][2]) or to in (v.castling[right][0], v.castling[right][2]))
		if lost:
			p.castling = ''.join(c for c in p.castling if c not in lost)
	p.halfmove = 0 if kind == 'P' or target is not None else pos.halfmove + 1
	if not white:
		p.fullmove += 1
	p.turn = BLACK if white else WHITE
	if v.check_limit and in_check(p):
		p.checks[0 if white else 1] -= 1
	return p


def attacked(pos: Position, sq: int, by: str) -> bool:
	'''Return whether a square is attacked by a color.

	:param pos: position
	:param sq: square index
	:param by: attacking color
	'''

	v     = pos.variant
	board = pos.board
	white = by == WHITE
	if v.atomic:
		# Kings can't capture in atomic, and nothing next to the enemy king can be taken without blowing it up
		enemy_king = 'K' if white else 'k'
		if any(board[s] == enemy_king for s in v.adjacent[sq]):
			return False
	for kind, per_square in v.attacks.items():
		if v.atomic and kind == 'K':
			continue
		want = kind if white else kind.lower()
		for ray, mode in per_square[sq]:
			if mode == 'g':
				# A grasshopper lands right behind its hurdle, so the hurdle sits next to the target and the grasshopper is the next piece beyond it
				if board[ray[0]] is None:
					continue
				ray = ray[1:]
			skip = 1 if mode == 'p' else 0
			for t in ray:
				q = board[t]
				if q is not None:
					if skip:
						skip = 0
						continue
					if q == want:
						return True
					break
	# A pawn attacks diagonally forward, so look one rank behind the target from the attacker's side
	f, r = sq % v.width, sq // v.width
	pr   = r - 1 if white else r + 1
	pawn = 'P' if white else 'p'
	if 0 <= pr < v.height:
		for pf in (f - 1, f + 1):
			if 0 <= pf < v.width and board[pr * v.width + pf] == pawn:
				return True
	return False


def fen(pos: Position) -> str:
	'''Return the FEN string for a position.'''

	v    = pos.variant
	rows = []
	for r in range(v.height - 1, -1, -1):
		row, empty = '', 0
		for f in range(v.width):
			q = pos.board[r * v.width + f]
			if q is None:
				empty += 1
			else:
				row += (str(empty) if empty else '') + q + ('~' if r * v.width + f in pos.promoted else '')
				empty = 0
		rows.append(row + (str(empty) if empty else ''))
	if v.drops:
		order = lambda k: (-v.pieces[k]['value'] if k in v.pieces else 0, k)
		rows[-1] += '[' + ''.join(k * n for k, n in sorted(pos.hand[WHITE].items(), key=lambda i: order(i[0]))) + ''.join(k.lower() * n for k, n in sorted(pos.hand[BLACK].items(), key=lambda i: order(i[0]))) + ']'
	ep = v.square_name(pos.ep) if pos.ep is not None else '-'
	checks = f' {pos.checks[0]}+{pos.checks[1]}' if v.check_limit else ''
	stars  = ' {' + ','.join(v.square_name(sq) for sq in sorted(pos.stars)) + '}' if v.upgrades else ''
	return f'{"/".join(rows)} {pos.turn} {pos.castling or "-"} {ep}{checks} {pos.halfmove} {pos.fullmove}{stars}'


def in_check(pos: Position, color: str = None) -> bool:
	'''Return whether a side's king is attacked.

	:param pos: position
	:param color: side to test, defaults to the side to move
	'''

	color = color or pos.turn
	king  = 'K' if color == WHITE else 'k'
	if king not in pos.board:
		return False
	return attacked(pos, pos.board.index(king), BLACK if color == WHITE else WHITE)


def insufficient_material(pos: Position) -> bool:
	'''Return whether neither side can ever checkmate (dead position).

	Covers K v K, K + minor v K, and positions where every remaining minor piece is a bishop on one square colour. Any other piece counts as mating material.
	'''

	w      = pos.variant.width
	others = [(sq, q.upper()) for sq, q in enumerate(pos.board) if q is not None and q not in (WALL, 'K', 'k')]
	if not others:
		return True
	if len(others) == 1 and others[0][1] in ('N', 'B'):
		return True
	if all(kind == 'B' for _, kind in others):
		return len({(sq % w + sq // w) % 2 for sq, _ in others}) == 1
	return False


def legal_moves(pos: Position) -> list:
	'''Return every legal move in a position. With king capture, any move that follows the piece rules is legal.'''

	if pos.variant.king_capture:
		return pseudo_moves(pos)
	moves = []
	color = pos.turn
	enemy = BLACK if color == WHITE else WHITE
	king  = 'K' if color == WHITE else 'k'
	theirs = 'k' if color == WHITE else 'K'
	for move in pseudo_moves(pos):
		after = apply_move(pos, move)
		if pos.variant.atomic:
			# Blowing up your own king is illegal, blowing up theirs wins even out of check
			if king not in after.board:
				continue
			if theirs not in after.board:
				moves.append(move)
				continue
		if king in after.board and attacked(after, after.board.index(king), enemy):
			continue
		moves.append(move)
	return moves


def mating_material(pos: Position, color: str) -> bool:
	'''Return whether a side could still checkmate by some series of legal moves (used for flag fall).

	Same rule as lichess: a lone knight needs an enemy pawn, minor or rook to block the enemy king, and bishops all on one square colour need an enemy pawn or knight.

	:param pos: position
	:param color: side to test
	'''

	if pos.variant.drops:
		return True
	board  = pos.board
	w      = pos.variant.width
	white  = color == WHITE
	mine   = [q.upper() for q in board if q not in (None, WALL, 'K', 'k') and q.isupper() == white]
	theirs = [q.upper() for q in board if q not in (None, WALL, 'K', 'k') and q.isupper() != white]
	if any(kind not in ('N', 'B') for kind in mine):
		return True
	if 'N' in mine:
		return len(mine) > 1 or any(kind != 'Q' for kind in theirs)
	if 'B' in mine:
		bishops = [sq for sq, q in enumerate(board) if q in ('B', 'b')]
		same    = len({(sq % w + sq // w) % 2 for sq in bishops}) == 1
		return not same or any(kind in ('P', 'N') for kind in theirs)
	return False


def move_from_uci(text: str, variant: Variant = None) -> tuple:
	'''Parse a UCI move string like e2e4, e7e8q or a9a10 into a move tuple.'''

	variant = variant or CLASSIC
	text    = (text or '').strip()
	drop    = DROP_RE.match(text)
	if drop:
		if drop.group(1) not in variant.pieces and drop.group(1) != 'P' or drop.group(1) == 'K':
			raise ValueError('bad move')
		return (DROP, variant.square_index(drop.group(2)), drop.group(1))
	match = UCI_RE.match(text)
	if not match:
		raise ValueError('bad move')
	promo = match.group(3).upper() or None
	if promo is not None and promo not in variant.promotion:
		raise ValueError('bad move')
	return (variant.square_index(match.group(1)), variant.square_index(match.group(2)), promo)


def move_to_uci(move: tuple, variant: Variant = None) -> str:
	'''Return the UCI string for a move tuple.'''

	variant = variant or CLASSIC
	if move[0] == DROP:
		return f'{move[2]}@{variant.square_name(move[1])}'
	return variant.square_name(move[0]) + variant.square_name(move[1]) + (move[2].lower() if move[2] else '')


def perft(pos: Position, depth: int) -> int:
	'''Count leaf nodes of the legal move tree, used to validate move generation.'''

	if depth == 0:
		return 1
	if pos.variant.king_capture and winner(pos):
		return 0
	moves = legal_moves(pos)
	if depth == 1:
		return len(moves)
	return sum(perft(apply_move(pos, m), depth - 1) for m in moves)


def position_key(pos: Position) -> str:
	'''Return the repetition key for a position.

	Positions repeat when the same side is to move with the same pieces, castling rights and en passant options, and en passant only counts when a capture is actually legal.
	'''

	ep = '-'
	if pos.ep is not None and any(m[0] != DROP and pos.board[m[0]] in ('P', 'p') and m[1] == pos.ep for m in legal_moves(pos)):
		ep = pos.variant.square_name(pos.ep)
	key = ''.join(q or '.' for q in pos.board) + pos.turn + (pos.castling or '-') + ep + (f'{pos.checks[0]}+{pos.checks[1]}' if pos.variant.check_limit else '')
	if pos.variant.drops:
		key += fen(pos).split()[0].partition('[')[2] + ','.join(map(str, sorted(pos.promoted)))
	if pos.stars:
		key += '{' + ','.join(map(str, sorted(pos.stars))) + '}'
	return key


def pseudo_moves(pos: Position) -> list:
	'''Return moves that follow piece movement rules but may leave the king in check.'''

	v     = pos.variant
	b     = pos.board
	w     = v.width
	white = pos.turn == WHITE
	moves = []
	for sq, piece in enumerate(b):
		if piece is None or piece == WALL or piece.isupper() != white:
			continue
		kind = piece.upper()
		if kind == 'P':
			step    = w if white else -w
			r       = sq // w
			f       = sq % w
			start   = v.pawn_rank if white else v.height - 1 - v.pawn_rank
			last    = v.height - 1 if white else 0
			fwd     = sq + step
			targets = []
			if 0 <= fwd < v.size:
				if b[fwd] is None:
					targets.append(fwd)
					if r == start and b[fwd + step] is None:
						targets.append(fwd + step)
				for df in (-1, 1):
					if 0 <= f + df < w:
						t = fwd + df
						q = b[t]
						if (q is not None and q != WALL and q.isupper() != white) or (t == pos.ep and q is None):
							targets.append(t)
			for t in targets:
				if t // w == last:
					moves.extend((sq, t, p) for p in v.promotion)
				else:
					moves.append((sq, t, None))
			continue
		for ray, mode in v.moves[kind][sq]:
			if mode == 'p':
				screen = False
				for t in ray:
					q = b[t]
					if q is None:
						continue
					if not screen:
						screen = True
						continue
					if q != WALL and q.isupper() != white:
						moves.append((sq, t, None))
					break
				continue
			if mode == 'g':
				for i, t in enumerate(ray):
					if b[t] is not None:
						if i + 1 < len(ray):
							land = ray[i + 1]
							q    = b[land]
							if q is None or (q != WALL and q.isupper() != white):
								moves.append((sq, land, None))
						break
				continue
			for t in ray:
				q = b[t]
				if q is None:
					if 'm' in mode:
						moves.append((sq, t, None))
				else:
					if q != WALL and q.isupper() != white and 'c' in mode and not (v.atomic and kind == 'K'):
						moves.append((sq, t, None))
					break
	if v.drops:
		last = v.size - w
		for kind, count in pos.hand[pos.turn].items():
			if count:
				moves.extend((DROP, t, kind) for t in range(v.size) if b[t] is None and not (kind == 'P' and (t < w or t >= last)))
	enemy = BLACK if white else WHITE
	for right in pos.castling:
		if right.isupper() != white:
			continue
		kf, kt, rf, rt, empty, safe = v.castling[right]
		if b[kf] != ('K' if white else 'k') or b[rf] != ('R' if white else 'r'):
			continue
		if any(b[s] is not None for s in empty):
			continue
		if not v.king_capture and any(attacked(pos, s, enemy) for s in safe):
			continue
		moves.append((kf, kt, None))
	return moves


def san(pos: Position, move: tuple, legal: list = None) -> str:
	'''Return the Standard Algebraic Notation for a legal move.

	:param pos: position before the move
	:param move: move tuple
	:param legal: legal moves in pos, computed if not given
	'''

	v = pos.variant
	frm, to, promo = move
	if frm == DROP:
		text = f'{"" if promo == "P" else promo}@{v.square_name(to)}'
		after = apply_move(pos, move)
		if in_check(after):
			text += '#' if not legal_moves(after) else '+'
		return text
	piece = pos.board[frm]
	kind  = piece.upper()
	if kind == 'K' and abs(to % v.width - frm % v.width) >= 2:
		text = 'O-O' if to > frm else 'O-O-O'
	else:
		capture = pos.board[to] is not None or (kind == 'P' and to == pos.ep)
		if kind == 'P':
			text = (FILES[frm % v.width] + 'x' if capture else '') + v.square_name(to)
			if promo:
				text += '=' + promo
		else:
			legal  = legal if legal is not None else legal_moves(pos)
			rivals = [m[0] for m in legal if m[1] == to and m[0] not in (frm, DROP) and pos.board[m[0]] == piece]
			text   = kind
			if rivals:
				if all(r % v.width != frm % v.width for r in rivals):
					text += FILES[frm % v.width]
				elif all(r // v.width != frm // v.width for r in rivals):
					text += str(frm // v.width + 1)
				else:
					text += v.square_name(frm)
			text += ('x' if capture else '') + v.square_name(to)
			if to in pos.stars and kind in v.upgrades:
				text += '=' + v.upgrades[kind]
	after = apply_move(pos, move)
	if v.king_capture or v.atomic and winner(after):
		if winner(after):
			text += '#'
	elif in_check(after):
		text += '#' if not legal_moves(after) else '+'
	return text


def status(pos: Position, keys: list) -> tuple:
	'''Return (result, reason) if the game is over in this position, else None.

	:param pos: current position
	:param keys: repetition keys of every position so far, including the current one
	'''

	v = pos.variant
	if v.check_limit and min(pos.checks) <= 0:
		return ('1-0' if pos.checks[0] <= 0 else '0-1', 'three-check' if v.check_limit == 3 else f'{v.check_limit} checks')
	if v.hill:
		for king, result in (('K', '1-0'), ('k', '0-1')):
			if king in pos.board and pos.board.index(king) in v.hill:
				return (result, 'king of the hill')
	if v.king_capture or v.atomic:
		won = winner(pos)
		if won:
			return ('1-0' if won == WHITE else '0-1', 'king captured' if v.king_capture else 'explosion')
	if not v.king_capture and not legal_moves(pos):
		if in_check(pos):
			return ('0-1' if pos.turn == WHITE else '1-0', 'checkmate')
		return ('1/2-1/2', 'stalemate')
	# A lone king can still win king of the hill, and in atomic only bare kings are a dead draw
	if v.atomic:
		if all(q in (None, WALL, 'K', 'k') for q in pos.board):
			return ('1/2-1/2', 'insufficient material')
	elif not v.king_capture and not v.hill and not v.drops and insufficient_material(pos):
		return ('1/2-1/2', 'insufficient material')
	if keys and keys.count(keys[-1]) >= 3:
		return ('1/2-1/2', 'threefold repetition')
	if pos.halfmove >= 100:
		return ('1/2-1/2', '50-move rule')
	return None


def winner(pos: Position) -> str:
	'''Return the color that captured the other king, or None.'''

	if 'K' not in pos.board:
		return BLACK
	if 'k' not in pos.board:
		return WHITE
	return None
