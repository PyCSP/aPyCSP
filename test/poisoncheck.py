#!/usr/bin/env python3
# -*- coding: latin-1 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

from common import *
from apycsp import *
from apycsp.plugNplay import *

@process
async def PoisonTest(cout):
    for i in range(100):
        print(i)
        await cout(i)
    await poisonChannel(cout)

def test():
    a = One2OneChannel("a")
    b = One2OneChannel("b")
    c = One2OneChannel("c")
    d = BlackHoleChannel("d")

    run_CSP(PoisonTest(a.write),
            Identity(a.read, b.write),
            Identity(b.read, c.write),
            Identity(c.read, d.write))
    for ch in [a,b,c,d]:
        print("State of channel", ch.name, "- poisoned is", ch.poisoned)

@process
async def PoisonReader(cin):
    for i in range(100):
        r = await cin()
        print(i, r)
    await cin.poison()

@process
async def Count(cout):
    i = 0
    while 1:
        await cout(i)
        i += 1

def test2():
    a = Any2OneChannel()
    run_CSP(Count(a.write),
            Count(a.write),
            PoisonReader(a.read))
    print("Processes done")

if __name__ == "__main__":
    test()
    test2()
