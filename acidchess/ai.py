#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/ai.py

import atexit
import os
import subprocess
import threading


ENGINE_PATH = os.environ.get('ACIDCHESS_ENGINE', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines', 'fairy-stockfish'))
TIMEOUT     = 10 # seconds before a stuck engine is killed
POOL_MAX    = 4  # idle engines kept running for reuse
POOL        = []
POOL_LOCK   = threading.Lock()

# Level -> (Skill Level, depth, movetime ms), the same table lichess uses for its 8 computer levels
LEVELS = {
	1 : (-9, 5,  50),
	2 : (-5, 5,  100),
	3 : (-1, 5,  150),
	4 : (3,  5,  200),
	5 : (7,  5,  300),
	6 : (11, 8,  400),
	7 : (16, 13, 500),
	8 : (20, 22, 1000),
}


class Engine:
	'''A running Fairy-Stockfish process. Starting one takes ~0.3s, so they are kept and reused.'''

	def __init__(self):
		'''Start the engine and wait for it to be ready.'''

		self.proc = subprocess.Popen([ENGINE_PATH], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
		self.send('uci')
		self.until('uciok')
		self.send('setoption name Threads value 1')
		self.send('setoption name Hash value 16')


	def close(self):
		'''Stop the engine process.'''

		try:
			self.send('quit')
		except OSError:
			pass
		try:
			self.proc.wait(timeout=1)
		except subprocess.TimeoutExpired:
			self.proc.kill()
			self.proc.wait()
		for pipe in (self.proc.stdin, self.proc.stdout):
			try:
				pipe.close()
			except OSError:
				pass


	def send(self, command: str):
		'''Send a UCI command.'''

		self.proc.stdin.write(command + '\n')
		self.proc.stdin.flush()


	def until(self, prefix: str) -> str:
		'''Read output until a line starts with prefix. Raises EOFError if the engine exits.'''

		for line in self.proc.stdout:
			if line.startswith(prefix):
				return line
		raise EOFError('engine exited')


def available() -> bool:
	'''Return whether the engine binary is installed.'''

	return os.access(ENGINE_PATH, os.X_OK)


def best_move(start_fen: str, moves: list, level: int) -> str:
	'''Ask the engine for a move. Returns a UCI move string, or None if the engine failed.

	:param start_fen: FEN the game started from
	:param moves: UCI moves played since
	:param level: computer level 1-8
	'''

	skill, depth, movetime = LEVELS[level]
	eng = None
	try:
		with POOL_LOCK:
			eng = POOL.pop() if POOL else None
		if eng is None:
			eng = Engine()
		# Kill the process if it hangs, which makes the reads below fail instead of blocking forever
		watchdog = threading.Timer(TIMEOUT, eng.proc.kill)
		watchdog.start()
		try:
			eng.send('ucinewgame')
			eng.send(f'setoption name Skill Level value {skill}')
			eng.send('isready')
			eng.until('readyok')
			eng.send(f'position fen {start_fen}' + (' moves ' + ' '.join(moves) if moves else ''))
			eng.send(f'go depth {depth} movetime {movetime}')
			move = eng.until('bestmove').split()[1]
		finally:
			watchdog.cancel()
	except (OSError, EOFError, IndexError, ValueError) as e:
		print(f'engine error: {e}')
		if eng:
			eng.close()
		return None
	with POOL_LOCK:
		if len(POOL) < POOL_MAX:
			POOL.append(eng)
			eng = None
	if eng:
		eng.close()
	return None if move in ('(none)', '0000') else move


def close_pool():
	'''Stop every idle engine.'''

	with POOL_LOCK:
		while POOL:
			POOL.pop().close()


atexit.register(close_pool)
