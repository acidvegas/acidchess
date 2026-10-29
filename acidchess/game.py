#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/game.py

import time

import engine
import four
import fourgame
import recon
import toggles
from storage import rating_of, record_bot_game, record_game


TIME_CONTROLS = {'1+0': (1, 0), '3+0': (3, 0), '3+2': (3, 2), '5+0': (5, 0), '10+0': (10, 0), '10+5': (10, 5), '15+10': (15, 10), '30+0': (30, 0)}
COLORS        = ('w', 'b')
CHAT_MAX      = 100
CHAT_TEXT_MAX = 200
NAMES         = {'P': 'pawn', 'N': 'knight', 'B': 'bishop', 'R': 'rook', 'Q': 'queen', 'K': 'king'}
WATCH_DELAY   = 4 # plies spectators trail behind in Reconnaissance Blind, so a player can't watch their own game for hints
VARIANTS      = {} # (mode, start FEN, rule toggles) -> Variant, for games whose toggles changed the rules or start position
VARIANTS_MAX  = 500

MODES = {
	'classic' : {'name': 'Classic',              'variant': engine.CLASSIC},
	'recon'   : {'name': 'Reconnaissance Blind', 'variant': recon.VARIANT},
	'big8'    : {'name': 'Big Board 10x8',       'variant': engine.Variant('big8', width=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces=engine.ALL_PIECES)},
	'big10'   : {'name': 'Big Board 10x10',      'variant': engine.Variant('big10', width=10, height=10, start_fen='rnabqkbcnr/olhg2ghlo/pppppppppp/10/10/10/10/PPPPPPPPPP/OLHG2GHLO/RNABQKBCNR w KQkq - 0 1', pieces=engine.ALL_PIECES, pawn_rank=2)},
	'four'    : {'name': '4-Player',             'variant': None, 'teams': False},
	'teams'   : {'name': '4-Player 2v2',         'variant': None, 'teams': True},
}


def check_flag(room: dict) -> bool:
	'''End the game if the side to move has run out of time. Returns True if it ended.'''

	if is_four(room):
		return fourgame.check_flag(room)
	game = room['game']
	if game['result'] or game['clock_at'] is None:
		return False
	turn = position(room).turn
	if clock_remaining(game, turn) > 0:
		return False
	game['clock'][turn] = 0
	other = opponent(turn)
	if mode(room) == 'recon' or engine.mating_material(position(room), other):
		finish(room, '1-0' if other == 'w' else '0-1', 'timeout')
	else:
		finish(room, '1/2-1/2', 'timeout vs insufficient material')
	return True


def clock_remaining(game: dict, color: str) -> int:
	'''Return a side's remaining clock time in milliseconds, counting the running turn.'''

	ms = game['clock'][color]
	if game['clock_at'] is not None and game['fen'].split()[1] == color:
		ms -= int((time.time() - game['clock_at']) * 1000)
	return max(0, ms)


def end_turn(room: dict, color: str, after: engine.Position, entry: dict):
	'''Record a finished turn: update the clock, the position and the move list.'''

	game = room['game']
	if game['clock_at'] is not None:
		game['clock'][color] = clock_remaining(game, color) + game['increment'] * 1000
	game['fen']    = engine.fen(after)
	entry['color'] = color
	entry['fen']   = game['fen']
	game['moves'].append(entry)
	game['keys'].append(engine.position_key(after))
	game['draw_offer'] = None
	# Clocks start once both sides have made their first move
	if room['tc'] and len(game['moves']) >= 2:
		game['clock_at'] = time.time()


