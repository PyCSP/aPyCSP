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
    return f'proc{n}'

print("---- Testing Sequence")
r = Sequence(TestProc(1),
             TestProc(2),
             TestProc(3))
print("Return values", r)


print("\n---- Test of aSequence")
loop = asyncio.get_event_loop()
r = loop.run_until_complete(aSequence(TestProc(1),
                                      TestProc(2),
                                      TestProc(3)))
print("Return values", r)


print("\n---- Test of Parallel")
r = Parallel(TestProc(1),
             TestProc(2),
             TestProc(3))
print("Return values", r)


print("\n---- Test of aParallel")
r = loop.run_until_complete(aParallel(TestProc(1),
                                      TestProc(2),
                                      TestProc(3)))
print("Return values", r)
