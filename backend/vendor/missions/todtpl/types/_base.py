"""types/_base.py - pieces every template module uses to build its Spec"""
import sys
sys.dont_write_bytecode = True
from ..tpl_core import Spec


class Inst:
    """one mission instance of a project: index (resolved), first (first instance of its type in the project), sfx (name suffix of non-first instances)"""

    def __init__(self, index, first=True, id=None):
        self.index = index
        self.first = first
        self.sfx = '' if first else '_%d' % index
        self.id = id


def new_root(mod, template_root, index, first):
    """fragment root name of the new mission block: SAME LENGTH as the template root (the block format needs fixed-size names)"""
    if first and index == mod.LEGACY_INDEX:
        return mod.LEGACY_ROOT
    n = len(template_root) - len('.fragment')
    s = 'SubM_%02d_Tpl%s' % (index, mod.NAME.capitalize())
    s = (s + 'x' * n)[:n]
    return s + '.fragment'


def giver_dict(mod, p, host, inst):
    x, y, z = p['giver_pos']
    return dict(name=mod.GIVER_NAME + inst.sfx, pos=[x, host.gy(x, z, y) + 0.6, z], yaw=p['giver_yaw'], size=p['giver_size'], height=p['giver_height'])


def texts(p, objectives):
    return dict(name=p['name'], description=p['description'], objectives=list(objectives), load_mid=p['load_mid'] or p['name'], load_low=p['load_low'])


def make_spec(mod, p, host, inst, template, objectives_text, objectives, design, award_scores=None, **extra):
    """award_scores: which of Award_3/2/1 to set; the pass / silver / gold parameters fill them (silver / gold None = keep the template's)"""
    sc = {'Award_3_ActionPoints': p['pass_score']}
    if p['silver_score'] is not None:
        sc['Award_2_ActionPoints'] = p['silver_score']
    if p['gold_score'] is not None:
        sc['Award_1_ActionPoints'] = p['gold_score']
    sp = Spec(NAME=mod.NAME, INDEX=inst.index, TEMPLATE=template, NEW_ROOT=new_root(mod, template['root'], inst.index, inst.first),
              GIVER=giver_dict(mod, p, host, inst), TEXT=texts(p, objectives_text), OBJECTIVES=objectives, design=design,
              PASS_SCORE=p['pass_score'], AWARD_SCORES=sc, START_SPOT=p['start_spot'], FOLDER_NAME='MESA_MISSION_%d' % inst.index)
    sp.__dict__.update(extra)
    return sp
