"""Release 1.1.0 final: an arrival on a giver centre is refused before the build."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from todms import missions_tpl as MT


def lp(arrive=None, arrival=(1400.0, 20.6, 1374.0), giver=(1412.0, None, 1384.0), kind='new_map'):
    entry = dict(id='e1', block='b')
    if arrive:
        entry['arrive'] = dict(pos=list(arrive), yaw=0.0)
    return dict(hosts=[dict(id='yard', kind=kind, map_index=0)],
                missions=[dict(id='ghost', type='ghost', host='yard', params=dict(giver_pos=list(giver)))],
                new_map=dict(maps=[dict(arrival=dict(pos=list(arrival)), teleports=[dict(name='SPOT_1', pos=[1400.0, 20.6, 1400.0])], entries=[entry])]))


class ArrivalOnGiver(unittest.TestCase):
    def test_entrance_arrival_on_the_giver_centre_is_an_error(self):
        out = MT.arrival_giver_messages(lp(arrive=(1412.0, 20.6, 1384.0)))
        self.assertEqual([m['level'] for m in out], ['error'])
        self.assertEqual(out[0]['where'], 'ghost')
        self.assertIn('entrance e1', out[0]['text'])

    def test_anywhere_in_the_box_is_an_error_and_outside_it_is_not(self):
        self.assertEqual(len(MT.arrival_giver_messages(lp(arrive=(1412.0, 20.6, 1381.5)))), 1)     # 2.5 m from the centre of a 6 m box
        self.assertEqual(MT.arrival_giver_messages(lp(arrive=(1412.0, 20.6, 1380.0))), [])         # 4 m: outside the box and its margin

    def test_map_arrival_and_teleport_spots_count_too(self):
        self.assertEqual(len(MT.arrival_giver_messages(lp(arrival=(1412.3, 20.6, 1384.2)))), 1)
        self.assertEqual(len(MT.arrival_giver_messages(lp(giver=(1400.0, None, 1401.5)))), 1)

    def test_existing_hosts_and_unplaced_givers_are_skipped(self):
        self.assertEqual(MT.arrival_giver_messages(lp(arrive=(1412.0, 20.6, 1384.0), kind='existing')), [])
        self.assertEqual(MT.arrival_giver_messages(lp(arrive=(1412.0, 20.6, 1384.0), giver=(None, None, None))), [])


if __name__ == '__main__':
    unittest.main()
