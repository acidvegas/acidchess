#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# tests/test_arcade.py

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('ACIDCHESS_DATA_DIR', tempfile.mkdtemp(prefix='acidchess_test_'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'acidchess'))

import app as server
import arcade
import auth
import storage


ACCOUNTS = {'tok-ann': {'user_id': 1001, 'username': 'ann', 'admin': False}, 'tok-ben': {'user_id': 1002, 'username': 'ben', 'admin': False}}


class Stop(BaseException):
	'''Raised from the fake sleep to end the sync loop after one pass.'''


class TestArcade(unittest.TestCase):
	'''Arcade mode with the acid-arcade-db client mocked out.'''

	def setUp(self):
		'''Turn arcade mode on with fake sessions.'''

		self.client = server.app.test_client()
		self.pushed = mock.Mock()
		for patch in (mock.patch.object(arcade, 'enabled', return_value=True), mock.patch.object(arcade, 'ARCADE_PUBLIC', 'https://arcade.example'), mock.patch.object(arcade, 'session', side_effect=ACCOUNTS.get), mock.patch.object(arcade, 'push_stats', self.pushed)):
			patch.start()
			self.addCleanup(patch.stop)


	def call(self, path: str, body: dict = None, auth_token: str = '', status: int = 200) -> dict:
		'''Make a GET or POST request, check its status and return the JSON reply.'''

		headers = {'X-Auth-Token': auth_token}
		resp    = self.client.get(path, headers=headers) if body is None else self.client.post(path, json=body, headers=headers)
		self.assertEqual(resp.status_code, status, resp.get_json())
		return resp.get_json()


	def sync_once(self, changes: dict):
		'''Run one pass of the acid-arcade-db sync loop.'''

		real = time.sleep

		def fake_sleep(n: float):
			if threading.current_thread() is threading.main_thread():
				raise Stop
			real(n)

		with mock.patch.object(arcade, 'changes', return_value=changes), mock.patch.object(server.time, 'sleep', fake_sleep):
			with self.assertRaises(Stop):
				server.arcade_sync()


	def wait_pushes(self, count: int) -> dict:
		'''Wait for stats pushes and return them by user id.'''

		end = time.time() + 5
		while self.pushed.call_count < count and time.time() < end:
			time.sleep(0.05)
		self.assertEqual(self.pushed.call_count, count)
		return {c.args[0]: c.args[1:] for c in self.pushed.call_args_list}


	def test_auth_proxy(self):
		'''Captcha, signup, login and logout go to acid-arcade-db with the same reply shapes and the player's IP, its errors pass through.'''

		with mock.patch.object(arcade, 'captcha', return_value={'captcha_id': 'c1', 'svg': '<svg/>'}):
			self.assertEqual(self.call('/auth/captcha'), {'captcha_id': 'c1', 'svg': '<svg/>'})
		with mock.patch.object(arcade, 'signup', return_value={'token': 'tok-ann', 'user_id': 1001, 'username': 'ann'}) as signup:
			resp = self.client.post('/auth/signup', json={'username': 'ann', 'password': 'hunter22x', 'captcha_id': 'c1', 'captcha': 'ABCDE'}, headers={'X-Forwarded-For': '203.0.113.7'})
			self.assertEqual(resp.get_json()['token'], 'tok-ann')
			signup.assert_called_once_with('ann', 'hunter22x', 'c1', 'ABCDE', '203.0.113.7')
		with mock.patch.object(arcade, 'login', return_value={'token': 'tok-ann', 'user_id': 1001, 'username': 'ann'}) as login:
			self.client.post('/auth/login', json={'username': 'ann', 'password': 'hunter22x'}, headers={'X-Forwarded-For': '203.0.113.8'})
			login.assert_called_once_with('ann', 'hunter22x', '203.0.113.8')
		with mock.patch.object(arcade, 'login', side_effect=arcade.ArcadeError('wrong username or password', 401)):
			self.assertEqual(self.call('/auth/login', {'username': 'ann', 'password': 'nope'}, status=401)['error'], 'wrong username or password')
		with mock.patch.object(arcade, 'login', side_effect=arcade.ArcadeError('too many failed logins, try again later', 429)):
			self.assertEqual(self.call('/auth/login', {'username': 'ann', 'password': 'nope'}, status=429)['error'], 'too many failed logins, try again later')
		with mock.patch.object(arcade, 'signup', side_effect=arcade.ArcadeError('too many new accounts, try again later', 429)):
			self.assertEqual(self.call('/auth/signup', {'username': 'ann', 'password': 'hunter22x'}, status=429)['error'], 'too many new accounts, try again later')
		with mock.patch.object(arcade, 'logout') as logout:
			self.call('/auth/logout', {}, 'tok-ann')
			logout.assert_called_once_with('tok-ann')
		with mock.patch.object(arcade, 'session', side_effect=arcade.ArcadeDown('refused')):
			self.assertEqual(self.call('/auth/me', auth_token='tok-ann', status=503)['error'], 'account server is down')
			self.assertEqual(self.call('/create', {'name': 'x'}, 'tok-ann', status=503)['error'], 'account server is down')
		self.assertIsNone(self.call('/auth/me', auth_token='bad')['user'])
		self.assertIn(b'data-arcade="https://arcade.example"', self.client.get('/').data)
		with mock.patch.object(arcade, 'ARCADE_PUBLIC', 'https://arcade.{domain}'):
			self.assertIn(b'data-arcade="https://arcade.supernets.org"', self.client.get('/', base_url='https://chess.supernets.org').data)
			self.assertIn(b'data-arcade="https://arcade.acid.vegas"', self.client.get('/', base_url='https://chess.acid.vegas').data)


	def test_game_rename_delete(self):
		'''A rated game pushes both summaries, renames show everywhere and a deleted account leaves no rows.'''

		me = self.call('/auth/me', auth_token='tok-ann')['user']
		self.assertEqual((me['id'], me['username']), (1001, 'ann'))
		with storage.db_connect() as c:
			self.assertEqual(c.execute('SELECT password_hash FROM users WHERE id=1001').fetchone()['password_hash'], '')
		a = self.call('/create', {'mode': 'big8', 'rated': True, 'color': 'w'}, 'tok-ann')
		b = self.call('/join', {'room_id': a['room_id']}, 'tok-ben')
		self.call('/chat', {'room_id': a['room_id'], 'player_token': b['player_token'], 'text': 'hi'})
		self.call('/resign', {'room_id': a['room_id'], 'player_token': b['player_token']})
		pushes = self.wait_pushes(2)
		self.assertEqual(pushes[1001], (1200, {'Big Board 10x8 Elo': 1220, 'Games': 1, 'Wins': 1, 'Losses': 0, 'Draws': 0}))
		self.assertEqual(pushes[1002], (1200, {'Big Board 10x8 Elo': 1180, 'Games': 1, 'Wins': 0, 'Losses': 1, 'Draws': 0}))
		# The finished game is not pushed again by later changes to the room
		self.call('/chat', {'room_id': a['room_id'], 'player_token': b['player_token'], 'text': 'gg'})
		time.sleep(0.2)
		self.assertEqual(self.pushed.call_count, 2)
		s = self.call(f'/state?room_id={a["room_id"]}')
		self.assertEqual((s['players']['w']['user_id'], s['chat'][0]['user_id']), (1001, 1002))

		self.sync_once({'now': 5, 'changed': [{'user_id': 1002, 'username': 'benny'}, {'user_id': 4242, 'username': 'stranger'}], 'deleted': []})
		self.assertEqual(self.call('/user/1001')['user']['recent'][0]['black'], 'benny')
		self.assertIn(('benny', 1180), [(p['username'], p['rating']) for p in self.call('/leaderboard?mode=big8')['players']])
		s = self.call(f'/state?room_id={a["room_id"]}')
		self.assertEqual((s['players']['b']['name'], s['chat'][0]['name']), ('benny', 'benny'))
		self.assertIsNone(self.call('/user/4242', status=404).get('user'))

		storage.record_four('zz01', 'four', {'r': 'benny', 'b': 'x', 'y': 'y', 'g': 'z'}, {'r': 1002, 'b': None, 'y': None, 'g': None}, {'r': 1, 'b': 2, 'y': 3, 'g': 4}, 'r', 'checkmate', False, None)
		self.sync_once({'now': 6, 'changed': [], 'deleted': [1002]})
		self.call('/user/1002', status=404)
		with storage.db_connect() as c:
			for table in ('ratings', 'bot_stats', 'sessions'):
				self.assertIsNone(c.execute(f'SELECT 1 FROM {table} WHERE user_id=1002').fetchone(), table)
			self.assertIsNone(c.execute('SELECT 1 FROM games WHERE white_id=1002 OR black_id=1002').fetchone())
			self.assertEqual(json.loads(c.execute("SELECT players FROM games4 WHERE room_id='zz01'").fetchone()['players'])['r'], ['deleted', None])
		self.assertEqual(self.call('/user/1001')['user']['recent'][0]['black'], 'deleted')


	def test_mirror_name_swap(self):
		'''A name taken over by another account parks the stale mirror row instead of failing.'''

		storage.mirror_user(2001, 'swapme')
		storage.mirror_user(2002, 'swapme')
		with storage.db_connect() as c:
			self.assertEqual({r['id']: r['username'] for r in c.execute('SELECT id, username FROM users WHERE id IN (2001, 2002)')}, {2001: '#2001', 2002: 'swapme'})


	def test_shared_sign_in(self):
		'''Signing in shares a cookie on the parent domain, other sites swap it for a session, logging out clears it.'''

		self.client = server.app.test_client(use_cookies=False)
		site        = 'https://chess.acid.vegas'
		login       = {'token': 'tok-ann', 'user_id': 1001, 'username': 'ann'}
		with mock.patch.object(arcade, 'login', return_value=login):
			resp = self.client.post('/auth/login', json={'username': 'ann', 'password': 'hunter22x'}, base_url=site)
		self.assertEqual(resp.get_json(), login)
		self.assertIn(f'{arcade.COOKIE}=tok-ann; Domain=acid.vegas', resp.headers['Set-Cookie'])
		with mock.patch.object(arcade, 'sso', return_value={'token': 'tok-ann', 'user_id': 1001, 'username': 'ann'}) as sso:
			resp = self.client.get('/auth/sso', headers={'Cookie': f'{arcade.COOKIE}=shared'}, base_url=site)
			sso.assert_called_once_with('shared')
		self.assertEqual(resp.get_json(), login)
		with mock.patch.object(arcade, 'sso', return_value=None):
			resp = self.client.get('/auth/sso', base_url=site)
		self.assertEqual(resp.status_code, 401)
		self.assertIn(f'{arcade.COOKIE}=;', resp.headers['Set-Cookie'])
		resp = self.client.get('/auth/me', headers={'X-Auth-Token': 'tok-ann'}, base_url=site)
		self.assertEqual(resp.get_json()['user']['id'], 1001)
		self.assertIn(f'{arcade.COOKIE}=tok-ann', resp.headers['Set-Cookie'])
		resp = self.client.get('/auth/me', headers={'X-Auth-Token': 'tok-ann', 'Cookie': f'{arcade.COOKIE}=tok-ann'}, base_url=site)
		self.assertNotIn('Set-Cookie', resp.headers)
		self.assertNotIn('Set-Cookie', self.client.get('/auth/me', headers={'X-Auth-Token': 'bad'}, base_url=site).headers)
		with mock.patch.object(arcade, 'logout') as logout:
			resp = self.client.post('/auth/logout', json={}, headers={'X-Auth-Token': 'tok-ann'}, base_url=site)
			logout.assert_called_once_with('tok-ann')
		self.assertIn(f'{arcade.COOKIE}=;', resp.headers['Set-Cookie'])


	def test_summary_bot(self):
		'''Games against the computer show up in the summary, the classic rating is the main number.'''

		storage.record_bot_game(3001, 2, 1)
		storage.record_bot_game(3001, 5, 0.5)
		storage.record_game('zz00', 'classic', 'p', 'q', 3001, 3002, '1-0', 'resignation', True, None, '')
		main, stats = storage.summary(3001, {'classic': 'Classic'})
		self.assertEqual((main, stats), (1220, {'Classic Elo': 1220, 'Games': 1, 'Wins': 1, 'Losses': 0, 'Draws': 0, 'Bot wins': 1, 'Bot losses': 0, 'Bot draws': 1}))



class TestStandalone(unittest.TestCase):
	'''Without acid-arcade-db the site never touches the shared sign-in cookie.'''

	def test_no_cookie(self):
		'''Signup, login, me and logout set no cookie, and there is no /auth/sso.'''

		client = server.app.test_client()
		cap    = client.get('/auth/captcha').get_json()
		resp   = client.post('/auth/signup', json={'username': 'solo', 'password': 'hunter22x', 'captcha_id': cap['captcha_id'], 'captcha': auth.CAPTCHAS[cap['captcha_id']][0]})
		token  = resp.get_json()['token']
		for resp in (resp, client.post('/auth/login', json={'username': 'solo', 'password': 'hunter22x'}), client.get('/auth/me', headers={'X-Auth-Token': token}), client.post('/auth/logout', json={}, headers={'X-Auth-Token': token})):
			self.assertEqual(resp.status_code, 200)
			self.assertNotIn('Set-Cookie', resp.headers)
		self.assertEqual(client.get('/auth/sso', headers={'Cookie': f'{arcade.COOKIE}=x'}).status_code, 404)



if __name__ == '__main__':
	unittest.main()
