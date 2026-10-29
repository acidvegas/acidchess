#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/recon.py

import engine
from engine import BLACK, WHITE


# Reconnaissance Blind Chess: standard pieces, no check, capture the king to win
VARIANT = engine.Variant('recon', king_capture=True)


def capture_square(pos: engine.Position, move: tuple) -> int:
	'''Return the square where a move captures a piece, or None.'''

	frm, to, _ = move
	if pos.board[to] is not None:
		return to
	if pos.board[frm] in ('P', 'p') and to == pos.ep:
		return to - pos.variant.width if pos.turn == WHITE else to + pos.variant.width
	return None


def pass_turn(pos: engine.Position) -> engine.Position:
	'''Return the position after a pass or a failed move: nothing moves and the turn goes over.'''

	p = pos.copy()
	p.ep = None
	p.halfmove += 1
	if pos.turn == BLACK:
		p.fullmove += 1
	p.turn = BLACK if pos.turn == WHITE else WHITE
	return p


def play(pos: engine.Position, move: tuple) -> tuple:
	'''Play a requested move on the true board. Returns (new position, move actually made or None, capture square or None).

	:param pos: true position
	:param move: requested move tuple, or None to pass
	'''

	taken = resolve(pos, move) if move else None
	if taken is None:
		return pass_turn(pos), None, None
	return engine.apply_move(pos, taken), taken, capture_square(pos, taken)


def requested_moves(pos: engine.Position) -> list:
	'''Return every move the side to move may ask for, knowing only where its own pieces are.

	That is every move with the enemy pieces taken off the board, plus every diagonal pawn capture onto a square not holding one of its own pieces.
	'''

	v     = pos.variant
	w     = v.width
	white = pos.turn == WHITE
	view  = pos.copy()
	view.board = [q if q is not None and q.isupper() == white else None for q in pos.board]
	moves = engine.pseudo_moves(view)
	last  = v.height - 1 if white else 0
	pawn  = 'P' if white else 'p'
	for sq, q in enumerate(view.board):
		if q != pawn:
			continue
		r = sq // w + (1 if white else -1)
		for f in (sq % w - 1, sq % w + 1):
			if 0 <= f < w and 0 <= r < v.height and view.board[r * w + f] is None:
				t = r * w + f
				if r == last:
					moves.extend((sq, t, p) for p in v.promotion)
				else:
					moves.append((sq, t, None))
	return list(dict.fromkeys(moves))


def resolve(pos: engine.Position, move: tuple) -> tuple:
	'''Return the move that actually happens on the true board, or None if it fails.

	A move that follows the piece rules on the true board happens as asked. Castling fails if anything stands between king and rook. A pawn, rook, bishop or queen whose path is blocked moves as far as it legally can along that path, capturing the blocker if it is an enemy piece. Anything else fails.
	'''

	frm, to, promo = move
	v      = pos.variant
	piece  = pos.board[frm]
	kind   = piece.upper()
	legal  = engine.pseudo_moves(pos)
	if kind == 'P' and promo is None and to // v.width in (0, v.height - 1):
		promo = 'Q'
		move  = (frm, to, promo)
	if move in legal:
		return move
	if kind == 'K' and abs(to % v.width - frm % v.width) >= 2:
		return None
	if kind not in ('P', 'R', 'B', 'Q'):
		return None
	# Walk back from the target towards the piece and take the first square that works
	ff, fr = frm % v.width, frm // v.width
	tf, tr = to % v.width, to // v.width
	df, dr = (tf > ff) - (tf < ff), (tr > fr) - (tr < fr)
	if (tf - ff) * dr != (tr - fr) * df:
		return None
	f, r = tf - df, tr - dr
	while (f, r) != (ff, fr):
		candidate = (frm, r * v.width + f, promo if r in (0, v.height - 1) and kind == 'P' else None)
		if candidate in legal:
			return candidate
		f, r = f - df, r - dr
	return None


def sense(pos: engine.Position, sq: int) -> list:
	'''Return [(square, piece or None)] for the 3x3 window centred on a square, clipped to the board.'''

	v    = pos.variant
	f, r = sq % v.width, sq // v.width
	return [(nr * v.width + nf, pos.board[nr * v.width + nf]) for nr in (r + 1, r, r - 1) for nf in (f - 1, f, f + 1) if 0 <= nf < v.width and 0 <= nr < v.height]


def status(pos: engine.Position) -> tuple:
	'''Return (result, reason) if the game is over, else None. There is no check, stalemate or repetition, only king capture and the 50-move rule.'''

	won = engine.winner(pos)
	if won:
		return ('1-0' if won == WHITE else '0-1', 'king captured')
	if pos.halfmove >= 100:
		return ('1/2-1/2', '50-move rule')
	return None
