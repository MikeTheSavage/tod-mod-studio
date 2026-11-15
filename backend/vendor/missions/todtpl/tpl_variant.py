"""tpl_variant.py - shipped mission blocks that a template starts from with a small edit ("variants").

A variant is NEVER stored as game data: it is made from the player's own blocks.naz by an edit recipe (data/<recipe>.json: fragtool ops, no game
bytes) and cached under tpl_env.CFG['cache']/variants/. A template names it as block_path='variant:<name>'; tpl_build resolves it here.
In the lab a pre-made copy (missions/mesa/base/subm_04_d1.mission) is used when it exists: it is byte-identical to the generated one (unit test).
"""
import argparse, hashlib, json, os, shutil, sys, tempfile
sys.dont_write_bytecode = True
from . import tpl_env

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = {
    # name: shipped block, edit recipe (the first block entry of the file), lab copy (optional, same bytes)
    'd1': dict(block='subm_04_down_somsal_kill.mission', recipe=os.path.join(HERE, 'data', 'd1_go_kill3_return.json'),
               lab=os.path.join(os.path.dirname(os.path.dirname(HERE)), 'mesa', 'base', 'subm_04_d1.mission')),
}
PREFIX = 'variant:'


def is_variant(bp):
    return isinstance(bp, str) and bp.startswith(PREFIX)


def resolve(bp, use_lab=True):
    """a real file path for block_path: unchanged unless it names a variant"""
    if not is_variant(bp):
        return bp
    v = VARIANTS[bp[len(PREFIX):]]
    if use_lab and os.path.exists(v['lab']) and not os.environ.get('TPL_VARIANT_GENERATE'):
        return v['lab']
    return generate(bp[len(PREFIX):])


def generate(name):
    v = VARIANTS[name]
    E = tpl_env.get()
    ft = E.ft
    recipe = open(v['recipe'], 'rb').read()
    entry = E.SHARED + v['block']
    base = E.ft.archive().read(entry)
    key = hashlib.sha256(recipe + base).hexdigest()[:20]
    cdir = os.path.join(tpl_env.CFG['cache'], 'variants')
    os.makedirs(cdir, exist_ok=True)
    out = os.path.join(cdir, '%s_%s.%s' % (name, key, v['block'].rsplit('.', 1)[-1]))
    if os.path.exists(out):
        return out
    tmp = tempfile.mkdtemp(prefix='tplvar_')
    try:
        spec = os.path.join(tmp, 'edit.json')
        open(spec, 'wb').write(recipe)
        with tpl_env.quiet():
            rc = ft.cmd_edit(argparse.Namespace(edit=spec, out=tmp, deploy=None))
        made = os.path.join(tmp, v['block'])
        if rc or not os.path.exists(made):
            raise RuntimeError('Could not prepare the %s mission block from your game files (the edit did not apply: is this the GOG version?)' % name)
        shutil.copyfile(made, out + '.part')
        os.replace(out + '.part', out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out
