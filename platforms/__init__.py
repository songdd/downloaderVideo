# -*- coding: utf-8 -*-
import os, sys
# Allow platform modules to import from parent directory (cookies, login)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
