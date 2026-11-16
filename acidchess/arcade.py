#!/usr/bin/env python3
# acid-arcade-db - Developed by acidvegas in Python (https://github.com/acidvegas)
# client/arcade.py

# Client for acid-arcade-db. Copy this file into a game unchanged. With ARCADE_URL unset the game keeps its own accounts and never calls this.

import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request


ARCADE_URL    = os.environ.get('ARCADE_URL', '').rstrip('/')        # internal API, e.g. http://acid-arcade-db:20021
ARCADE_PUBLIC = os.environ.get('ARCADE_PUBLIC_URL', '').rstrip('/') # public site, e.g. https://arcade.{domain} ({domain} becomes the player's parent domain)
ARCADE_GAME   = os.environ.get('ARCADE_GAME', '')                   # this game's slug in acid-arcade-db's games.json
ARCADE_KEY    = os.environ.get('ARCADE_KEY', '')                    # this game's key, when acid-arcade-db has ARCADE_GAME_KEYS set
TIMEOUT       = 5
COOKIE        = 'arcade_sso' # shared sign-in cookie on the parent domain, e.g. .acid.vegas
COOKIE_TTL    = 30 * 24 * 60 * 60

if ARCADE_URL and not ARCADE_GAME:
	raise RuntimeError('ARCADE_URL is set but ARCADE_GAME is empty, set it to this game\'s slug in acid-arcade-db\'s games.json')


class ArcadeDown(Exception):
	'''acid-arcade-db could not be reached. Games answer 503 when this is raised.'''


class ArcadeError(Exception):
	'''acid-arcade-db refused a request. str() is the error message to show the player and .status is the HTTP status.'''

	def __init__(self, message: str, status: int):
		super().__init__(message)
		self.status = status


def avatar_url(user_id: int, host: str) -> str:
	'''Return the public URL of a player's profile picture, on the arcade of the same domain as host.'''

	return f'{public_url(host)}/avatar/{user_id}'


def call(path: str, body: dict = None) -> dict:
	'''GET (no body) or POST JSON to the internal API and return the JSON reply.'''

	req = urllib.request.Request(ARCADE_URL + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Arcade-Key': ARCADE_KEY})
	try:
		with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
			return json.load(resp)
	except urllib.error.HTTPError as e:
		try:
			message = json.load(e).get('error') or str(e)
		except ValueError:
			message = str(e)
		raise ArcadeError(message, e.code)
	except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e: # ValueError is a reply that is not JSON, HTTPException a broken one such as IncompleteRead
		raise ArcadeDown(str(e))


def captcha() -> dict:
	'''Return a new captcha: {captcha_id, svg}.'''

	return call('/internal/captcha')


def changes(since: float) -> dict:
	'''Return {now, changed: [{user_id, username}], deleted: [user_id]} since a time. Poll it and pass back the last now.'''

	return call(f'/internal/changes?since={since}')


def clear_cookie(resp, host: str):
	'''Remove the shared sign-in cookie from a Flask response.'''

	resp.delete_cookie(COOKIE, domain=cookie_domain(host), secure=True, httponly=True, samesite='Lax')


def cookie_domain(host: str) -> str:
	'''Return the parent domain to share the sign-in cookie on (chess.acid.vegas -> acid.vegas), or None for hosts without one.'''

	host = host.split(':')[0]
	parts = host.split('.')
	if len(parts) < 2 or host.replace('.', '').isdigit():
		return None
	return '.'.join(parts[-2:])


def enabled() -> bool:
	'''Return True if this game is set up to use acid-arcade-db.'''

	return bool(ARCADE_URL)


def event(user_id: int, kind: str, text: str):
	'''Add a line to the arcade activity feed. text reads after the player's name: "won a rated Classic game (+12 Elo)".

	:param kind: a short tag such as win, solve, bigwin, record, streak
	'''

	call('/internal/event', {'game': ARCADE_GAME, 'user_id': user_id, 'kind': kind, 'text': text})


def login(username: str, password: str, ip: str) -> dict:
	'''Log in. Returns {token, user_id, username} or raises ArcadeError (429 after too many failures).

	:param ip: the player's address (request.remote_addr behind a trusted proxy), used to limit failed logins
	'''

	return call('/internal/login', {'username': username, 'password': password, 'ip': ip})


def logout(token: str):
	'''End a session.'''

	call('/internal/logout', {'token': token})


def presence(user_ids: list):
	'''Report the signed in players who have this game open right now. Call it every 30 seconds, even with an empty list.'''

	call('/internal/presence', {'game': ARCADE_GAME, 'user_ids': list(user_ids)})


def public_url(host: str) -> str:
	'''Return the arcade site for a request's host: ARCADE_PUBLIC_URL with {domain} filled in (chess.supernets.org -> https://arcade.supernets.org).'''

	return ARCADE_PUBLIC.replace('{domain}', cookie_domain(host) or host.split(':')[0])


def push_stats(user_id: int, main: float, stats: dict):
	'''Store a player's summary for this game: main is the leaderboard number (higher is better), stats is shown on their profile.'''

	call('/internal/stats', {'game': ARCADE_GAME, 'user_id': user_id, 'main': main, 'stats': stats})


def session(token: str) -> dict:
	'''Return {user_id, username, admin} for a session token, or None if it is not valid.'''

	if not token:
		return None
	try:
		return call('/internal/session', {'token': token})
	except ArcadeError as e:
		if e.status == 401:
			return None
		raise


def set_cookie(resp, host: str, token: str):
	'''Set the shared sign-in cookie on a Flask response, so the other sites on this domain can sign in from it.'''

	resp.set_cookie(COOKIE, token, max_age=COOKIE_TTL, domain=cookie_domain(host), secure=True, httponly=True, samesite='Lax')


def signup(username: str, password: str, captcha_id: str, captcha_answer: str, ip: str) -> dict:
	'''Create an account. Returns {token, user_id, username} or raises ArcadeError (429 after too many from one address).

	:param ip: the player's address (request.remote_addr behind a trusted proxy), used to limit new accounts
	'''

	return call('/internal/signup', {'username': username, 'password': password, 'captcha_id': captcha_id, 'captcha': captcha_answer, 'ip': ip})


def sso(token: str) -> dict:
	'''Swap a shared sign-in cookie token for a new session on this game. Returns {token, user_id, username}, or None if it is not valid.'''

	if not token:
		return None
	try:
		return call('/internal/sso', {'token': token})
	except ArcadeError as e:
		if e.status == 401:
			return None
		raise


def user(username: str) -> dict:
	'''Return {user_id, username} for an account name, or None if there is no such account.'''

	try:
		return call('/internal/user?username=' + urllib.parse.quote(username or ''))
	except ArcadeError as e:
		if e.status == 404:
			return None
		raise