def finish(room: dict, result: str, reason: str):
	'''End the game, store it and apply rating changes.

	:param result: 1-0, 0-1, 1/2-1/2, or * for an aborted game
	'''

	if is_four(room):
		return fourgame.finish(room, result == '*')
	game = room['game']
	if game['clock_at'] is not None and not game['result']:
		turn = game['fen'].split()[1]
		game['clock'][turn] = clock_remaining(game, turn)
	game['clock_at']   = None
	game['result']     = result
	game['reason']     = reason
	game['draw_offer'] = None
	game['ended_at']   = time.time()
	if result == '*':
		return
	w, b = room['players']['w'], room['players']['b']
	game['rating_diff'] = record_game(room['id'], mode(room), w['name'], b['name'], w['user_id'], b['user_id'], result, reason, room['rated'], room['tc'], pgn(room))
	if room.get('bot'):
		human = 'b' if w.get('bot') else 'w'
		if room['players'][human]['user_id']:
			score = {'1-0': 1.0, '0-1': 0.0}.get(result, 0.5)
			record_bot_game(room['players'][human]['user_id'], room['bot'], score if human == 'w' else 1 - score)


def is_four(room: dict) -> bool:
	'''Return whether a room plays 4-player chess.'''

	return MODES[mode(room)]['variant'] is None


def make_move(room: dict, color: str, uci: str) -> str:
	'''Play a move for a color. Returns an error message, or None on success.'''

	if is_four(room):
		return fourgame.make_move(room, color, uci)
	game = room['game']
	if game['result']:
		return 'game is over'
	if not room['players']['w'] or not room['players']['b']:
		return 'waiting for an opponent'
	if check_flag(room):
		return 'out of time'
	pos = position(room)
	if pos.turn != color:
		return 'not your turn'
	if mode(room) == 'recon':
		return recon_move(room, color, pos, uci)
	try:
		move = engine.move_from_uci(uci, pos.variant)
	except ValueError:
		return 'bad move'
	legal = engine.legal_moves(pos)
	if move not in legal:
		return 'illegal move'
	san   = engine.san(pos, move, legal)
	after = engine.apply_move(pos, move)
	end_turn(room, color, after, {'uci': engine.move_to_uci(move, pos.variant), 'san': san})
	ended = engine.status(after, game['keys'])
	if ended:
		finish(room, *ended)
	return None


def mode(room: dict) -> str:
	'''Return a room's game mode.'''

	return room.get('mode', 'classic')


def new_game(room: dict):
	'''Start a fresh game in a room.'''

	if is_four(room):
		return fourgame.new_game(room, *TIME_CONTROLS.get(room['tc'], (0, 0)), MODES[mode(room)]['teams'])
	start        = toggles.start_fen(MODES[mode(room)]['variant'], room.get('toggles', {}))
	minutes, inc = TIME_CONTROLS.get(room['tc'], (0, 0))
	room['game'] = {
		'start_fen'   : start,
		'fen'         : start,
		'moves'       : [],
		'result'      : None,
		'reason'      : None,
		'clock'       : {'w': minutes * 60_000, 'b': minutes * 60_000},
		'increment'   : inc,
		'clock_at'    : None,
		'draw_offer'  : None,
		'rating_diff' : {},
		'ended_at'    : None,
	}
	room['game']['keys'] = [engine.position_key(position(room))]
	if mode(room) == 'recon':
		room['game'].update({'phase': 'sense', 'sense': None, 'ghosts': {'w': {}, 'b': {}}, 'notices': {'w': [], 'b': []}})
	room['rematch'] = []


def new_room(rid: str, tc: str, public: bool, quick: bool, rated: bool, bot: int = None, game_mode: str = 'classic', options: dict = None) -> dict:
	'''Create a room with no players seated.

	:param bot: computer level 1-8 for games against the computer
	:param game_mode: key of MODES
	:param options: toggles, see toggles.py
	'''

	now  = time.time()
	room = {
		'id'            : rid,
		'created_at'    : now,
		'last_activity' : now,
		'mode'          : game_mode if game_mode in MODES else 'classic',
		'tc'            : tc if tc in TIME_CONTROLS else None,
		'public'        : public,
		'quick'         : quick,
		'rated'         : rated,
		'bot'           : bot,
		'toggles'       : options or {},
		'players'       : {},
		'spectators'    : {},
		'chat'          : [],
	}
	room['players'] = {c: None for c in seats(room)}
	new_game(room)
	return room


