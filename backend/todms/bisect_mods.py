"""Find the mod that breaks the game: switch the installed mods off in halves. Each step installs a subset into the TEST copy only and the player
says whether the problem still happens. Pure logic: the state is a small dict the server keeps in a file and the UI shows.

  phase 'search'   candidates are the mods that may cause it; the next test runs the first half of them
  phase 'confirm'  one candidate is left; it is tested alone
  phase 'done'     verdict: one mod, or "needs several mods together" (neither half shows the problem alone), or "none" (the problem stays with nothing on)
"""
import datetime


def start(ids):
    ids = list(ids)
    st = dict(phase='search', all=ids, candidates=ids, steps=[], verdict=None, culprit=None, started=datetime.datetime.now().isoformat(timespec='seconds'))
    if len(ids) < 2:
        st['phase'] = 'confirm' if ids else 'done'
        if not ids:
            st['verdict'] = 'none'
    return st


def pending(st):
    """The mod ids the next test installs, or None when the search is over."""
    if st['phase'] == 'done':
        return None
    c = st['candidates']
    if st['phase'] == 'confirm':
        return [c[0]]
    return c[:len(c) // 2]


def answer(st, bad):
    """bad: the problem happened with the subset `pending` named. Returns the new state (the argument is not changed)."""
    st = dict(st, steps=list(st['steps']))
    test = pending(st)
    if test is None:
        return st
    st['steps'].append(dict(mods=test, bad=bool(bad)))
    c = st['candidates']
    if st['phase'] == 'confirm':
        st['phase'] = 'done'
        if bad:
            st['verdict'], st['culprit'] = 'one', c[0]
        else:
            st['verdict'] = 'several'
        return st
    if bad and len(test) == 1:                      # one mod alone shows the problem: that is the answer
        st.update(candidates=test, phase='done', verdict='one', culprit=test[0])
        return st
    st['candidates'] = test if bad else c[len(c) // 2:]
    if len(st['candidates']) == 1:
        st['phase'] = 'confirm'
    return st
