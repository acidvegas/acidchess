#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# tests/test_app.py

import os
import queue
import sys
import tempfile
import time
import unittest

os.environ['ACIDCHESS_DATA_DIR'] = tempfile.mkdtemp(prefix='acidchess_test_')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'acidchess'))

import ai
import app as server
import auth
import storage


SCHOLARS_MATE = ['e2e4', 'e7e5', 'f1c4', 'b8c6', 'd1h5', 'g8f6', 'h5f7']


class TestApp(unittest.TestCase):
	'''HTTP API tests against an in-process app with a throwaway database.'''

	def setUp(self):
		'''Create a test client.'''

		self.client = server.app.test_client()


	def call(self, path: str, body: dict = None, auth_token: str = '', player_token: str = '') -> dict:
		'''Make a GET or POST request and return the JSON reply.'''

		headers = {'X-Auth-Token': auth_token, 'X-Player-Token': player_token}
		if body is None:
			return self.client.get(path, headers=headers).get_json()
		return self.client.post(path, json=body, headers=headers).get_json()


	def listen(self, rid: str):
		'''Pretend a browser has the room's event stream open, which is what makes it count as open.'''

		server.SUBSCRIBERS.setdefault(rid, []).append(queue.Queue())


	def play(self, rid: str, tokens: dict, moves: list) -> dict:
		'''Play moves alternating white and black.'''

		data = None
		for i, uci in enumerate(moves):
			color = 'w' if i % 2 == 0 else 'b'
			data  = self.call('/move', {'room_id': rid, 'player_token': tokens[color], 'uci': uci})
			self.assertNotIn('error', data, uci)
		return data


	def wait(self, rid: str, token: str, check, timeout: float = 10) -> dict:
		'''Poll a room until check(state) is true.'''

		end = time.time() + timeout
		while time.time() < end:
			s = self.call(f'/state?room_id={rid}', player_token=token)
			if check(s):
				return s
			time.sleep(0.05)
		self.fail(f'timed out waiting on room {rid}')


	def signup(self, username: str) -> str:
		'''Create an account and return its auth token.'''

		cap = self.call('/auth/captcha')
		self.assertEqual(self.call('/auth/signup', {'username': username, 'password': 'hunter22x', 'captcha_id': cap['captcha_id'], 'captcha': 'WRONG'})['error'], 'wrong captcha')
		cap  = self.call('/auth/captcha')
		text = auth.CAPTCHAS[cap['captcha_id']][0]
		data = self.call('/auth/signup', {'username': username, 'password': 'hunter22x', 'captcha_id': cap['captcha_id'], 'captcha': text.lower()})
		self.assertIn('token', data, data)
		return data['token']


	def start(self, body: dict, auth_a: str = '', auth_b: str = '') -> tuple:
		'''Create a room as player A and join it as player B. Returns (room id, tokens by color).'''

		a = self.call('/create', body, auth_a)
		b = self.call('/join', {'room_id': a['room_id']}, auth_b)
		self.assertIn('player_token', b, b)
		self.assertNotEqual(a['color'], b['color'])
		return a['room_id'], {a['color']: a['player_token'], b['color']: b['player_token']}


	def test_abort_and_draw(self):
		'''Abort only before both sides move, draws need the other side to accept.'''

		rid, t = self.start({'name': 'a'})
		self.play(rid, t, ['e2e4'])
		self.assertIn('ok', self.call('/abort', {'room_id': rid, 'player_token': t['b']}))
		self.assertEqual(self.call(f'/state?room_id={rid}', player_token=t['w'])['reason'], 'aborted')
		rid, t = self.start({'name': 'a'})
		self.play(rid, t, ['e2e4', 'e7e5'])
		self.assertIn('error', self.call('/abort', {'room_id': rid, 'player_token': t['w']}))
		self.call('/draw', {'room_id': rid, 'player_token': t['w'], 'action': 'offer'})
		self.assertEqual(self.call(f'/state?room_id={rid}', player_token=t['b'])['draw_offer'], 'w')
		self.assertIn('error', self.call('/draw', {'room_id': rid, 'player_token': t['w'], 'action': 'accept'}))
		self.call('/draw', {'room_id': rid, 'player_token': t['b'], 'action': 'accept'})
		s = self.call(f'/state?room_id={rid}', player_token=t['b'])
		self.assertEqual((s['result'], s['reason']), ('1/2-1/2', 'agreement'))


	def test_computer(self):
		'''The computer replies to moves, refuses draws, records results per level and plays again on request.'''

		if not ai.available():
			self.skipTest('engine binary not installed')
		self.assertEqual(self.call('/create', {'bot': 9})['error'], 'level must be 1-8')
		token = self.signup('carol')
		a     = self.call('/create', {'bot': 3, 'color': 'b'}, token)
		rid   = a['room_id']
		s     = self.wait(rid, a['player_token'], lambda s: s['turn'] == 'b')
		self.assertEqual((len(s['moves']), s['players']['w']['bot'], s['bot']), (1, 3, 3))
		self.assertEqual(self.call('/draw', {'room_id': rid, 'player_token': a['player_token'], 'action': 'offer'})['error'], 'the computer does not take draws')
		for _ in range(3):
			move = s['legal'][0]
			self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': a['player_token'], 'uci': move}))
			s = self.wait(rid, a['player_token'], lambda s: s['turn'] == 'b' or s['result'])
		self.assertEqual(len(s['moves']), 7)
		self.call('/resign', {'room_id': rid, 'player_token': a['player_token']})
		me = self.call('/auth/me', auth_token=token)['user']
		self.assertEqual((me['bot'], me['ratings']), ([{'level': 3, 'wins': 0, 'losses': 1, 'draws': 0}], {}))
		self.call('/rematch', {'room_id': rid, 'player_token': a['player_token']})
		s = self.call(f'/state?room_id={rid}', player_token=a['player_token'])
		self.assertEqual((s['color'], s['result'], s['turn'], len(s['legal'])), ('w', None, 'w', 20))
		self.assertEqual(self.call('/lobby')['bot'], True)


	def test_clock_flag(self):
		'''Clocks start after both first moves and running out loses.'''

		rid, t = self.start({'name': 'a', 'tc': '1+0'})
		self.play(rid, t, ['e2e4'])
		self.assertFalse(self.call(f'/state?room_id={rid}', player_token=t['w'])['clock_running'])
		self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'e7e5'}))
		s = self.call(f'/state?room_id={rid}', player_token=t['w'])
		self.assertTrue(s['clock_running'])
		self.assertEqual(s['clock']['b'], 60_000)
		server.rooms[rid]['game']['clock_at'] -= 61
		s = self.call(f'/state?room_id={rid}', player_token=t['w'])
		self.assertEqual((s['result'], s['reason'], s['clock']['w']), ('0-1', 'timeout', 0))


	def test_increment(self):
		'''Increment is added after each move once clocks run.'''

		rid, t = self.start({'name': 'a', 'tc': '3+2'})
		self.play(rid, t, ['e2e4', 'e7e5'])
		server.rooms[rid]['game']['clock_at'] -= 10
		s = self.play(rid, t, ['g1f3'])
		self.assertAlmostEqual(s['clock']['w'], 180_000 - 10_000 + 2000, delta=500)


	def test_lobby_and_quickplay(self):
		'''Open rooms show in the lobby only while their creator is connected, and quick play pairs matching settings.'''

		a = self.call('/create', {'name': 'host', 'public': True, 'tc': '10+0'})
		self.assertNotIn(a['room_id'], [r['room_id'] for r in self.call('/lobby')['rooms']])
		self.listen(a['room_id'])
		self.assertIn(a['room_id'], [r['room_id'] for r in self.call('/lobby')['rooms']])
		q1 = self.call('/quickplay', {'name': 'q1', 'tc': '5+0'})
		self.listen(q1['room_id'])
		q2 = self.call('/quickplay', {'name': 'q2', 'tc': '3+0'})
		self.assertNotEqual(q1['room_id'], q2['room_id'])
		q3 = self.call('/quickplay', {'name': 'q3', 'tc': '5+0'})
		self.assertEqual(q1['room_id'], q3['room_id'])
		self.assertNotEqual(q1['color'], q3['color'])
		self.assertIn('error', self.call('/quickplay', {'name': 'q4', 'tc': '5+0', 'rated': True}))


	def test_rated_game(self):
		'''A rated win moves both ratings by 20 at K=40, then a rematch swaps colors.'''

		ta, tb = self.signup('alice'), self.signup('bob')
		self.assertEqual(self.call('/auth/login', {'username': 'ALICE', 'password': 'nope'})['error'], 'wrong username or password')
		self.assertIn('token', self.call('/auth/login', {'username': 'ALICE', 'password': 'hunter22x'}))
		guest = self.call('/create', {'name': 'g', 'rated': True})
		self.assertEqual(guest['error'], 'sign in to play rated games')
		a = self.call('/create', {'color': 'w', 'rated': True}, ta)
		self.assertEqual(self.call('/join', {'room_id': a['room_id'], 'name': 'guest'})['error'], 'sign in to play rated games')
		self.assertEqual(self.call('/join', {'room_id': a['room_id']}, ta)['error'], 'you cannot play yourself in a rated game')
		b   = self.call('/join', {'room_id': a['room_id']}, tb)
		rid = a['room_id']
		t   = {'w': a['player_token'], 'b': b['player_token']}
		self.assertEqual(self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'e7e5'})['error'], 'not your turn')
		self.assertEqual(self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'e2e5'})['error'], 'illegal move')
		s = self.play(rid, t, SCHOLARS_MATE)
		self.assertEqual((s['result'], s['reason'], s['rating_diff']), ('1-0', 'checkmate', {'w': 20, 'b': -20}))
		self.assertEqual(s['moves'][-1]['san'], 'Qxf7#')
		self.assertIn('1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0', s['pgn'])
		board = self.call('/leaderboard')['players']
		self.assertEqual([(p['username'], p['rating']) for p in board], [('alice', 1220), ('bob', 1180)])
		me = self.call('/auth/me', auth_token=ta)['user']['ratings']['classic']
		self.assertEqual((me['wins'], me['games'], me['streak']), (1, 1, 1))
		self.call('/rematch', {'room_id': rid, 'player_token': t['w']})
		self.call('/rematch', {'room_id': rid, 'player_token': t['b']})
		s = self.call(f'/state?room_id={rid}', player_token=t['w'])
		self.assertEqual((s['color'], s['result'], s['moves'], s['players']['w']['rating']), ('b', None, [], 1180))


	def test_persistence(self):
		'''Rooms are saved and load back identically.'''

		rid, t = self.start({'name': 'a'})
		self.play(rid, t, ['d2d4', 'd7d5'])
		self.assertEqual(storage.load_rooms()[rid]['game'], server.rooms[rid]['game'])


	def test_recon(self):
		'''Reconnaissance Blind: sense then move, each side sees only its own pieces, blocked slides stop and capture, the king is captured to win, spectators trail behind.'''

		ta, tb = self.signup('rwhite'), self.signup('rblack')
		a   = self.call('/create', {'mode': 'recon', 'color': 'w', 'rated': True}, ta)
		rid = a['room_id']
		b   = self.call('/join', {'room_id': rid}, tb)
		t   = {'w': a['player_token'], 'b': b['player_token']}
		self.assertEqual(self.call('/create', {'mode': 'recon', 'bot': 1})['error'], 'the computer only plays classic for now')
		s = self.call(f'/state?room_id={rid}', player_token=t['w'])
		self.assertEqual((s['mode'], s['phase'], s['fen'].split()[0], s['legal']), ('recon', 'sense', '8/8/8/8/8/8/PPPPPPPP/RNBQKBNR', []))
		self.assertEqual(self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'e2e4'})['error'], 'sense first')
		self.assertEqual(self.call('/sense', {'room_id': rid, 'player_token': t['b'], 'square': 'e2'})['error'], 'not your turn')
		s = self.call('/sense', {'room_id': rid, 'player_token': t['w'], 'square': 'e7'})
		self.assertEqual({k: v['piece'] for k, v in s['ghosts'].items()}, {'d8': 'q', 'e8': 'k', 'f8': 'b', 'd7': 'p', 'e7': 'p', 'f7': 'p'})
		self.assertEqual((s['phase'], len(s['sensed']), 'pass' in s['legal'], 'e2e4' in s['legal'], 'd2e3' in s['legal']), ('move', 9, True, True, True))
		self.assertEqual(self.call('/sense', {'room_id': rid, 'player_token': t['w'], 'square': 'a1'})['error'], 'already sensed this turn')
		self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'e2e4'}))
		s = self.call(f'/state?room_id={rid}', player_token=t['b'])
		self.assertEqual((s['moves'][0]['san'], s['fen'].split()[0], s['pgn']), ('?', 'rnbqkbnr/pppppppp/8/8/8/8/8/8', None))
		# Put a hidden black pawn in the rook's path and empty d5 for a pawn capture that will fail
		game = server.rooms[rid]['game']
		game['fen'] = 'rnbqkbnr/1ppppppp/8/p7/4P3/8/1PPP1PPP/RNBQKBNR b KQkq - 0 1'
		self.call('/sense', {'room_id': rid, 'player_token': t['b'], 'square': None})
		self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'pass'}))
		self.call('/sense', {'room_id': rid, 'player_token': t['w'], 'square': None})
		s = self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'a1a8'})
		self.assertEqual([n['text'] for n in s['notices'][-2:]], ['a1a8 was stopped at a5', 'You captured a piece on a5'])
		self.assertEqual(s['moves'][-1]['san'], 'Rxa5')
		s = self.call(f'/state?room_id={rid}', player_token=t['b'])
		self.assertEqual((s['notices'][-1]['text'], s['ghosts']['a5']['piece'], s['moves'][-1]['san']), ('Your pawn on a5 was captured', '?', '?xa5'))
		self.call('/sense', {'room_id': rid, 'player_token': t['b'], 'square': None})
		self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'pass'})
		self.call('/sense', {'room_id': rid, 'player_token': t['w'], 'square': None})
		s = self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'e4d5'})
		self.assertEqual((s['notices'][-1]['text'], s['moves'][-1]['san'], s['fen'].split()[0]), ('e4d5 failed', 'e4d5 ✗', '8/8/8/R7/4P3/8/1PPP1PPP/1NBQKBNR'))
		spec = self.call(f'/state?room_id={rid}')
		self.assertEqual((len(spec['moves']), spec['delay'], spec['fen']), (1, 4, server.rooms[rid]['game']['moves'][0]['fen']))
		# Black passes, the rook takes the king
		self.call('/sense', {'room_id': rid, 'player_token': t['b'], 'square': 'a5'})
		self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'pass'})
		game['fen'] = 'rnbq1bnr/1ppppppp/8/R3k3/4P3/8/1PPP1PPP/1NBQKBNR w Kk - 0 4'
		self.call('/sense', {'room_id': rid, 'player_token': t['w'], 'square': None})
		s = self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'a5h5'})
		self.assertEqual((s['result'], s['reason'], s['rating_diff']), ('1-0', 'king captured', {'w': 20, 'b': -20}))
		self.assertIn('Rxe5#', s['pgn'])
		self.assertEqual(self.call(f'/state?room_id={rid}')['fen'], s['fen'])
		self.assertEqual([(p['username'], p['rating']) for p in self.call('/leaderboard?mode=recon')['players']], [('rwhite', 1220), ('rblack', 1180)])
		self.assertNotIn('classic', self.call('/auth/me', auth_token=ta)['user']['ratings'])


	def test_toggles(self):
		'''Twisted games get a new random layout every game, are always casual, and are refused where they aren't supported yet.'''

		token = self.signup('twister')
		a = self.call('/create', {'mode': 'big8', 'color': 'w', 'rated': True, 'toggles': {'holes': True, 'armies': True, 'swaps': ['amazon', 'nightriders', 'grasshoppers', 'nope'], 'junk': 1}}, token)
		b = self.call('/join', {'room_id': a['room_id'], 'name': 'guest'})
		self.assertIn('player_token', b, b)
		s = self.call(f'/state?room_id={a["room_id"]}', player_token=a['player_token'])
		self.assertEqual((s['rated'], s['toggles'], s['width'], s['start_fen'].count('*')), (False, {'holes': True, 'armies': True, 'swaps': ['nightriders', 'amazon']}, 10, 4))
		self.assertTrue(s['legal'])
		rows = s['start_fen'].split()[0].split('/')
		self.assertEqual(rows[0], rows[-1].lower())
		self.assertNotIn('N', rows[-1])
		self.assertEqual(self.call('/create', {'mode': 'recon', 'toggles': {'holes': True}})['error'], 'twists are not available for this game yet')
		self.assertEqual(self.call('/create', {'bot': 2, 'toggles': {'armies': True}})['error'], 'twists are not available for this game yet')
		self.call('/resign', {'room_id': a['room_id'], 'player_token': a['player_token']})
		self.call('/rematch', {'room_id': a['room_id'], 'player_token': a['player_token']})
		self.call('/rematch', {'room_id': a['room_id'], 'player_token': b['player_token']})
		s = self.call(f'/state?room_id={a["room_id"]}', player_token=a['player_token'])
		self.assertEqual((s['result'], s['start_fen'].count('*'), s['fen']), (None, 4, s['start_fen']))


	def test_rule_toggles(self):
		'''Drops put captures in hand and let them be dropped, three-check counts down, the hill wins, explosions clear the area.'''

		rid, t = self.start({'name': 'a', 'color': 'w', 'toggles': {'drops': True, 'threecheck': True, 'atomic': False}})
		s = self.play(rid, t, ['e2e4', 'd7d5', 'e4d5', 'd8d5', 'b1c3'])
		self.assertEqual((s['hand'], s['checks']), ({'w': {'P': 1}, 'b': {'P': 1}}, {'w': 3, 'b': 3, 'limit': 3}))
		self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'd5e5'}))
		s = self.call(f'/state?room_id={rid}', player_token=t['w'])
		self.assertEqual(s['checks'], {'w': 3, 'b': 2, 'limit': 3})
		self.assertIn('P@e3', s['legal'])
		self.assertNotIn('P@e1', s['legal'])
		s = self.call('/move', {'room_id': rid, 'player_token': t['w'], 'uci': 'g1e2'})
		self.assertNotIn('error', s)
		rid, t = self.start({'name': 'a', 'color': 'w', 'toggles': {'koth': True}})
		game = server.rooms[rid]['game']
		game['fen'] = '4k3/8/8/8/8/4K3/8/8 w - - 0 1'
		s = self.play(rid, t, ['e3e4'])
		self.assertEqual((s['result'], s['reason'], s['hill']), ('1-0', 'king of the hill', ['d4', 'e4', 'd5', 'e5']))
		rid, t = self.start({'name': 'a', 'color': 'w', 'toggles': {'atomic': True, 'drops': True}})
		self.assertEqual(server.rooms[rid]['toggles'], {'atomic': True})
		s = self.play(rid, t, ['e2e4', 'd7d5', 'e4d5'])
		self.assertEqual(s['fen'].split()[0], 'rnbqkbnr/ppp1pppp/8/8/8/8/PPPP1PPP/RNBQKBNR')


	def test_four(self):
		'''4-player: four seats, clockwise turns, resigning freezes your army, last king standing wins, ratings move pairwise.'''

		tokens = [self.signup(f'quad{i}') for i in range(4)]
		a = self.call('/create', {'mode': 'four', 'color': 'r', 'rated': True}, tokens[0])
		rid = a['room_id']
		t = {a['color']: a['player_token']}
		s = self.call(f'/state?room_id={rid}', player_token=t['r'])
		self.assertEqual((s['width'], len(s['board4']), s['colors'], s['legal']), (14, 196, ['r', 'b', 'y', 'g'], []))
		self.assertEqual(self.call('/move', {'room_id': rid, 'player_token': t['r'], 'uci': 'h2h4'})['error'], 'waiting for players')
		for token in tokens[1:]:
			j = self.call('/join', {'room_id': rid}, token)
			t[j['color']] = j['player_token']
		self.assertEqual(sorted(t), ['b', 'g', 'r', 'y'])
		self.assertEqual(self.call('/draw', {'room_id': rid, 'player_token': t['r'], 'action': 'offer'})['error'], 'there are no draws in 4-player')
		self.assertEqual(self.call('/move', {'room_id': rid, 'player_token': t['b'], 'uci': 'b7d7'})['error'], 'not your turn')
		s = self.call(f'/state?room_id={rid}', player_token=t['r'])
		self.assertEqual(len(s['legal']), 20)
		for color, uci in (('r', 'h2h4'), ('b', 'b7d7'), ('y', 'g13g11'), ('g', 'm8k8')):
			s = self.call('/move', {'room_id': rid, 'player_token': t[color], 'uci': uci})
			self.assertNotIn('error', s, uci)
		self.assertEqual((s['turn'], [m['san'] for m in s['moves']]), ('r', ['h2-h4', 'b7-d7', 'g13-g11', 'm8-k8']))
		self.assertIn('error', self.call('/abort', {'room_id': rid, 'player_token': t['r']}))
		# Blue resigns on its own turn: blue is out, its army stays, the turn passes to yellow
		self.assertNotIn('error', self.call('/move', {'room_id': rid, 'player_token': t['r'], 'uci': 'h4h5'}))
		self.call('/resign', {'room_id': rid, 'player_token': t['b']})
		s = self.call(f'/state?room_id={rid}', player_token=t['y'])
		self.assertEqual((s['alive'], s['turn'], s['board4'][6 * 14 + 0]), (['r', 'y', 'g'], 'y', 'bK'))
		self.call('/resign', {'room_id': rid, 'player_token': t['g']})
		self.call('/resign', {'room_id': rid, 'player_token': t['y']})
		s = self.call(f'/state?room_id={rid}', player_token=t['r'])
		self.assertEqual((s['result'], s['reason'], s['places']), ('r', 'resignation', {'r': 1, 'y': 2, 'g': 3, 'b': 4}))
		self.assertEqual(s['rating_diff']['r'], 20)
		self.assertEqual(sum(s['rating_diff'].values()), 0)
		self.assertEqual([p['username'] for p in self.call('/leaderboard?mode=four')['players']][0], 'quad0')
		for c in t:
			self.call('/rematch', {'room_id': rid, 'player_token': t[c]})
		s = self.call(f'/state?room_id={rid}', player_token=t['r'])
		self.assertEqual((s['result'], s['color'], s['moves']), (None, 'b', []))
		# Quick play fills one room with four players
		q = [self.call('/quickplay', {'name': f'q{i}', 'mode': 'four', 'tc': '3+2'}) for i in range(4)]
		self.listen(q[0]['room_id'])
		q = [q[0]] + [self.call('/quickplay', {'name': f'q{i}', 'mode': 'four', 'tc': '3+2'}) for i in range(3)]
		self.assertEqual(len({x['room_id'] for x in q}), 1)
		self.assertEqual(sorted(x['color'] for x in q), ['b', 'g', 'r', 'y'])
		# 2v2 ends at the first player out
		a = self.call('/create', {'mode': 'teams', 'color': 'r'})
		t = {'r': a['player_token']}
		for _ in range(3):
			j = self.call('/join', {'room_id': a['room_id'], 'name': 'x'})
			t[j['color']] = j['player_token']
		self.call('/resign', {'room_id': a['room_id'], 'player_token': t['g']})
		s = self.call(f'/state?room_id={a["room_id"]}', player_token=t['r'])
		self.assertEqual((s['result'], s['teams']), ('ry', True))


	def test_spectator(self):
		'''A third visitor watches instead of playing.'''

		rid, t = self.start({'name': 'a'})
		s = self.call('/join', {'room_id': rid})
		self.assertIsNone(s['player_token'])
		s = self.call(f'/state?room_id={rid}')
		self.assertTrue(s['spectator'])
		self.assertEqual(s['legal'], [])
		self.assertIn('error', self.call('/move', {'room_id': rid, 'player_token': '', 'uci': 'e2e4'}))



if __name__ == '__main__':
	unittest.main()
