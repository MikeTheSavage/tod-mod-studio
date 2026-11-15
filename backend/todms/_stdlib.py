"""Standard-library modules the vendored tools import at run time. The packager only sees imports in analysed code,
and the tools are loaded from backend/vendor as plain files, so they are listed here once."""
import argparse, base64, bisect, collections, contextlib, copy, csv, ctypes, glob, hashlib, io, json, math  # noqa
import pathlib, pickle, random, re, shutil, struct, subprocess, sys, tempfile, traceback, types, wave  # noqa
import winreg, zipfile, zlib, datetime, uuid, string, itertools, functools, operator, textwrap, fnmatch  # noqa
