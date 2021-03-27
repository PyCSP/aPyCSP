#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

from common import handle_common_args
from apycsp import process, Channel, chan_poisoncheck, poisonChannel, run_CSP
from apycsp.plugNplay import Identity

handle_common_args()

if 'BlackHoleChannel' not in vars():
    print("Temp workaround for missing BlackHoleChannel")

    class BlackHoleChannel(Channel):
        def __init__(self, name=None):
            Channel.__init__(self, name)

        @chan_poisoncheck
        async def _write(self, obj=None):
            pass

        @chan_poisoncheck
        async def _read(self):
            raise "BlackHoleChannels are not readable"


@process
async def PoisonTest(cout):
    for i in range(100):
        print(i)
        await cout(i)
    await poisonChannel(cout)


def test():
    a = Channel("a")
    b = Channel("b")
    c = Channel("c")
    d = BlackHoleChannel("d")

    run_CSP(PoisonTest(a.write),
            Identity(a.read, b.write),
            Identity(b.read, c.write),
            Identity(c.read, d.write))
    for ch in [a, b, c, d]:
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
    a = Channel()
    run_CSP(Count(a.write),
            Count(a.write),
            PoisonReader(a.read))
    print("Processes done")


if __name__ == "__main__":
    test()
    test2()
