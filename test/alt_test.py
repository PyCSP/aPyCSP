#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import asyncio
from common import handle_common_args, CSPTaskGroup
from apycsp import process, Alternative, Channel, Parallel, Skip, Timer

handle_common_args()


@process
async def AltTest_p():
    sg1 = Skip()
    sg2 = Skip()
    ch = Channel('p')
    alt = Alternative(sg1, sg2, ch.read)
    ret = await alt.select()
    print("Returned from alt.select():", ret)


@process
async def p1(cin):
    print("Bip 1")
    alt = Alternative(cin)
    for i in range(10):
        print(f"p1: ding {i}")
        _, ret = await alt.select()
        print("p1: got from select:", ret, type(ret))


# Same as above, but demonstrates the async with syntax.
@process
async def p1_b(cin):
    print("Bip 1")
    alt = Alternative(cin)
    for _ in range(10):
        print("ding 1")
        async with alt as (g, val):
            print("p1_b: got from select:", g, type(g), val)


@process(verbose_poison=True)
async def alt_writer(cout):
    print("This is altwriter")
    for i in range(10):
        val = f"sendpkt{i}"
        print(" -- altwriter sending with alt", val)
        g = cout.alt_pending_write(val)
        alt = Alternative(g)
        ret = await alt.select()
        print(" -- alt_writer done, got ", ret)
        print(" ** ch queue : ", cout._chan.queue)


@process(verbose_poison=True)
async def alt_reader(cin):
    print("This is altreader")
    for i in range(10):
        alt = Alternative(cin)
        print(" -- altreader waiting")
        ret = await alt.select()
        print(" -- altreader got ", ret)
        # print(" ** ch queue : ", cin._chan.queue)


@process
async def alt_timer(cin):
    print("This is alttimer")
    for i in range(10):
        timer = Timer(0.100)
        alt = Alternative(cin, timer)
        (g, ret) = await alt.select()
        if isinstance(g, Timer):
            print(f"alttimer {i}: timeout")
        else:
            print(f"alttimer {i}: got :{ret}")


@process
async def writer(cout):
    print("This is writer")
    await asyncio.sleep(0.500)
    await cout("ping")


@process
async def p2(cout):
    print("Bip 2")
    for i in range(10):
        await cout("foo %d" % i)


async def AltTest():
    print("------------- AltTest ----------------")
    await Parallel(AltTest_p())


async def AltTest2():
    print("------------- AltTest2 ----------------")
    c = Channel('ch2')
    await Parallel(
        p1(c.read),
        p2(c.write))


async def AltTest3():
    print("------------- AltTest3 ----------------")
    c = Channel('ch3')
    await Parallel(
        p1_b(c.read),
        p2(c.write))


async def AltTest4():
    print("------------- AltTest4 ----------------")
    c = Channel('ch4')
    await Parallel(
        alt_writer(c.write),
        p1(c.read))


async def AltTest5():
    print("------------- AltTest5 ----------------")
    c = Channel('ch5')
    await Parallel(
        alt_timer(c.read),
        writer(c.write))


async def poison_check():
    print("--------- checking for poison handling in alts ---- ")

    async with CSPTaskGroup() as wg:
        print("** Poison channel that read alt is waiting for")
        ch = Channel("poison-tst1")
        wg.spawn(alt_reader(ch.read))
        await ch.write('tst')
        await asyncio.sleep(0.3)
        await ch.poison()

    async with CSPTaskGroup() as wg:
        print("** Poison channel that write alt is waiting for")
        ch = Channel("poison-tst2")
        wg.spawn(alt_writer(ch.write))
        await asyncio.sleep(0.3)
        await ch.poison()

    async with CSPTaskGroup() as wg:
        print("** Poison channel before letting the read alt enable on it")
        ch = Channel("poison-tst3")
        await ch.poison()
        wg.spawn(alt_reader(ch.read))

    async with CSPTaskGroup() as wg:
        print("** Poison channel before letting the read alt enable on it")
        ch = Channel("poison-tst4")
        await ch.poison()
        wg.spawn(alt_writer(ch.write))


async def run_tests():
    await AltTest()
    await AltTest2()
    await AltTest3()
    await AltTest4()
    await AltTest5()
    await poison_check()


asyncio.run(run_tests())