def notice(game: dict, color: str, text: str):
	'''Add a Reconnaissance Blind notice for one player.'''

	game['notices'][color].append({'ply': len(game['moves']), 'text': text})


def opponent(color: str) -> str:
	'''Return the other color.'''

	return 'b' if color == 'w' else 'w'


def pgn(room: dict) -> str:
	'''Return the game as PGN. Reconnaissance Blind moves are written on the true board, failed moves and passes as --.'''

	game  = room['game']
	w, b  = room['players']['w'], room['players']['b']
	date  = time.strftime('%Y.%m.%d', time.gmtime(room['created_at']))
	tags  = [('Event', f'acidchess {MODES[mode(room)]["name"]} ' + ('rated' if room['rated'] else 'casual')), ('Site', 'acidchess'), ('Date', date), ('White', w['name'] if w else '?'), ('Black', b['name'] if b else '?'), ('Result', game['result'] or '*')]
	if room['tc']:
		minutes, inc = TIME_CONTROLS[room['tc']]
		tags.append(('TimeControl', f'{minutes * 60}+{inc}'))
	if game['reason']:
		tags.append(('Termination', game['reason']))
	text = ''.join(f'[{k} "{v}"]\n' for k, v in tags) + '\n'
	sans = []
	for i, m in enumerate(game['moves']):
		sans.append((f'{i // 2 + 1}. ' if i % 2 == 0 else '') + m['san'])
	return text + ' '.join(sans + [game['result'] or '*']) + '\n'


def position(room: dict) -> engine.Position:
	'''Return the room's current true position.'''

	return engine.Position(room['game']['fen'], variant(room))


def recon_move(room: dict, color: str, pos: engine.Position, uci: str) -> str:
	'''Play a Reconnaissance Blind turn's move phase. Returns an error message, or None on success.'''

	game  = room['game']
	v     = pos.variant
	enemy = opponent(color)
	if game['phase'] != 'move':
		return 'sense first'
	if uci == 'pass':
		move = None
	else:
		try:
			move = engine.move_from_uci(uci, v)
		except ValueError:
			return 'bad move'
		if move not in recon.requested_moves(pos):
			return 'illegal move'
	after, taken, captured = recon.play(pos, move)
	ghosts = game['ghosts'][color]
	if move is None:
		notice(game, color, 'You passed')
	elif taken is None:
		notice(game, color, f'{engine.move_to_uci(move, v)} failed')
	else:
		if taken != move:
			notice(game, color, f'{engine.move_to_uci(move, v)} was stopped at {v.square_name(taken[1])}')
		ghosts.pop(v.square_name(taken[1]), None)
	if captured is not None:
		ghosts.pop(v.square_name(captured), None)
		lost = pos.board[captured].upper()
		notice(game, color, f'You captured a piece on {v.square_name(captured)}')
		notice(game, enemy, f'Your {NAMES[lost]} on {v.square_name(captured)} was captured')
		# The enemy now knows something of ours stands there, without knowing what
		game['ghosts'][enemy][v.square_name(taken[1])] = ['?', len(game['moves'])]
	san = engine.san(pos, taken) if taken else '--'
	end_turn(room, color, after, {'uci': engine.move_to_uci(taken, v) if taken else None, 'requested': uci, 'san': san, 'sense': game['sense'], 'capture': v.square_name(captured) if captured is not None else None})
	game['phase'] = 'sense'
	game['sense'] = None
	ended = recon.status(after)
	if ended:
		finish(room, *ended)
	return None


