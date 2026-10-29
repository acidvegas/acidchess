#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# tests/test_variants.py

import os
import random
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'acidchess'))

import ai
import engine
import game
import toggles
from engine import ALL_PIECES, DIAG, KNIGHT, ORTHO, PIECES


GAMES = int(os.environ.get('VARIANT_GAMES', 5)) # random games per variant
ARCHBISHOP = {'value': 7, 'moves': ((DIAG, True, 'mc'), (KNIGHT, False, 'mc'))}
CHANCELLOR = {'value': 8, 'moves': ((ORTHO, True, 'mc'), (KNIGHT, False, 'mc'))}

# The fairy pieces in Fairy-Stockfish's Betza notation
FAIRY_INI = 'customPiece1 = m:QN\ncustomPiece2 = o:mRcpR\ncustomPiece3 = g:gRgB\ncustomPiece4 = h:NN\ncustomPiece5 = l:C\n'

# Atomic rules on top of another variant, the same way Fairy-Stockfish builds its own atomic
ATOMIC_INI = 'king = -\ncommoner = k\ncastlingKingPiece = k\nextinctionValue = loss\nextinctionPieceTypes = k\nextinctionPseudoRoyal = true\nblastOnCapture = true\n'

# Our variant definition alongside the same rules written for Fairy-Stockfish
VARIANTS = [
	(
		engine.Variant('holes', start_fen='rnbqkbnr/pppppppp/8/2*4*/*4*2/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'),
		'[holes:chess]\nstartFen = rnbqkbnr/pppppppp/8/2*4*/*4*2/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1\n',
	),
	(
		engine.Variant('wide', width=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces={**PIECES, 'A': ARCHBISHOP, 'C': CHANCELLOR}, promotion=('Q', 'C', 'A', 'R', 'B', 'N')),
		'',  # Fairy-Stockfish's built-in capablanca
	),
	(
		engine.Variant('big', width=10, height=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces={**PIECES, 'A': ARCHBISHOP, 'C': CHANCELLOR}, promotion=('Q', 'C', 'A', 'R', 'B', 'N')),
		'[big:capablanca]\nmaxRank = 10\nstartFen = rnabqkbcnr/pppppppppp/10/10/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1\npromotionRegionWhite = *10\npromotionRegionBlack = *1\ndoubleStepRegionWhite = *2\ndoubleStepRegionBlack = *9\n',
	),
	(
		engine.Variant('oddpieces', start_fen='rnbxkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBXKBNR w KQkq - 0 1', pieces={**PIECES, 'X': {'value': 6, 'moves': ((ORTHO, True, 'm'), (DIAG, True, 'c'))}}, promotion=('X', 'R', 'B', 'N')),
		'[oddpieces:chess]\ncustomPiece1 = x:mRcB\nstartFen = rnbxkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBXKBNR w KQkq - 0 1\npromotionPieceTypes = xrbn\n',
	),
	(
		engine.Variant('fairymix', start_fen='ohgmklgo/pppppppp/8/8/8/8/PPPPPPPP/OHGMKLGO w - - 0 1', pieces=ALL_PIECES),
		'[fairymix:chess]\n' + FAIRY_INI + 'startFen = ohgmklgo/pppppppp/8/8/8/8/PPPPPPPP/OHGMKLGO w - - 0 1\npromotionPieceTypes = mhogl\n',
	),
	(
		engine.Variant('fairyholes', start_fen='ohgmklgo/pppppppp/8/1*4*1/2*2*2/8/PPPPPPPP/OHGMKLGO w - - 0 1', pieces=ALL_PIECES),
		'[fairyholes:chess]\n' + FAIRY_INI + 'startFen = ohgmklgo/pppppppp/8/1*4*1/2*2*2/8/PPPPPPPP/OHGMKLGO w - - 0 1\npromotionPieceTypes = mhogl\n',
	),
	(
		engine.Variant('big8', width=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces=ALL_PIECES),
		'[big8:capablanca]\n',
	),
	(
		engine.Variant('big10', width=10, height=10, start_fen='rnabqkbcnr/olhg2ghlo/pppppppppp/10/10/10/10/PPPPPPPPPP/OLHG2GHLO/RNABQKBCNR w KQkq - 0 1', pieces=ALL_PIECES, pawn_rank=2),
		'[big10:capablanca]\n' + FAIRY_INI + 'maxRank = 10\nstartFen = rnabqkbcnr/olhg2ghlo/pppppppppp/10/10/10/10/PPPPPPPPPP/OLHG2GHLO/RNABQKBCNR w KQkq - 0 1\npromotionRegionWhite = *10\npromotionRegionBlack = *1\ndoubleStepRegionWhite = *3\ndoubleStepRegionBlack = *8\npromotionPieceTypes = qcarholbng\n',
	),
	(
		engine.Variant('koth', koth=True),
		'[koth:kingofthehill]\n',
	),
	(
		engine.Variant('threecheck', check_limit=3),
		'[threecheck:3check]\n',
	),
	(
		engine.Variant('bigkoth', width=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces=ALL_PIECES, koth=True),
		'[bigkoth:capablanca]\nflagPiece = k\nflagRegionWhite = e4 f4 e5 f5\nflagRegionBlack = e4 f4 e5 f5\n',
	),
	(
		engine.Variant('atomicchess', atomic=True),
		'[atomicchess:atomic]\n',
	),
	(
		engine.Variant('bigatomic', width=10, start_fen='rnabqkbcnr/pppppppppp/10/10/10/10/PPPPPPPPPP/RNABQKBCNR w KQkq - 0 1', pieces=ALL_PIECES, atomic=True),
		'[bigatomic:capablanca]\n' + ATOMIC_INI,
	),
	(
		engine.Variant('kingcapture', king_capture=True),
		'[kingcapture:chess]\nking = -\ncommoner = k\ncastlingKingPiece = k\nextinctionValue = loss\nextinctionPieceTypes = k\nstalemateValue = loss\n',
	),
]


