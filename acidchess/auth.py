#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/auth.py

import math
import random
import re
import secrets
import threading
import time

from flask import request

import arcade
from storage import DB_LOCK, db_connect, mirror_user


CAPTCHA_TTL    = 300
CAPTCHA_MAX    = 5000 # captchas kept at once, the oldest are dropped past this
SESSION_TTL    = 30 * 24 * 60 * 60
CAPTCHAS       = {}
CAPTCHA_LOCK   = threading.Lock()
USERNAME_RE    = re.compile(r'^[A-Za-z0-9_]{3,16}$')
CAPTCHA_CHARS  = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' # no I/O/0/1
SEEN           = {} # acid-arcade-db user id -> when their session was last checked, for presence
CAPTCHA_COLORS = ['#ff7da0', '#ffae41', '#4dd17a', '#5fa8ff', '#b07dff', '#ffd86a', '#ff5e8a', '#7da0ff']
ATTEMPTS       = {} # rate limit key -> recent attempt times
ATTEMPTS_LOCK  = threading.Lock()
LIMITS         = {'account': (10, 900), 'ip': (30, 900), 'captcha': (30, 60)} # kind -> (attempts, seconds)

# Captcha glyphs as strokes on a 10 wide, 14 tall grid (y down). They are drawn as warped SVG paths, so the answer is never in the markup as text.
GLYPHS = {
	'A': [[(0, 14), (5, 0), (10, 14)], [(2, 8.5), (8, 8.5)]],
	'B': [[(0, 0), (0, 14), (6.5, 14), (9, 12.5), (9, 9), (6.5, 7), (0, 7)], [(0, 0), (6, 0), (8.5, 1.5), (8.5, 5), (6, 7)]],
	'C': [[(9.5, 2), (7.5, 0), (3, 0), (0.5, 2.5), (0, 7), (0.5, 11.5), (3, 14), (7.5, 14), (9.5, 12)]],
	'D': [[(0, 0), (0, 14), (5, 14), (8.5, 11.5), (10, 7), (8.5, 2.5), (5, 0), (0, 0)]],
	'E': [[(10, 0), (0, 0), (0, 14), (10, 14)], [(0, 7), (7, 7)]],
	'F': [[(10, 0), (0, 0), (0, 14)], [(0, 7), (7, 7)]],
	'G': [[(9.5, 2), (7.5, 0), (3, 0), (0.5, 2.5), (0, 7), (0.5, 11.5), (3, 14), (7.5, 14), (10, 12), (10, 8), (6, 8)]],
	'H': [[(0, 0), (0, 14)], [(10, 0), (10, 14)], [(0, 7), (10, 7)]],
	'J': [[(10, 0), (10, 10.5), (8, 14), (3, 14), (0, 11)]],
	'K': [[(0, 0), (0, 14)], [(10, 0), (0, 8)], [(3, 6), (10, 14)]],
	'L': [[(0, 0), (0, 14), (10, 14)]],
	'M': [[(0, 14), (0, 0), (5, 8), (10, 0), (10, 14)]],
	'N': [[(0, 14), (0, 0), (10, 14), (10, 0)]],
	'P': [[(0, 14), (0, 0), (7, 0), (10, 2), (10, 5.5), (7, 7.5), (0, 7.5)]],
	'Q': [[(5, 0), (1.5, 1.5), (0, 7), (1.5, 12.5), (5, 14), (8.5, 12.5), (10, 7), (8.5, 1.5), (5, 0)], [(6, 10), (10, 14.5)]],
	'R': [[(0, 14), (0, 0), (7, 0), (10, 2), (10, 5.5), (7, 7.5), (0, 7.5)], [(5, 7.5), (10, 14)]],
	'S': [[(9.5, 2), (7, 0), (3, 0), (0.5, 2), (0.5, 5), (3, 6.8), (7, 7.2), (9.5, 9), (9.5, 12), (7, 14), (3, 14), (0.5, 12)]],
	'T': [[(0, 0), (10, 0)], [(5, 0), (5, 14)]],
	'U': [[(0, 0), (0, 10.5), (2, 14), (8, 14), (10, 10.5), (10, 0)]],
	'V': [[(0, 0), (5, 14), (10, 0)]],
	'W': [[(0, 0), (2.5, 14), (5, 6), (7.5, 14), (10, 0)]],
	'X': [[(0, 0), (10, 14)], [(10, 0), (0, 14)]],
	'Y': [[(0, 0), (5, 7), (10, 0)], [(5, 7), (5, 14)]],
	'Z': [[(0, 0), (10, 0), (0, 14), (10, 14)]],
	'2': [[(0.5, 3), (2.5, 0.3), (7, 0.3), (9.5, 2.5), (9.5, 5), (0, 14), (10, 14)]],
	'3': [[(0.5, 1.5), (3, 0), (7, 0), (9.5, 2), (9.5, 5), (7, 7), (4, 7)], [(7, 7), (9.8, 9), (9.8, 12), (7, 14), (3, 14), (0.5, 12.5)]],
	'4': [[(7.5, 14), (7.5, 0), (0, 10), (10, 10)]],
	'5': [[(9.5, 0), (1, 0), (0.5, 6), (4, 5.5), (7.5, 6), (10, 8.5), (10, 11.5), (7.5, 14), (3, 14), (0.5, 12.5)]],
	'6': [[(9, 1), (6.5, 0), (3, 0), (0.5, 3), (0, 8), (0.5, 12), (3, 14), (7, 14), (9.8, 12), (9.8, 9), (7, 7), (3, 7), (0.3, 9)]],
	'7': [[(0, 0), (10, 0), (4, 14)]],
	'8': [[(5, 7), (1.5, 5.5), (1, 2.5), (3, 0), (7, 0), (9, 2.5), (8.5, 5.5), (5, 7), (1, 9), (0.5, 12), (3, 14), (7, 14), (9.5, 12), (9, 9), (5, 7)]],
	'9': [[(9.7, 5), (7, 7), (3, 7), (0.3, 5), (0.3, 2), (3, 0), (7, 0), (9.7, 2), (10, 6), (9.5, 11), (7, 14), (3.5, 14), (1, 13)]],
}


