"""Disassemble GOG TOD.exe at a VA: dis.py <hexva> [count]"""
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import pe
va = int(sys.argv[1], 16); n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
md = Cs(CS_ARCH_X86, CS_MODE_32)
for i, ins in enumerate(md.disasm(pe.read(va, n * 8), va)):
    if i >= n: break
    print('%08x: %-8s %s' % (ins.address, ins.mnemonic, ins.op_str))
