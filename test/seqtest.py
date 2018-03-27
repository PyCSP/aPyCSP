#!/usr/bin/env python
# -*- coding: latin-1 -*-
# Copyright (c) 2007 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

from common import *
from apycsp import *
from apycsp.plugNplay import *

@process
async def TestProc(n):
    print("This is test proc", n)

Sequence(TestProc(1),
         TestProc(2),
         TestProc(3))


@process
async def TestProc2(n):
    print("This is test proc", n)

Sequence(TestProc2(1),
         TestProc2(2),
         TestProc2(3))