def attempt(kind: str, key: str):
	'''Record an attempt against a rate limit.'''

	with ATTEMPTS_LOCK:
		ATTEMPTS.setdefault(f'{kind}:{key}', []).append(time.time())


def blocked(kind: str, key: str) -> bool:
	'''Return True if a rate limit is used up. Also drops attempts that are too old to count.'''

	limit, window = LIMITS[kind]
	now = time.time()
	with ATTEMPTS_LOCK:
		for k in [k for k, times in ATTEMPTS.items() if not times or now - times[-1] > LIMITS[k.split(':', 1)[0]][1]]: # each key by its own limit's window, or a short window (captchas) would wipe login failures
			del ATTEMPTS[k]
		times = ATTEMPTS.get(f'{kind}:{key}', [])
		times[:] = [t for t in times if now - t < window]
		return len(times) >= limit


def captcha_create() -> dict:
	'''Create a captcha and return its id and SVG.'''

	cid  = secrets.token_urlsafe(12)
	text = ''.join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))
	now  = time.time()
	with CAPTCHA_LOCK:
		for k in [k for k, (_, exp) in CAPTCHAS.items() if exp < now] + list(CAPTCHAS)[:max(0, len(CAPTCHAS) - CAPTCHA_MAX + 1)]:
			CAPTCHAS.pop(k, None)
		CAPTCHAS[cid] = (text, now + CAPTCHA_TTL)
	return {'captcha_id': cid, 'svg': captcha_render_svg(text)}


