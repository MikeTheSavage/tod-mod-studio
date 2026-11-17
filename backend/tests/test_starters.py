"""Starter projects: recipes only, valid in the recipe format, no game bytes in them."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import missions_tpl as MT, paths, starters


class Starters(unittest.TestCase):
    def test_every_starter_opens_and_the_mods_are_valid_recipes(self):
        from todms import mods  # puts todct on the path
        from todct import todmod
        ids = [s['id'] for s in starters.listing()]
        self.assertEqual(ids, ['level', 'tuning', 'race'])
        for sid in ('level', 'tuning'):
            r = starters.open_one(sid)
            self.assertEqual(r['kind'], 'mod')
            m = r['mod']
            self.assertNotIn('id', m)                      # a starter is never tied to a library entry
            todmod.validate(dict(m, id='x'))
        self.assertTrue(starters.open_one('level')['mod']['level'])
        self.assertTrue(starters.open_one('tuning')['mod']['data'])
        with self.assertRaises(KeyError):
            starters.open_one('nope')

    def test_no_game_files_are_shipped(self):
        # recipes are small text: no archive, no binary, no block payload
        total = 0
        for f in os.listdir(starters.DIR):
            p = os.path.join(starters.DIR, f)
            self.assertTrue(f.endswith('.json'), f)
            data = open(p, 'rb').read()
            total += len(data)
            json.loads(data.decode('utf-8'))
            self.assertLess(len(data), 20000, f)
        self.assertLess(total, 60000)

    def test_the_race_is_a_sample_mission_project(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, TODMS_HOME=os.path.join(t, 'home'), TODMS_CACHE=os.path.join(t, 'cache')):
            info = {s['key']: s for s in MT.sample_info()}
            self.assertIn('race', info)
            self.assertFalse(info['race']['uses_all_slots'])
            self.assertEqual(info['race']['missions'], 1)
            p = MT.open_sample('race')
            self.assertEqual([m['type'] for m in p['project']['missions']], ['race'])
            self.assertEqual(len(p['project']['missions'][0]['params']['gates']), 9)


if __name__ == '__main__':
    unittest.main()
