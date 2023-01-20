#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import asyncio
from apycsp import process, Alternative, Channel, Parallel, Skip, Timer
from apycsp.utils import handle_common_args, CSPTaskGroup


def list_same(lst1, lst2):
    """Checks that the lists are of the same length and same contents"""
    return len(lst1) == len(lst2) and all([x == y for x, y in zip(lst1, lst2)])


def merge_par_results(res):
    """Results from a Parallel could, in principle, be returned in any order.
    To simplify handling, the processes return a dict with their own name as key
    and the value as a result.
    This function merges the results.
    """
    nres = {}
    for r in res:
        nres.update(r)
    return nres


@process
async def alt_reader(cin, name='alt_reader', N=10):
    print("This is", name)
    alt = Alternative(cin)
    rets = []
    for i in range(N):
        print(f"{name}: ding {i}")
        g, ret = await alt.select()
        print(f"{name}: got from select: {ret} {type(ret)}")
        assert g == cin, "Returned guard should be cin"
        rets.append(ret)
    return {name : rets}


@process
async def alt_reader_newalt(cin, name='alt_reader_newalt', N=10):
    """Like alt_reader, but creates a new alt every iteration"""
    print("This is", name)
    rets = []
    for i in range(N):
        alt = Alternative(cin)
        print(f"{name}: ding {i}")
        g, ret = await alt.select()
        print(f"{name}: got from select: {ret} {type(ret)}")
        assert g == cin, "Returned guard should be cin"
        rets.append(ret)
    return {name : rets}


@process
async def alt_reader_awith(cin, name='alt_reader_awith', N=10):
    """Like alt_reader, but uses the async with syntax"""
    print("This is", name)
    alt = Alternative(cin)
    rets = []
    for _ in range(N):
        print("ding 1, name")
        async with alt as (g, val):
            print(f"{name}: got from select:", g, type(g), val)
            assert g == cin, "Returned guard should be cin"
            rets.append(val)
    return {name : rets}


@process(verbose_poison=True)
async def alt_writer(cout, name='alt_writer', N=10):
    print("This is", name)
    rets = []
    for i in range(N):
        val = f"sendpkt{i}"
        print(f" -- {name} sending with alt {val}")
        wg = cout.alt_pending_write(val)
        alt = Alternative(wg)
        g, ret = await alt.select()
        print(f" -- {name} done, got {g, ret}, ** ch queue: ", cout._chan.queue)
        assert g == g
        assert ret == 0
        rets.append(val)
    return {name : rets}


@process
async def alt_timer(cin, name="alt_timer", N=10):
    print("This is alttimer")
    rets = []
    for i in range(N):
        timer = Timer(0.100)
        alt = Alternative(cin, timer)
        (g, ret) = await alt.select()
        assert g in [cin, timer], "returned guard should be either the timer or cin"
        if isinstance(g, Timer):
            print(f"alttimer {i}: timeout")
            rets.append('timeout')
        else:
            print(f"alttimer {i}: got :{ret}")
            rets.append(ret)
    return {name: rets}


@process
async def sleep_write_once(cout, name='sleep_write_once'):
    print("This is writer")
    await asyncio.sleep(0.500)
    await cout("ping")
    return {name: ["ping"]}


@process
async def write_n(cout, name='write_n', N=10):
    print("Bip 2")
    rets = []
    for i in range(N):
        msg = f"foo {i}"
        ret = await cout(msg)
        assert ret == 0, 'Writes should return 0'
        rets.append(msg)
    return {name : rets}


async def test_alt_skip():
    print("------------- test alt using skip ----------------")
    sg1 = Skip()
    sg2 = Skip()
    ch = Channel('p')
    alt = Alternative(sg1, sg2, ch.read)
    ret = await alt.select()
    ch.verify()
    print("Returned from alt.select():", ret)
    assert ret[0] in (sg1, sg2), "Alt should pick one of the results"
    assert ret[1] is None, "Skip shouldn't return a value here"


async def test_alt_single_reader_chan():
    print("------------- test alt on reader, single chan ----------------")
    c = Channel('ch2')
    res = await Parallel(
        alt_reader(c.read),
        write_n(c.write))

    c.verify()
    rdict = merge_par_results(res)
    read_res = rdict['alt_reader']
    write_res = rdict['write_n']
    assert list_same(read_res, write_res), "Should have the same number of reads and writes, and all written values should be read in order"