def recon_sense(room: dict, color: str, square: str) -> str:
	'''Play a Reconnaissance Blind turn's sense phase. Returns an error message, or None on success.

	:param square: centre of the 3x3 window, or None to skip sensing
	'''

	game = room['game']
	if mode(room) != 'recon':
		return 'not a Reconnaissance Blind game'
	if game['result']:
		return 'game is over'
	if not room['players']['w'] or not room['players']['b']:
		return 'waiting for an opponent'
	if check_flag(room):
		return 'out of time'
	pos = position(room)
	if pos.turn != color:
		return 'not your turn'
	if game['phase'] != 'sense':
		return 'already sensed this turn'
	if square is not None:
		v = pos.variant
		try:
			sq = v.square_index(square)
		except ValueError:
			return 'bad square'
		ghosts = game['ghosts'][color]
		white  = color == 'w'
		for s, piece in recon.sense(pos, sq):
			name = v.square_name(s)
			if piece is not None and piece != engine.WALL and piece.isupper() != white:
				ghosts[name] = [piece, len(game['moves'])]
			else:
				ghosts.pop(name, None)
	game['sense'] = square
	game['phase'] = 'move'
	return None


def recon_view(room: dict, color: str) -> dict:
	'''Return the Reconnaissance Blind fields a player or spectator may see.'''

	game = room['game']
	v    = MODES['recon']['variant']
	pos  = position(room)
	if game['result']:
		return {'phase': None, 'sensed': None, 'ghosts': {}, 'notices': game['notices'][color] if color else []}
	if color is None:
		# Spectators trail behind so a player can't use a second tab to see the enemy
		shown = max(0, len(game['moves']) - WATCH_DELAY)
		fen   = game['moves'][shown - 1]['fen'] if shown else v.start_fen
		return {'fen': fen, 'moves': game['moves'][:shown], 'phase': None, 'sensed': None, 'ghosts': {}, 'notices': [], 'turn': fen.split()[1], 'delay': WATCH_DELAY}
	white = color == 'w'
	mine  = pos.copy()
	mine.board = [q if q is not None and (q == engine.WALL or q.isupper() == white) else None for q in pos.board]
	moves = []
	for m in game['moves']:
		if m['color'] == color:
			moves.append({'color': color, 'uci': m['uci'], 'san': m['san'] if m['uci'] else f'{m["requested"]} ✗' if m['requested'] != 'pass' else 'pass'})
		else:
			moves.append({'color': m['color'], 'uci': None, 'san': f'?x{m["capture"]}' if m['capture'] else '?'})
	sensed = None
	if pos.turn == color and game['sense']:
		sensed = [v.square_name(s) for s, _ in recon.sense(pos, v.square_index(game['sense']))]
	ply = len(game['moves'])
	return {
		'fen'     : engine.fen(mine),
		'moves'   : moves,
		'phase'   : game['phase'] if pos.turn == color else None,
		'sensed'  : sensed,
		'ghosts'  : {sq: {'piece': piece, 'age': (ply - seen) // 2} for sq, (piece, seen) in game['ghosts'][color].items()},
		'notices' : game['notices'][color][-30:],
		'legal'   : [engine.move_to_uci(m, v) for m in recon.requested_moves(pos)] + ['pass'] if pos.turn == color and game['phase'] == 'move' else [],
	}


def seat(room: dict, color: str, token: str, name: str, user_id: int, bot: int = None):
	'''Seat a player in a room. Computer players have a level and no token.'''

	room['players'][color] = {'token': token, 'name': name, 'user_id': user_id, 'rating': rating_of(user_id, mode(room)) if user_id else None, 'bot': bot}


def seats(room: dict) -> tuple:
	'''Return the colors that sit at a room's board.'''

	return four.COLORS if is_four(room) else COLORS


def state(room: dict, token: str) -> dict:
	'''Return the room as the given player or spectator should see it.'''

	game  = room['game']
	color = next((c for c in seats(room) if token and room['players'][c] and room['players'][c]['token'] == token), None)
	if is_four(room):
		return state_four(room, color)
	pos   = position(room)
	legal = []
	ready = room['players']['w'] and room['players']['b'] and not game['result']
	if color == pos.turn and ready and mode(room) != 'recon':
		legal = [engine.move_to_uci(m, pos.variant) for m in engine.legal_moves(pos)]
	players = {}
	for c in COLORS:
		p = room['players'][c]
		players[c] = {'name': p['name'], 'rating': p['rating'], 'registered': bool(p['user_id']), 'bot': p.get('bot')} if p else None
	out = {
		'id'           : room['id'],
		'mode'         : mode(room),
		'mode_name'    : MODES[mode(room)]['name'],
		'width'        : pos.variant.width,
		'height'       : pos.variant.height,
		'start_fen'    : game.get('start_fen', pos.variant.start_fen),
		'values'       : {k: p['value'] for k, p in pos.variant.pieces.items()},
		'hand'         : pos.hand if pos.variant.drops else None,
		'checks'       : {'w': pos.checks[0], 'b': pos.checks[1], 'limit': pos.variant.check_limit} if pos.variant.check_limit else None,
		'hill'         : [pos.variant.square_name(sq) for sq in sorted(pos.variant.hill)],
		'stars'        : [pos.variant.square_name(sq) for sq in sorted(pos.stars)],
		'tc'           : room['tc'],
		'public'       : room['public'],
		'rated'        : room['rated'],
		'bot'          : room.get('bot'),
		'toggles'      : room.get('toggles', {}),
		'color'        : color,
		'spectator'    : color is None,
		'players'      : players,
		'fen'          : game['fen'],
		'turn'         : pos.turn,
		'check'        : engine.in_check(pos) if not pos.variant.king_capture else False,
		'moves'        : game['moves'],
		'legal'        : legal,
		'result'       : game['result'],
		'reason'       : game['reason'],
		'clock'        : {c: clock_remaining(game, c) for c in COLORS} if room['tc'] else None,
		'clock_running': game['clock_at'] is not None,
		'draw_offer'   : game['draw_offer'],
		'rating_diff'  : game['rating_diff'],
		'rematch'      : room['rematch'],
		'chat'         : room['chat'][-CHAT_MAX:],
		'spectators'   : len(room['spectators']),
		'pgn'          : pgn(room) if game['result'] or mode(room) != 'recon' else None,
	}
	if mode(room) == 'recon':
		out.update(recon_view(room, color))
	return out


def state_four(room: dict, color: str) -> dict:
	'''Return a 4-player room as a player or spectator sees it.'''

	game = room['game']
	out  = {
		'id'          : room['id'],
		'mode'        : mode(room),
		'mode_name'   : MODES[mode(room)]['name'],
		'tc'          : room['tc'],
		'public'      : room['public'],
		'rated'       : room['rated'],
		'bot'         : None,
		'toggles'     : {},
		'color'       : color,
		'spectator'   : color is None,
		'players'     : {c: {'name': p['name'], 'rating': p['rating'], 'registered': bool(p['user_id']), 'bot': None} if p else None for c, p in room['players'].items()},
		'result'      : game['result'],
		'reason'      : game['reason'],
		'draw_offer'  : None,
		'rating_diff' : game['rating_diff'],
		'rematch'     : room['rematch'],
		'chat'        : room['chat'][-CHAT_MAX:],
		'spectators'  : len(room['spectators']),
		'pgn'         : None,
	}
	out.update(fourgame.view(room, color))
	return out


def variant(room: dict) -> engine.Variant:
	'''Return the rules for a room's game. Toggles that change the start position get their own variant, since castling and promotion come from it.'''

	base  = MODES[mode(room)]['variant']
	start = room['game'].get('start_fen', base.start_fen)
	opts  = room.get('toggles', {})
	rules = tuple(name for name in toggles.RULES if opts.get(name))
	if start == base.start_fen and not rules:
		return base
	key = (mode(room), start, rules)
	if key not in VARIANTS:
		if len(VARIANTS) >= VARIANTS_MAX:
			VARIANTS.clear()
		VARIANTS[key] = engine.Variant(base.name, base.width, base.height, start, engine.ALL_PIECES, None, True, base.king_capture, base.pawn_rank, 'koth' in rules, 3 if 'threecheck' in rules else 0, 'atomic' in rules, 'drops' in rules, toggles.UPGRADES if 'bonus' in rules else None)
	return VARIANTS[key]
