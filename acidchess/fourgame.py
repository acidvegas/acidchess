#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/fourgame.py

import time

import four
from storage import record_four


CLOCK_START = 4 # clocks start once every player has made a move


def advance_clock(game: dict, color: str):
	'''Charge the time used by the player who just moved and start the next player's clock.'''

	if game['clock_at'] is not None:
		game['clock'][color] = remaining(game, color) + game['increment'] * 1000
	if game['tc'] and len(game['moves']) >= CLOCK_START:
		game['clock_at'] = time.time()


def check_flag(room: dict) -> bool:
	'''Knock out the player to move if their clock ran out. Returns True if anything changed.'''

	game  = room['game']
	state = game['state']
	if game['result'] or game['clock_at'] is None:
		return False
	color = state['turn']
	if remaining(game, color) > 0:
		return False
	game['clock'][color] = 0
	four.eliminate(state, color, 'timeout')
	knocked = [(color, 'timeout')] + four.advance(state)
	note_out(game, knocked)
	game['clock_at'] = time.time()
	if four.finished(state):
		finish(room)
	return True


def finish(room: dict, aborted: bool = False):
	'''End the game and record it. An aborted game is not recorded.'''

	game  = room['game']
	state = game['state']
	if game['clock_at'] is not None and not aborted:
		game['clock'][state['turn']] = remaining(game, state['turn'])
	game['clock_at'] = None
	game['ended_at'] = time.time()
	if aborted:
		game['result'], game['reason'] = '*', 'aborted'
		return
	result = four.finished(state)
	game['result']  = ''.join(result['winners'])
	game['reason']  = result['reason']
	game['places']  = four.placements(state)
	players = room['players']
	game['rating_diff'] = record_four(room['id'], room['mode'], {c: players[c]['name'] for c in four.COLORS}, {c: players[c]['user_id'] for c in four.COLORS}, game['places'], game['result'], game['reason'], room['rated'], room['tc'])


def make_move(room: dict, color: str, uci: str) -> str:
	'''Play a move for a color. Returns an error message, or None on success.'''

	game  = room['game']
	state = game['state']
	if game['result']:
		return 'game is over'
	if any(room['players'][c] is None for c in four.COLORS):
		return 'waiting for players'
	if check_flag(room):
		return 'out of time'
	if state['turn'] != color:
		return 'not your turn'
	try:
		move = four.move_from_uci(uci)
	except ValueError:
		return 'bad move'
	if move not in four.legal_moves(state, color):
		return 'illegal move'
	san     = four.san(state['board'], move)
	knocked = four.play(state, move)
	game['moves'].append({'color': color, 'uci': four.move_to_uci(move), 'san': san + ('+' if any(four.in_check(state, c) for c in state['alive'] if c != color) else '')})
	note_out(game, knocked)
	advance_clock(game, color)
	if four.finished(state):
		finish(room)
	return None


def new_game(room: dict, minutes: int, inc: int, teams: bool):
	'''Start a fresh 4-player game in a room.'''

	room['game'] = {
		'state'       : four.new_state(teams),
		'moves'       : [],
		'events'      : [],
		'result'      : None,
		'reason'      : None,
		'places'      : None,
		'tc'          : bool(minutes),
		'clock'       : {c: minutes * 60_000 for c in four.COLORS},
		'increment'   : inc,
		'clock_at'    : None,
		'draw_offer'  : None,
		'rating_diff' : {},
		'ended_at'    : None,
	}
	room['rematch'] = []


def note_out(game: dict, knocked: list):
	'''Log players who were knocked out, for the move list.'''

	for color, why in knocked:
		game['events'].append({'ply': len(game['moves']), 'text': f'{four.NAMES[color]} is out ({why})'})


def remaining(game: dict, color: str) -> int:
	'''Return a player's clock in milliseconds, counting the running turn.'''

	ms = game['clock'][color]
	if game['clock_at'] is not None and game['state']['turn'] == color and not game['result']:
		ms -= int((time.time() - game['clock_at']) * 1000)
	return max(0, ms)


def resign(room: dict, color: str) -> str:
	'''Resign: the player is out, their army freezes. Returns an error message, or None.'''

	game  = room['game']
	state = game['state']
	if game['result'] or color not in state['alive']:
		return 'nothing to resign'
	was_turn = state['turn'] == color
	if was_turn and game['clock_at'] is not None:
		game['clock'][color] = remaining(game, color)
		game['clock_at'] = time.time()
	four.eliminate(state, color, 'resignation')
	knocked = [(color, 'resignation')] + (four.advance(state) if was_turn else [])
	note_out(game, knocked)
	if four.finished(state):
		finish(room)
	return None


def view(room: dict, color: str) -> dict:
	'''Return the 4-player fields of the room state.'''

	game = room['game']
	st   = game['state']
	live = not game['result'] and all(room['players'][c] for c in four.COLORS)
	return {
		'width'         : four.SIZE,
		'height'        : four.SIZE,
		'colors'        : list(four.COLORS),
		'teams'         : st['teams'],
		'board4'        : st['board'],
		'valid'         : four.VALID,
		'turn'          : st['turn'],
		'alive'         : st['alive'],
		'out'           : st['out'],
		'check'         : four.in_check(st, st['turn']) if live else False,
		'legal'         : [four.move_to_uci(m) for m in four.legal_moves(st, color)] if live and color == st['turn'] else [],
		'moves'         : game['moves'],
		'events'        : game['events'],
		'places'        : game['places'],
		'clock'         : {c: remaining(game, c) for c in four.COLORS} if game['tc'] else None,
		'clock_running' : game['clock_at'] is not None,
	}
