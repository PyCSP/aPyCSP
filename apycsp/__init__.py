#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
PyCSP implementation of the CSP Core functionality (Channels, Processes, PAR, ALT).

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""

if 0:
    # Use the base/lock implementation still
    from .lockimpl import *
else:
    from .coreimpl import *
