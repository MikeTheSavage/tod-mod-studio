"""The user's own words for a trigger in a section (a text a mod shows on screen), the way the mission templates do it:
a blank row of uk_Objective.txt is given the text (ordinal -> `FeedbackText`), and the language blocks that hold the rows travel in the
mod's pack (textool's edit, the same tool and the same five languages as the mesa build's text_override.zip).

A trigger's `params.text` is a number (a line the game already has) or a string (the user's words). A string is written into a blank row of uk_Objective.txt that every language has: rows 345..351
(seven; the mission templates fill the same blanks from 345 upward, so this takes them from 351 downward). The file is longer in some
languages (383 rows in uk and de, 352 in fr, es and it), so a row appended at the end would get a different number per language: never append.
Two installs that both change the language blocks (a mod with texts and a mission project) write the same blocks: the later one in the pack
wins them.
"""
import copy
import json
import os
import tempfile
import zipfile

FIRST_ROW = 351                        # the last blank row every language has; the next texts take 350, 349 ...
MAX_TEXTS = 7
LANGS = ['uk', 'de', 'fr', 'es', 'it']
MAX_LEN = 80                           # characters; the engine ends a string at a unit with low byte 0 and a long line runs off the screen


class TextError(ValueError):
    pass


def is_words(v):
    """True for a string the user typed (not a number and not empty)."""
    if isinstance(v, str):
        s = v.strip()
        return bool(s) and not s.isdigit()
    return False


def words_of(ops):
    """The distinct strings of the mission ops, in order."""
    out = []
    for o in ops or []:
        t = (o.get('params') or {}).get('text')
        if o.get('op') in ('add_trigger', 'add_action') and is_words(t) and t.strip() not in out:
            out.append(t.strip())
    return out


def resolve(ops):
    """-> (ops with every string replaced by its row number, [{file, ordinal, value}]). The originals are not changed."""
    words = words_of(ops)
    if not words:
        return list(ops or []), []
    if len(words) > MAX_TEXTS:
        raise TextError('At most %d different texts fit in one install (this one has %d).' % (MAX_TEXTS, len(words)))
    for w in words:
        if len(w) > MAX_LEN:
            raise TextError('A text is at most %d characters: "%s..."' % (MAX_LEN, w[:20]))
        if '%' in w or '\x00' in w:
            raise TextError('A text cannot hold a percent sign: "%s"' % w[:30])
    row = {w: FIRST_ROW - i for i, w in enumerate(words)}
    out = []
    for o in ops:
        t = (o.get('params') or {}).get('text')
        if o.get('op') in ('add_trigger', 'add_action') and is_words(t):
            o = copy.deepcopy(o)
            o['params']['text'] = row[t.strip()]
        out.append(o)
    edits = [dict(file='uk_Objective.txt', ordinal=r, value=w) for w, r in row.items()]
    return out, edits


def blocks(ws, edits, progress=None):
    """The language blocks with the edits applied -> [(entry, bytes)] (textool edit: round trip, verify, five languages)."""
    if not edits:
        return []
    from . import missions_tpl as MT
    with MT.session(ws):
        from todtpl import tpl_env
        to = tpl_env.textool()
        to._ARCH = None
        d = tempfile.mkdtemp(prefix='todms_text_')
        ej = os.path.join(d, 'edit.json')
        json.dump(dict(description='texts of triggers in sections', langs=LANGS, edits=edits), open(ej, 'w'), indent=1)
        with tpl_env.quiet():
            rc = to.cmd_edit(type('A', (), dict(edit=ej, out=d, deploy=None))())
        if rc:
            raise TextError('The text tool refused the text: see %s' % os.path.join(d, 'report.json'))
        z = os.path.join(d, 'text_override.zip')
        with zipfile.ZipFile(z) as zf:
            return [(n, zf.read(n)) for n in zf.namelist()]


def shipped_lines(ws):
    """The lines uk_Objective.txt already has that a trigger can show: [{i, text}] (no parameters, no blanks)."""
    from . import missions_tpl as MT
    with MT.session(ws):
        from todtpl import tpl_env
        to = tpl_env.textool()
        rows = to.text_table('uk').get('uk_Objective.txt') or []
    return [dict(i=i, text=v) for i, (_k, v) in enumerate(rows) if v and '%' not in v and i < 345]
