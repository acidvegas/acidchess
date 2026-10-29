#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# tests/test_four.py

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'acidchess'))

import four
from four import SIZE


NEXT = {'r': 'b', 'b': 'y', 'y': 'g', 'g': 'r'}


def rotate(sq: int) -> int:
	'''Turn a square a quarter turn so red's side lands on blue's.'''

	f, r = sq % SIZE, sq // SIZE
	return (SIZE - 1 - f) * SIZE + r


def rotate_state(state: dict) -> dict:
	'''Rotate a whole game a quarter turn, handing each army to the next color clockwise.'''

	board = [None] * (SIZE * SIZE)
	for sq, q in enumerate(state['board']):
		if q:
			board[rotate(sq)] = NEXT[q[0]] + q[1]
	return {
		'board'  : board,
		'turn'   : NEXT[state['turn']],
		'alive'  : [NEXT[c] for c in state['alive']],
		'out'    : [[NEXT[c], why] for c, why in state['out']],
		'rights' : {NEXT[c]: [rotate(sq) for sq in sqs] for c, sqs in state['rights'].items()},
		'teams'  : state['teams'],
	}


class TestFour(unittest.TestCase):
	'''4-player rules.'''

	def random_states(self, games: int, teams: bool, seed: int):
		'''Yield (state, color to move) from random games.'''

		rng = random.Random(seed)
		for _ in range(games):
			state = four.new_state(teams)
			for _ in range(300):
				if four.finished(state):
					break
				yield state
				moves = four.legal_moves(state, state['turn'])
				four.play(state, rng.choice(moves))


	def test_board(self):
		'''160 playable squares, 64 pieces, 20 opening moves for every color.'''

		state = four.new_state(False)
		self.assertEqual(sum(four.VALID), 160)
		self.assertEqual(sum(1 for q in state['board'] if q), 64)
		for c in four.COLORS:
			self.assertEqual(len(four.legal_moves(state, c)), 20, c)


	def test_castling(self):
		'''Red castles both ways once the squares are clear, never through an attacked square.'''

		state = four.new_state(False)
		b = state['board']
		for sq in ('e1', 'f1', 'g1', 'i1', 'j1'):
			b[four.square_index(sq)] = None
		moves = {four.move_to_uci(m) for m in four.legal_moves(state, 'r')}
		self.assertTrue({'h1j1', 'h1f1'} <= moves)
		after = four.apply_move(b, four.move_from_uci('h1j1'))
		self.assertEqual((after[four.square_index('j1')], after[four.square_index('i1')], after[four.square_index('k1')]), ('rK', 'rR', None))
		b[four.square_index('i5')] = 'yR'
		b[four.square_index('i2')] = None
		moves = {four.move_to_uci(m) for m in four.legal_moves(state, 'r')}
		self.assertNotIn('h1j1', moves)
		self.assertIn('h1f1', moves)


	def test_king_safety(self):
		'''No legal move leaves your own king attacked by a live enemy.'''

		checked = 0
		for state in self.random_states(15, False, 1):
			c = state['turn']
			for move in four.legal_moves(state, c):
				after = dict(state, board=four.apply_move(state['board'], move))
				self.assertFalse(four.in_check(after, c), four.move_to_uci(move))
				checked += 1
		self.assertGreater(checked, 1000)


	def test_rotation(self):
		'''Turning the board a quarter turn and passing each army on gives exactly the same moves.'''

		positions = 0
		for teams in (False, True):
			for state in self.random_states(12, teams, 2 + teams):
				c = state['turn']
				ours = {(rotate(m[0]), rotate(m[1]), m[2]) for m in four.legal_moves(state, c)}
				turned = rotate_state(state)
				self.assertEqual(ours, set(four.legal_moves(turned, NEXT[c])))
				self.assertEqual(four.in_check(state, c), four.in_check(turned, NEXT[c]))
				positions += 1
		self.assertGreater(positions, 1000)


	def test_teams(self):
		'''Partners can't capture each other, and the first player out loses it for their team.'''

		state = four.new_state(True)
		b = state['board']
		b[four.square_index('h2')] = None
		b[four.square_index('g3')] = 'rB'
		b[four.square_index('i5')] = 'yN'
		b[four.square_index('e5')] = 'bN'
		moves = {four.move_to_uci(m) for m in four.legal_moves(state, 'r')}
		self.assertIn('g3h4', moves)
		self.assertNotIn('g3i5', moves)
		self.assertIn('g3e5', moves)
		four.eliminate(state, 'b', 'checkmate')
		self.assertEqual(four.finished(state), {'winners': ['r', 'y'], 'reason': 'checkmate'})



if __name__ == '__main__':
	unittest.main()
