#!/usr/bin/env python3

# Based on the version from
# https://github.com/kevin-chalmers/cpp-csp/blob/master/demos/stressedalt.cpp
# https://www.researchgate.net/publication/315053019_Development_and_Evaluation_of_a_Modern_CCSP_Library

import common
import apycsp
from apycsp import *
import asyncio
import time

N_RUNS    = 10
N_SELECTS = 10000
N_CHANNELS = 10
N_PROCS_PER_CHAN = 1000

print("--------------------- Stressed Alt --------------------")
common.handle_common_args()

@process
async def stressed_writer(cout, writer_id):
    "Stressed alt writer"
    i = 0
    while True:
        #await cout((writer_id, i))
        await cout(writer_id)
        #i += 1


@process
async def stressed_reader(channels, writers_per_chan):
    print("Waiting 5 seconds for all writers to get going")
    await asyncio.sleep(5)
    print("- sleep done, reader ready")

    print(f"Setting up alt with {writers_per_chan} procs per channel and {len(channels)} channels.")
    print(f"Total writer procs : {writers_per_chan * len(channels)}")
    alt = Alternative(*[ch.read for ch in channels])
    
    print("Select using async with : ")
    for run in range(N_RUNS):
        t1 = time.time()
        for i in range(N_SELECTS):
            async with alt as (g, val):
                # the selected read operation is already executed, so we have the value already
                pass
        t2 = time.time()
        dt = t2-t1
        us_per_select = 1_000_000 * dt / N_SELECTS
        print(f"Run {run:2}, {N_SELECTS} iters, {us_per_select} us per select/iter")

    print("Select using alt.select() : ")
    for run in range(N_RUNS):
        t1 = time.time()
        for i in range(N_SELECTS):
            g, val = await alt.select()
            # the selected read operation is already executed, so we have the value already
        t2 = time.time()
        dt = t2-t1
        us_per_select = 1_000_000 * dt / N_SELECTS
        print(f"Run {run:2}, {N_SELECTS} iters, {us_per_select} us per select/iter")
        
    for ch in channels:
        await ch.poison()

        
def run_bm():
    chans = [Channel(f'ch {i}') for i in range(N_CHANNELS)]
    procs = []
    for cno, ch in enumerate(chans):
        for c_pid in range(N_PROCS_PER_CHAN):
            writer_id = (cno, c_pid)
            procs.append(stressed_writer(ch.write, writer_id))
    procs.append(stressed_reader(chans, N_PROCS_PER_CHAN))
    run_CSP(*procs)


run_bm()

