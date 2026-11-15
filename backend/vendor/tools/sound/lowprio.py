"""Import first: drops this process to BELOW_NORMAL priority (Windows) so the user's other process keeps the machine."""
import ctypes, sys
if sys.platform == 'win32':
    k = ctypes.windll.kernel32
    k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
