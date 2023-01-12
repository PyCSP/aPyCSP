#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
import psutil
import sys
import asyncio
import apycsp
from apycsp import process, Parallel
from apycsp.utils import handle_common_args
# NB: the Channel is not imported directly to support switching channel implementation in common_exp

args = handle_common_args([
    (["np"], dict(type=int, help='number of procs', default=10, nargs="?")),
])

N_PROCS = args.np  # 10 if len(sys.argv) < 2 else int(sys.argv[1])

# NB: necessary to support the channel patching we're doing in common/common_exp
Channel = apycsp.Channel
print("Running with channel type", Channel)


@process
async def simple_proc(pid, checkin, cin):
    # check in
    await checkin(pid)
    # wait for poison
    while True:
        await cin()


@process
async def killer(chin, pch, nprocs):
    print("Killer waiting for the other procs to call in")
    for _ in range(nprocs):
        await chin()
    print("Done, checking memory usage")
    p = psutil.Process(os.getpid())
    rss = p.memory_info().rss
    print(f"RSS now {rss}  {rss/(1024**2)}M")
    print("now poisioning")
    await pch.poison()
    return rss


async def run_n_procs(n):
    print(f"Running with {n} simple_procs")
    ch = Channel()
    pch = Channel()
    t1 = time.time()
    tasks = [simple_proc(i, ch.write, pch.read) for i in range(N_PROCS)]
    tasks.append(killer(ch.read, pch, n))
    t2 = time.time()
    res = await Parallel(*tasks)
    t3 = time.time()
    rss = res[-1]
    tcr = t2 - t1
    trun = t3 - t2
    print("Creating tasks: {:15.3f} us  {:15.3f} ms  {:15.9f} s".format(1_000_000 * tcr,  1000 * tcr,  tcr))
    print("Running  tasks: {:15.3f} us  {:15.3f} ms  {:15.9f} s".format(1_000_000 * trun, 1000 * trun, trun))
    print("{" + (f'"args" : {sys.argv[1:]}, "nprocs" : {n}, "t1" : {t1}, "t2" : {t2}, "t3" : {t3}, "tcr" : {tcr}, "trun" : {trun}, "rss" : {rss}') + "}")


asyncio.run(run_n_procs(N_PROCS))
