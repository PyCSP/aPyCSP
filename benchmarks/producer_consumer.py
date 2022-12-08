#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from common import handle_common_args, avg
import apycsp
from apycsp import process, run_CSP

print("--------------------- Producer/consumer --------------------")
handle_common_args()
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
    print(f"Run %d DT = {dt:f} us. Time per rw {per_rw:7.3f} us")
    return per_rw


def run_bm():
    N_BM = 10
    N_WARM = 100
    N_RUN   = 10_000
    chan = Channel('prod/cons')

    res = []
    for i in range(N_BM):
        rets = run_CSP(producer(chan.write, N_WARM, N_RUN),
                       consumer(chan.read, N_WARM, N_RUN, i))
        # print(rets)
        res.append(rets[-1])
    print("Res with min, avg, max")
    print(f"| producer-consumer | {min(res):7.3f} | {avg(res):7.3f} |{max(res):7.3f} |")
    return rets


if __name__ == "__main__":
    run_bm()
    import cProfile
    cProfile.run("run_bm()", sort='tottime')
