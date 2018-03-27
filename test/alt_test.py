#!/usr/bin/env python3
# -*- coding: latin-1 -*-
# Copyright (c) 2018 John Markus Bj�rndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License). 
from common import *
from apycsp import *
from apycsp.plugNplay import *

@process
async def AltTest_p():
    sg1 = Skip()
    sg2 = Skip()
    ch = One2OneChannel()
    alt = Alternative(sg1, sg2, ch.read)
    ret = await alt.select()
    print("Returned from alt.select():", ret)

@process
async def p1(cin):
    print("Bip 1")
    alt = Alternative(cin)
    for i in range(10):
        print("ding 1")
        ret = await alt.select()
        val = await ret()
        print("p1: got from select:", ret, type(ret), val)
        
@process    
async def p2(cout):
    print("Bip 2")
    for i in range(10):
        await cout("foo %d" % i)


def AltTest():
    Sequence(AltTest_p())
    
def AltTest2():
    c = One2OneChannel()
    Parallel(p1(c.read),
             p2(c.write))

AltTest()
AltTest2()