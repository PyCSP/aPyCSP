#!/usr/bin/env python3
# -*- coding: latin-1 -*-
from common import *
from apycsp import *
from apycsp.plugNplay import *
import os
import psutil
import sys
import time

N_PROCS = 10 if len(sys.argv) < 2 else int(sys.argv[1])

@process
async def simple_proc(pid, checkin, cin):
    # check in
    await checkin(pid)
    # wait for poison
    while True:
        x = await cin()

@process
async def killer(chin, pch, nprocs):
    print("Killer waiting for the other procs to call in")
    for i in range(nprocs):
        x = await chin()
    print("Done, checking memory usage")
    p = psutil.Process(os.getpid())
    rss = p.memory_info().rss
    print(f"RSS now {rss}  {rss/(1024**2)}M")
    print("now poisioning")
    await pch.poison()

def run_n_procs(n):
    print(f"Running with {n} simple_procs")
    ch = Any2OneChannel()
    pch =  One2AnyChannel()
    t1 = time.time()
    tasks = [simple_proc(i, ch.write, pch.read) for i in range(N_PROCS)]
    tasks.append(killer(ch.read, pch, n))
    t2 = time.time()
    Parallel(*tasks)
    t3 = time.time()
    print("Creating tasks: {:10.3f} us".format(1_000_000 * (t2-t1)))
    print("Running  tasks: {:10.3f} us".format(1_000_000 * (t3-t2)))


run_n_procs(N_PROCS)
