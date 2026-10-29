#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/toggles.py

import random

import engine


HOLES      = 4    # walls per game, placed in point-symmetric pairs
STARS      = 4    # bonus squares per game, placed the same way
UPGRADES   = {'N': 'A', 'B': 'A', 'R': 'C', 'Q': 'M'} # what a piece becomes on a bonus square
RULES      = ('koth', 'threecheck', 'atomic', 'drops', 'bonus') # toggles that change the rules rather than the start position
ARMY_SLACK = 2    # how far a random army's value may stray from the normal back rank
ARMY_POOL  = ('N', 'B', 'R', 'Q', 'A', 'C', 'M', 'O', 'G', 'H', 'L')

# Swap name -> (label, piece replaced, replacement)
SWAPS = {
	'nightriders'  : ('Knights become nightriders', 'N', 'H'),
	'camels'       : ('Bishops become camels',      'B', 'L'),
	'cannons'      : ('Rooks become cannons',       'R', 'O'),
	'amazon'       : ('Queen becomes an amazon',    'Q', 'M'),
	'grasshoppers' : ('Knights become grasshoppers', 'N', 'G'),
}


def armies(board: list, variant: engine.Variant, rng: random.Random):
	'''Replace each side's back rank, except the king and corner rooks, with random pieces worth about the same. Black mirrors White.'''

	w     = variant.width
	back  = board[:w]
	slots = [f for f, q in enumerate(back) if q is not None and q != 'K' and not (q == 'R' and f in (0, w - 1))]
	value = sum(engine.ALL_PIECES[back[f]]['value'] for f in slots)
	while True:
		picks = [rng.choice(ARMY_POOL) for _ in slots]
		if abs(sum(engine.ALL_PIECES[p]['value'] for p in picks) - value) <= ARMY_SLACK:
			break
	top = (variant.height - 1) * w
	for f, piece in zip(slots, picks):
		board[f]       = piece
		board[top + f] = piece.lower()


def clean(data: dict) -> dict:
	'''Return only known toggles from a request, keeping at most one swap per piece type.'''

	data = data if isinstance(data, dict) else {}
	out  = {name: True for name in ('holes', 'armies') + RULES if data.get(name)}
	# Explosions and drops have no agreed rules together, explosions win
	if out.get('atomic'):
		out.pop('drops', None)
	swaps, used = [], set()
	for name in SWAPS:
		if name in (data.get('swaps') or []) and SWAPS[name][1] not in used:
			swaps.append(name)
			used.add(SWAPS[name][1])
	if swaps:
		out['swaps'] = swaps
	return out


def holes(board: list, variant: engine.Variant, rng: random.Random):
	'''Put walls on empty middle squares in pairs mirrored through the centre, so both sides face the same board.'''

	for sq in middle_pairs(board, variant, rng, HOLES // 2):
		board[sq] = engine.WALL
		board[variant.size - 1 - sq] = engine.WALL


def middle_pairs(board: list, variant: engine.Variant, rng: random.Random, count: int) -> list:
	'''Pick empty squares in the lower middle of the board whose mirror through the centre is empty too.'''

	w, h  = variant.width, variant.height
	first = variant.pawn_rank + 1
	empty = [r * w + f for r in range(first, h // 2) for f in range(w) if board[r * w + f] is None and board[variant.size - 1 - (r * w + f)] is None]
	return rng.sample(empty, count)


def start_fen(variant: engine.Variant, options: dict, rng: random.Random = None) -> str:
	'''Return the starting FEN for a variant with the start position toggles applied.

	:param variant: the mode's variant
	:param options: toggles, e.g. {'holes': True, 'armies': True, 'swaps': ['amazon'], 'drops': True}
	:param rng: random source, a fresh one if not given
	'''

	rng = rng or random.Random()
	pos = engine.Position(variant=variant)
	if options.get('armies'):
		armies(pos.board, variant, rng)
	# Swaps go after the army roll so they apply to whatever ended up on the board
	for name in options.get('swaps', []):
		_, old, new = SWAPS[name]
		pos.board = [new if q == old else new.lower() if q == old.lower() else q for q in pos.board]
	if options.get('holes'):
		holes(pos.board, variant, rng)
	fen = engine.fen(pos).split()
	# The FEN of the rules being added: an empty hand for drops, the check counter for three-check, the bonus squares
	if options.get('drops'):
		fen[0] += '[]'
	if options.get('threecheck'):
		fen.insert(4, '3+3')
	if options.get('bonus'):
		stars = middle_pairs(pos.board, variant, rng, STARS // 2)
		fen.append('{' + ','.join(variant.square_name(sq) for sq in sorted(stars + [variant.size - 1 - sq for sq in stars])) + '}')
	return ' '.join(fen)
