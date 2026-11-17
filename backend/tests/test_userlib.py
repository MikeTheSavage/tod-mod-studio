"""The per-user editor library (prefabs, shortcuts, scatter presets, copy buffer) and the project-only editor data."""
import json
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import server, userlib, mods


class UserLibTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('TODMS_HOME')
        os.environ['TODMS_HOME'] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop('TODMS_HOME', None)
        else:
            os.environ['TODMS_HOME'] = self.old
        self.tmp.cleanup()

    def test_empty_library_has_every_key(self):
        d = server.h_userlib_get({}, {})
        self.assertEqual(d, {'prefabs': [], 'shortcuts': {}, 'scatter': {}, 'clipboard': {}})

    def test_save_and_read_back(self):
        pre = [{'id': 'p1', 'name': 'Crate pile', 'items': [{'dpos': [0, 0, 0]}]}]
        server.h_userlib_set({}, {'key': 'prefabs', 'value': pre})
        server.h_userlib_set({}, {'key': 'shortcuts', 'value': {'level.undo': 'ctrl+z'}})
        d = server.h_userlib_get({}, {})
        self.assertEqual(d['prefabs'], pre)
        self.assertEqual(d['shortcuts']['level.undo'], 'ctrl+z')

    def test_bad_key_and_bad_shape_are_refused(self):
        with self.assertRaises(server.ApiError):
            server.h_userlib_set({}, {'key': 'nope', 'value': {}})
        with self.assertRaises(server.ApiError):
            server.h_userlib_set({}, {'key': 'prefabs', 'value': {'a': 1}})

    def test_unreadable_file_gives_empty_values(self):
        Path(self.tmp.name, userlib.FILE).write_text('{not json', encoding='utf-8')
        self.assertEqual(userlib.load()['prefabs'], [])

    def test_oversized_library_is_refused(self):
        with self.assertRaises(server.ApiError):
            server.h_userlib_set({}, {'key': 'prefabs', 'value': ['x' * 1024] * 5000})

    def test_editor_data_rides_along_with_a_saved_mod(self):
        m = {'name': 'Layers', 'level': [], 'data': {}, 'editor': {'layers': [{'id': 'l1', 'name': 'Props'}], 'notes': [{'id': 'n1', 'text': 'check'}]}}
        saved = mods.save_mod(m)
        again = mods.get_mod(saved['id'])
        self.assertEqual(again['editor']['layers'][0]['name'], 'Props')
        from todct import todmod
        todmod.validate(again)         # the recipe check does not mind it, and no builder reads it


class QuietOpenTest(unittest.TestCase):
    def test_a_quiet_open_leaves_the_last_view_alone(self):
        from unittest.mock import MagicMock, patch
        w = MagicMock()
        w.settings = {'last_view': {'map': 'map06'}}
        with patch.object(server, 'need_game', return_value=w):
            server.h_open({}, {'map': 'map02', 'quiet': True})
            self.assertEqual(w.settings['last_view'], {'map': 'map06'})
            w.save_settings.assert_not_called()
            server.h_open({}, {'map': 'map02'})
            self.assertEqual(w.settings['last_view']['map'], 'map02')
            w.save_settings.assert_called_once()


if __name__ == '__main__':
    unittest.main()
