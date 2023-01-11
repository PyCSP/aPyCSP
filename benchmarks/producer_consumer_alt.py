#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Producer-consumer,  but using multiple channels and sending tentative reads and writes to all of them using alt/select.
"""

import sys
import time
import asyncio
from common import handle_common_args, avg
import apycsp
from apycsp import process, Parallel, Alternative

print("--------------------- Producer/consumer --------------------")
args = handle_common_args([
    (("-profile",), dict(help="profile", action="store_const", const=True, default=False)),
])
Channel = apycsp.Channel    # in case command line arguments replaced the Channel def


@process
async def alting_producer(outputs, n_warm, n_runs):
    async def send(val):
        # need to create the guards and the alts every iteration
        guards = [out.alt_pending_write(val) for out in outputs]
        alt = Alternative(*guards)
        await alt.select()

    for i in range(n_warm):
        await send(i)
    for i in range(n_runs):
        await send(i)


@process
async def producer(outputs, n_warm, n_runs):
    for i in range(n_warm):
        await outputs[i % len(outputs)](i)
    for i in range(n_runs):
        await outputs[i % len(outputs)](i)


@process
async def consumer(inputs, n_warm, n_runs, run_no):
    alt = Alternative(*inputs)
    for i in range(n_warm):
        await alt.select()
    ts = time.time
    t1 = ts()
    for i in range(n_runs):
        await alt.select()
    t2 = ts()
    dt = (t2 - t1) * 1_000_000  # in microseconds
    per_rw = dt / n_runs
    # print(f"Run %d DT = {dt:f} us. Time per rw {per_rw:7.3f} us")
    return per_rw


async def run_bm(producer=producer, N_CHANNELS=5):
    N_BM = 10
    N_WARM = 100
    N_RUN   = 10_000
    channels = [Channel('prod/cons') for _ in range(N_CHANNELS)]
    ch_writes = [chan.write for chan in channels]
    ch_reads = [chan.read for chan in channels]

    res = []
    for i in range(N_BM):
        rets = await Parallel(
            producer(ch_writes, N_WARM, N_RUN),
            consumer(ch_reads, N_WARM, N_RUN, i))
        # print(rets)
        res.append(rets[-1])
    if nc == 1:
        print("Res with nchans, min, avg, max")
    args = " ".join(sys.argv[1:])
    print(f"| {producer.__name__}-consumer alt {args} | {N_CHANNELS} | {min(res):7.3f} | {avg(res):7.3f} |{max(res):7.3f} |")
    return rets


if __name__ == "__main__":
    for nc in [1, 2, 4, 6, 8, 10]:
        asyncio.run(run_bm(N_CHANNELS=nc))
    for nc in [1, 2, 4, 6, 8, 10]:
        asyncio.run(run_bm(producer=alting_producer, N_CHANNELS=nc))
    if args.profile:
        import cProfile
        cProfile.run("run_bm()", sort='tottime')
        print("Profile with alting producer")
        import cProfile
        cProfile.run("run_bm(producer=alting_producer)", sort='tottime')