"""Starter projects: three small finished examples (a level tweak, a tuning tweak, a race mission).

They are recipes only: lists of changes and mission settings. They hold no game files and no copied game blocks; the level tweak and the
race are written against object names the game already has, and the app builds the real thing from the player's own game.
"""
import json
import os

from . import paths

DIR = os.path.join(paths.DATA, 'starters')


def _load(name):
    with open(os.path.join(DIR, name), encoding='utf-8') as f:
        return json.load(f)


def index():
    return _load('index.json')


def listing():
    out = []
    for s in index():
        out.append(dict(id=s['id'], kind=s['kind'], screen=s['screen']))
    return out


def open_one(sid):
    """-> dict(kind, screen, mod=<recipe without an id>) for a mod starter; dict(kind, screen, sample=key) for the mission starter."""
    for s in index():
        if s['id'] != sid:
            continue
        if s['kind'] == 'mod':
            m = _load(s['file'])
            m = {k: v for k, v in m.items() if k not in ('id', 'created', 'updated')}
            return dict(kind='mod', screen=s['screen'], mod=m)
        return dict(kind='mission', screen=s['screen'], sample=s['sample'])
    raise KeyError('no starter %s' % sid)