def captcha_render_svg(text: str) -> str:
	'''Render captcha text as a noisy SVG. Each character is drawn from GLYPHS as jittered, rotated path strokes in a random order, so there is no text to read out of the markup.'''

	w, h  = 220, 80
	parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">', f'<rect width="{w}" height="{h}" fill="#1a1a28" rx="8"/>']
	for _ in range(40):
		parts.append(f'<circle cx="{random.randint(0, w)}" cy="{random.randint(0, h)}" r="{random.uniform(0.6, 1.8):.1f}" fill="{random.choice(CAPTCHA_COLORS)}" fill-opacity="0.4"/>')
	strokes = []
	slot    = (w - 30) / len(text)
	for i, ch in enumerate(text):
		cx, cy = 15 + slot * (i + 0.5) + random.uniform(-3, 3), h / 2 + random.uniform(-5, 5)
		scale  = random.uniform(2.2, 2.7)
		turn   = math.radians(random.uniform(-22, 22))
		lean   = random.uniform(-0.25, 0.25)
		color  = random.choice(CAPTCHA_COLORS)
		width  = random.uniform(2.6, 3.6)
		for line in GLYPHS[ch]:
			pts = []
			for x, y in line:
				x, y = (x - 5 + random.uniform(-0.6, 0.6) + lean * (y - 7)) * scale, (y - 7 + random.uniform(-0.6, 0.6)) * scale
				pts.append((cx + x * math.cos(turn) - y * math.sin(turn), cy + x * math.sin(turn) + y * math.cos(turn)))
			strokes.append((pts, color, width))
	for _ in range(6): # decoy strokes in the same colors and widths, so stroke style alone can't separate them from the letters
		x, y = random.uniform(0, w), random.uniform(10, h - 10)
		pts  = [(x, y)]
		for _ in range(random.randint(1, 3)):
			x, y = x + random.uniform(-22, 22), y + random.uniform(-16, 16)
			pts.append((x, y))
		strokes.append((pts, random.choice(CAPTCHA_COLORS), random.uniform(1.4, 3.0)))
	random.shuffle(strokes)
	for pts, color, width in strokes:
		d = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in pts)
		parts.append(f'<path d="{d}" stroke="{color}" stroke-width="{width:.1f}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>')
	pts = ' '.join(f'{x},{h / 2 + random.uniform(-18, 18):.1f}' for x in range(0, w + 1, 12))
	parts.append(f'<polyline points="{pts}" stroke="{random.choice(CAPTCHA_COLORS)}" stroke-opacity="0.5" stroke-width="2" fill="none"/></svg>')
	return ''.join(parts)


def captcha_verify(cid: str, answer: str) -> bool:
	'''Check a captcha answer. Each captcha can only be tried once.'''

	if not cid or answer is None:
		return False
	with CAPTCHA_LOCK:
		rec = CAPTCHAS.pop(cid, None)
	if rec is None or time.time() > rec[1]:
		return False
	return str(answer).strip().upper() == rec[0]


def create_session(user_id: int) -> str:
	'''Create a login session and return its token.'''

	token = secrets.token_urlsafe(32)
	with DB_LOCK, db_connect() as c:
		c.execute('INSERT INTO sessions(token, user_id, expires_at) VALUES(?, ?, ?)', (token, user_id, int(time.time()) + SESSION_TTL))
	return token


def delete_session(token: str):
	'''Log a session out.'''

	with DB_LOCK, db_connect() as c:
		c.execute('DELETE FROM sessions WHERE token=?', (token,))


def request_token() -> str:
	'''Return the auth token sent with the current request.'''

	return request.headers.get('X-Auth-Token') or ''


def request_user() -> tuple:
	'''Return (user id, username) for the current request, or (None, None) for guests.'''

	token = request_token()
	if not token:
		return None, None
	if arcade.enabled():
		user = arcade.session(token)
		if not user:
			return None, None
		mirror_user(user['user_id'], user['username'])
		SEEN[user['user_id']] = time.time()
		return user['user_id'], user['username']
	with db_connect() as c:
		row = c.execute('SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=? AND s.expires_at > ?', (token, int(time.time()))).fetchone()
	return (row['id'], row['username']) if row else (None, None)
