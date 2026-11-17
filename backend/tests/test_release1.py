"""Release 1.1.0 polish: Ready lists only a project's own rows."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from todms import problems


def row(id_, parts, status='amber'):
    return dict(id=id_, label=id_, kinds=['newmap'], status=status, parts=parts, used=6, max=8, unit='archives', enforce='warn', jump='newmaps',
                effect='', items=[])


class OwnRows(unittest.TestCase):
    def test_installed_packages_alone_are_not_the_project(self):
        out = problems._from_ledger([row('P1', dict(vanilla=5, packages=1, project=0)), row('L8', dict(vanilla=9, packages=0, project=1))], 'newmap')
        self.assertEqual([p['title'].split(':')[0] for p in out], ['L8'])

    def test_red_stays(self):
        out = problems._from_ledger([row('P1', dict(vanilla=5, packages=4, project=0), 'red')], 'newmap')
        self.assertEqual(len(out), 1)


class StartupCheck(unittest.TestCase):
    def test_missing_parts_names_what_cannot_be_imported(self):
        from todms.workspace import Workspace
        self.assertEqual(Workspace.missing_parts(), [])
        real = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__
        import builtins

        def no_pil(name, *a, **k):
            if name == 'PIL':
                raise ImportError(name)
            return real(name, *a, **k)
        builtins.__import__ = no_pil
        try:
            self.assertEqual(Workspace.missing_parts(), ['PIL'])
        finally:
            builtins.__import__ = real




if __name__ == '__main__':
    unittest.main()
