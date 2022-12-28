#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License).
"""
import time
import asyncio
from common import handle_common_args, avg
import apycsp
from apycsp import process, Parallel

args = handle_common_args()

# NB: necessary to support the channel patching we're doing in common/common_exp
Channel = apycsp.Channel
print("Running with channel type", Channel)


@process
async def writer(N, cout):
    for i in range(N):
        await cout(i)


@process
async def reader(N, cin):
    for _ in range(N):
        await cin()


@process
async def reader_verb(N, cin):
    for _ in range(N):
        v = await cin()
        print(v, end=" ")


async def setup_chan():
    N = 10
    ch = Channel('a')
    await Parallel(
        writer(N, ch.write),
        reader_verb(N, ch.read))
    return ch


# We're doing the timing inside the reader and writer procs to time the
# channel overhead without the process start/stop overhead.
# We add 10 write+reads as a warmup time and to make sure both are ready.
@process
async def writer_timed(N, cout, cres):
    for i in range(10):
        await cout(i)
    t1 = time.time()
    for i in range(N):
        await cout(i)
    await cres(t1)


@process
async def reader_timed(N, cin, cres):
    for _ in range(N + 10):
        await cin()
    t2 = time.time()
    await cres(t2)


@process
async def get_res(N, c1, c2, dts):
    t1 = await c1()
    t2 = await c2()
    dt_ms    = (t2 - t1) * 1000
    dt_op_us = (dt_ms / N) * 1000
    print(f"  DT    = {dt_ms:8.3f} ms  per op: {dt_op_us:8.3f} us")
    dts.append(dt_op_us)


async def run_timing(read_end, write_end):
    dts = []
    res1 = Channel()
    res2 = Channel()
    for i in range(100):
        N = 1000
        print(f"  Run {i}:", end="")
        await Parallel(
            writer_timed(N, write_end, res1.write),
            reader_timed(N, read_end, res2.write),
            get_res(N, res1.read, res2.read, dts))
    print(" -- min {:.3f} avg {:.3f} max {:.3f} ".format(min(dts), avg(dts), max(dts)))


async def run_test():
    c = await setup_chan()

    print("timing with channel ends")
    await run_timing(c.read, c.write)

    print("timing with _read and _write directly")
    await run_timing(c._read, c._write)


asyncio.run(run_test())
