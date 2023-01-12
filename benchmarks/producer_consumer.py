#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import asyncio
import apycsp
from apycsp import process, Parallel
from apycsp.utils import handle_common_args, avg

print("--------------------- Producer/consumer --------------------")
args = handle_common_args([
    (("-profile",), dict(help="profile", action="store_const", const=True, default=False)),
])
Channel = apycsp.Channel    # in case command line arguments replaced the Channel def


@process
async def producer(cout, n_warm, n_runs):
    for i in range(n_warm):
        await cout(i)
    for i in range(n_runs):
        await cout(i)


@process
async def consumer(cin, n_warm, n_runs, run_no):
    for i in range(n_warm):
        await cin()
    ts = time.time
    t1 = ts()
    for i in range(n_runs):
        await cin()
    t2 = ts()
    dt = (t2 - t1) * 1_000_000  # in microseconds
    per_rw = dt / n_runs
    print(f"Run {run_no} DT = {dt:f} us. Time per rw {per_rw:7.3f} us")
    return per_rw


async def run_bm(use_ends=True):
    N_BM = 10
    N_WARM = 100
    N_RUN   = 10_000
    chan = Channel('prod/cons')

    if use_ends:
        cout = chan.write
        cin = chan.read
        bmtype = "channel ends"
    else:
        cout = chan._write
        cin = chan._read
        bmtype = "_read/_write"

    res = []
    for i in range(N_BM):
        rets = await Parallel(
            producer(cout, N_WARM, N_RUN),
            consumer(cin, N_WARM, N_RUN, i))
        # print(rets)
        res.append(rets[-1])
    print("Res with min, avg, max")
    nm_args = " ".join(sys.argv)
    print(f"| {bmtype} | {nm_args} | {min(res):7.3f} | {avg(res):7.3f} |{max(res):7.3f} |")
    return rets


if __name__ == "__main__":
    asyncio.run(run_bm())
    asyncio.run(run_bm(False))
    if args.profile:
        import cProfile
        cProfile.run("run_bm()", sort='tottime')
