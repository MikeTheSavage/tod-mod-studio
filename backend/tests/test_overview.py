"""The read-only overview endpoint behind the status bar (no game folder needed for the empty case)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import server


class FakeJobs:
    jobs = {'a': dict(id='a', kind='prepare', status='running', message='map01', done=2, total=30),
            'b': dict(id='b', kind='open', status='done', message='', done=0, total=0)}


class FakeWs:
    game = None
    jobs = FakeJobs()


class OverviewTest(unittest.TestCase):
    def test_without_a_game_lists_only_running_jobs(self):
        with patch.object(server, 'ws', return_value=FakeWs()):
            out = server.h_overview({}, {})
        self.assertFalse(out['ready'])
        self.assertEqual([j['id'] for j in out['jobs']], ['a'])
        self.assertEqual(out['jobs'][0]['total'], 30)


if __name__ == '__main__':
    unittest.main()