async def test_alt_single_reader_chan_awith():
    print("------------- test alt on reader, single chan, using async with ----------------")
    c = Channel('ch3')
    res = await Parallel(
        alt_reader_awith(c.read),
        write_n(c.write))

    c.verify()
    rdict = merge_par_results(res)
    read_res = rdict['alt_reader_awith']
    write_res = rdict['write_n']
    assert list_same(read_res, write_res), "Should have the same number of reads and writes, and all written values should be read in order"


async def test_alt_on_writer_and_reader():
    print("------------- Test alt on both reader and writer ----------------")
    c = Channel('ch4')
    res = await Parallel(
        alt_writer(c.write),
        alt_reader(c.read))
    c.verify()
    rdict = merge_par_results(res)
    read_res = rdict['alt_reader']
    write_res = rdict['alt_writer']
    assert list_same(read_res, write_res), "Should have the same number of reads and writes, and all written values should be read in order"


async def test_timer_one_write():
    print("------------- Test timer on reader with a single delayed write ----------------")
    N = 10
    c = Channel('ch5')
    res = await Parallel(
        alt_timer(c.read, N=N),
        sleep_write_once(c.write))
    c.verify()
    rdict = merge_par_results(res)
    print(res)
    read_res = rdict['alt_timer']
    write_res = rdict['sleep_write_once']
    assert len(write_res) == 1, "Write_once should only write one message"
    assert len(read_res) == N, f"alt_timer should have returned {N} results, got {len(read_res)}"
    assert read_res.count('timeout') == N - 1, f"alt_timer should return {N- 1} timeouts"
    assert read_res.count(write_res[0]) == 1, f"alt_timer should return 1 {write_res[0]}"


def task_info(task):
    info = {
        # 'task' : task,
        'done' : task.done(),
        'cancelled' : task.cancelled(),
    }
    try:
        info['exception'] = task.exception()
    except asyncio.CancelledError:
        info['exception'] = "Was Cancelled"
    except asyncio.InvalidStateError:
        info['exception'] = "Not Done"
    return info


async def test_poison_alt():
    print("--------- checking for poison handling in alts ---- ")

    async with CSPTaskGroup(poison_shield=True) as wg:
        print("** Poison channel that read alt is waiting for, terminating the reader")
        ch = Channel("poison-tst1")
        reader = wg.spawn(alt_reader_newalt(ch.read))
        await ch.write('tst')
        await asyncio.sleep(0.3)
        await ch.poison()

    assert ch.verify(), "Channel state check"
    assert ch.poisoned, "Channel should be poisoned now"
    rinfo = task_info(reader)
    assert rinfo['done'], "Task should be done"
    assert rinfo['exception'] is None, "@process should have caught exception"

    async with CSPTaskGroup() as wg:
        print("** Poison channel that write alt is waiting for, terminating writer")
        ch = Channel("poison-tst2")
        wg.spawn(alt_writer(ch.write))
        await asyncio.sleep(0.3)
        await ch.poison()
    assert ch.verify(), "Channel state check"
    assert ch.poisoned, "Channel should be poisoned now"

    async with CSPTaskGroup() as wg:
        print("** Poison channel before letting the read alt enable on it")
        ch = Channel("poison-tst3")
        await ch.poison()
        wg.spawn(alt_reader_newalt(ch.read))
    assert ch.verify(), "Channel state check"
    assert ch.poisoned, "Channel should be poisoned now"

    async with CSPTaskGroup() as wg:
        print("** Poison channel before letting the read alt enable on it")
        ch = Channel("poison-tst4")
        await ch.poison()
        wg.spawn(alt_writer(ch.write))
    assert ch.verify(), "Channel state check"
    assert ch.poisoned, "Channel should be poisoned now"


async def run_tests():
    await test_alt_skip()
    await test_alt_single_reader_chan()
    await test_alt_single_reader_chan_awith()
    await test_alt_on_writer_and_reader()
    await test_timer_one_write()
    await test_poison_alt()


if __name__ == '__main__':
    handle_common_args()
    asyncio.run(run_tests())