class Fairy:
	'''A Fairy-Stockfish process used to list legal moves.'''

	def __init__(self, ini: str):
		'''Start the engine with extra variant definitions.'''

		self.ini = tempfile.NamedTemporaryFile('w', suffix='.ini', delete=False)
		self.ini.write(ini)
		self.ini.close()
		self.proc = subprocess.Popen([ai.ENGINE_PATH], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
		self.send(f'setoption name VariantPath value {self.ini.name}')


	def close(self):
		'''Stop the engine.'''

		self.send('quit')
		self.proc.wait()
		self.proc.stdin.close()
		self.proc.stdout.close()
		os.unlink(self.ini.name)


	def moves(self, variant: str, fen: str) -> set:
		'''Return the UCI moves Fairy-Stockfish allows in a position.'''

		self.send(f'setoption name UCI_Variant value {variant}')
		self.send(f'position fen {fen}')
		self.send('go perft 1')
		out = set()
		for line in self.proc.stdout:
			if line.startswith('Nodes searched'):
				return out
			if ': ' in line:
				out.add(line.split(':')[0].strip())
		raise EOFError('engine exited')


	def send(self, command: str):
		'''Send a UCI command.'''

		self.proc.stdin.write(command + '\n')
		self.proc.stdin.flush()


def toggled_variants(count: int) -> list:
	'''Build random toggled start positions for every board mode, each with a matching Fairy-Stockfish section.'''

	rng     = random.Random(2)
	parents = {'classic': 'chess', 'big8': 'capablanca', 'big10': 'capablanca'}
	extra   = {'classic': 'archbishop = a\nchancellor = c\n', 'big8': '', 'big10': 'maxRank = 10\npromotionRegionWhite = *10\npromotionRegionBlack = *1\ndoubleStepRegionWhite = *3\ndoubleStepRegionBlack = *8\n'}
	out     = []
	for i in range(count):
		mode    = list(parents)[i % 3]
		options = toggles.clean({'holes': rng.random() < 0.5, 'armies': rng.random() < 0.5, 'swaps': rng.sample(list(toggles.SWAPS), rng.randint(0, 2)), **{rule: rng.random() < 0.35 for rule in toggles.RULES}})
		base    = game.MODES[mode]['variant']
		start   = toggles.start_fen(base, options, rng)
		ours    = game.variant({'mode': mode, 'toggles': options, 'game': {'start_fen': start}})
		rules   = ''
		if options.get('koth'):
			hill   = ' '.join(ours.square_name(sq) for sq in sorted(ours.hill))
			rules += f'flagPiece = k\nflagRegionWhite = {hill}\nflagRegionBlack = {hill}\n'
		if options.get('threecheck'):
			rules += 'checkCounting = true\n'
		if options.get('atomic'):
			rules += ATOMIC_INI
		if options.get('drops'):
			rules += 'pieceDrops = true\ncapturesToHand = true\n'
		ini = f'[tg{i}:{parents[mode]}]\n' + FAIRY_INI + extra[mode] + rules + f'startFen = {start}\npromotionPieceTypes = {"".join(ours.promotion).lower()}\n'
		out.append((ours, ini, f'tg{i}'))
	return out


@unittest.skipUnless(ai.available(), 'engine binary not installed')
class TestVariants(unittest.TestCase):
	'''Our move generation matches Fairy-Stockfish move for move across random games in every variant.'''

	@classmethod
	def setUpClass(cls):
		'''Start one engine with every test variant loaded.'''

		cls.toggled = toggled_variants(GAMES * 3)
		cls.fairy   = Fairy('\n'.join([ini for _, ini in VARIANTS if ini] + [ini for _, ini, _ in cls.toggled]))


	@classmethod
	def tearDownClass(cls):
		'''Stop the engine.'''

		cls.fairy.close()


	def compare(self, variant: engine.Variant, fsf_name: str, games: int, rng: random.Random) -> int:
		'''Play random games in a variant, comparing legal moves with Fairy-Stockfish at every position. Returns positions checked.'''

		checked = 0
		for _ in range(games):
			pos  = engine.Position(variant=variant)
			keys = [engine.position_key(pos)]
			for _ in range(200):
				# Once a win condition other than mate is met the game is over and the engines may disagree about what follows
				ended = engine.status(pos, keys)
				if ended and ended[1] in ('king of the hill', 'three-check', 'king captured', 'explosion'):
					break
				ours   = {engine.move_to_uci(m, variant) for m in engine.legal_moves(pos)}
				theirs = self.fairy.moves(fsf_name, engine.fen(pos))
				if variant.king_capture and engine.winner(pos):
					theirs = set()
					ours   = set()
				self.assertEqual(ours, theirs, f'{variant.name} {engine.fen(pos)}: only ours {sorted(ours - theirs)}, only theirs {sorted(theirs - ours)}')
				checked += 1
				if not ours or engine.status(pos, keys):
					break
				pos = engine.apply_move(pos, engine.move_from_uci(rng.choice(sorted(ours)), variant))
				keys.append(engine.position_key(pos))
		return checked


	def test_toggles(self):
		'''Random stacks of toggles *(holes, random armies, swaps, king of the hill, three-check, explosive captures, drops)* on every board.'''

		rng = random.Random(3)
		checked = sum(self.compare(variant, name, 1, rng) for variant, _, name in self.toggled)
		print(f'toggled starts: {len(self.toggled)} layouts, {checked} positions match')


	def test_variants(self):
		'''Walk random games and compare the legal move list at every position.'''

		rng = random.Random(1)
		for variant, ini in VARIANTS:
			fsf_name = ini.split(':')[0][1:] if ini else 'capablanca'
			checked  = self.compare(variant, fsf_name, GAMES, rng)
			print(f'{variant.name}: {checked} positions match')



if __name__ == '__main__':
	unittest.main()
