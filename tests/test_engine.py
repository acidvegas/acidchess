#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# tests/test_engine.py

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'acidchess'))

import engine


# Reference counts from https://www.chessprogramming.org/Perft_Results
PERFT = [
	(engine.START_FEN,                                                            [20, 400, 8902, 197_281]),
	('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1',      [48, 2039, 97_862, 4_085_603]),
	('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1',                                 [14, 191, 2812, 43_238, 674_624]),
	('r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1',          [6, 264, 9467, 422_333]),
	('r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1',          [6, 264, 9467, 422_333]),
	('rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8',                 [44, 1486, 62_379, 2_103_487]),
	('r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10',  [46, 2079, 89_890, 3_894_594]),
]


class TestEngine(unittest.TestCase):
	'''Rules engine tests.'''

	def play(self, *moves: str) -> tuple:
		'''Play UCI moves from the start position, returning the position and repetition keys.'''

		pos  = engine.Position()
		keys = [engine.position_key(pos)]
		for text in moves:
			move = engine.move_from_uci(text)
			self.assertIn(move, engine.legal_moves(pos), text)
			pos = engine.apply_move(pos, move)
			keys.append(engine.position_key(pos))
		return pos, keys


	def test_bonus_squares(self):
		'''A knight landing on a star becomes an archbishop and uses the star up.'''

		v   = engine.Variant('bonus', pieces=engine.ALL_PIECES, upgrades={'N': 'A', 'B': 'A', 'R': 'C', 'Q': 'M'})
		pos = engine.Position('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 {f3,c6}', v)
		self.assertEqual(engine.san(pos, engine.move_from_uci('g1f3', v)), 'Nf3=A')
		pos = engine.apply_move(pos, engine.move_from_uci('g1f3', v))
		self.assertEqual(engine.fen(pos), 'rnbqkbnr/pppppppp/8/8/8/5A2/PPPPPPPP/RNBQKB1R b KQkq - 1 1 {c6}')
		pos = engine.apply_move(pos, engine.move_from_uci('c7c6', v))
		self.assertEqual((pos.board[engine.CLASSIC.square_index('c6')], pos.stars), ('p', set()))


	def test_castling_through_check(self):
		'''Castling is refused through an attacked square but allowed when only the rook passes one.'''

		pos = engine.Position('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
		self.assertIn(engine.move_from_uci('e1g1'), engine.legal_moves(pos))
		pos = engine.Position('r3k2r/8/8/8/8/8/8/R3K1qR w KQkq - 0 1')
		self.assertNotIn(engine.move_from_uci('e1g1'), engine.legal_moves(pos))
		pos = engine.Position('1r2k3/8/8/8/8/8/8/R3K3 w Q - 0 1')
		self.assertIn(engine.move_from_uci('e1c1'), engine.legal_moves(pos))


	def test_en_passant_pin(self):
		'''En passant is illegal when it exposes the king along the rank.'''

		pos = engine.Position('8/8/8/K2pP2r/8/8/8/7k w - d6 0 1')
		self.assertNotIn(engine.move_from_uci('e5d6'), engine.legal_moves(pos))


	def test_fools_mate(self):
		'''Fastest checkmate ends the game.'''

		pos, keys = self.play('f2f3', 'e7e5', 'g2g4', 'd8h4')
		self.assertEqual(engine.status(pos, keys), ('0-1', 'checkmate'))


	def test_perft(self):
		'''Move generation matches the reference node counts.'''

		depth = int(os.environ.get('PERFT_DEPTH', 3))
		for fen, counts in PERFT:
			pos = engine.Position(fen)
			for d, expected in enumerate(counts[:depth], 1):
				self.assertEqual(engine.perft(pos, d), expected, f'{fen} depth {d}')


	def test_repetition(self):
		'''Shuffling knights back and forth draws on the third occurrence.'''

		pos, keys = self.play('g1f3', 'g8f6', 'f3g1', 'f6g8', 'g1f3', 'g8f6', 'f3g1', 'f6g8')
		self.assertEqual(engine.status(pos, keys), ('1/2-1/2', 'threefold repetition'))


	def test_san(self):
		'''SAN covers disambiguation, promotion and mate.'''

		pos = engine.Position('4k3/1P6/8/8/8/8/8/R3K2R w KQ - 0 1')
		self.assertEqual(engine.san(pos, engine.move_from_uci('b7b8n')), 'b8=N')
		self.assertEqual(engine.san(pos, engine.move_from_uci('e1c1')), 'O-O-O')
		pos = engine.Position('6k1/5ppp/8/8/8/8/8/R4RK1 w - - 0 1')
		self.assertEqual(engine.san(pos, engine.move_from_uci('a1d1')), 'Rad1')
		self.assertEqual(engine.san(pos, engine.move_from_uci('a1a8')), 'Ra8#')


	def test_stalemate(self):
		'''No legal moves and not in check is a draw.'''

		pos = engine.Position('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')
		self.assertEqual(engine.status(pos, [engine.position_key(pos)]), ('1/2-1/2', 'stalemate'))



if __name__ == '__main__':
	unittest.main()
