#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

  Prefix ---- a ---->  Delta2 -- d --> consume
   ^                      |
   |                      |
   b                      |
   |                      |
  Succ <------- c --------|

"""
import sys
import time
import cProfile
import pstats
import asyncio
import apycsp
from apycsp import process, Parallel, Sequence
from apycsp import plugNplay
from apycsp.plugNplay import Prefix, Successor, poison_chans
from apycsp.utils import handle_common_args

print("--------------------- Commstime --------------------")
handle_common_args()
Channel = apycsp.Channel    # in case command line arguments replaced the Channel def


@process
async def consumer(cin, run_no):
    "Commstime consumer process"
    N = 5000
    ts = time.time
    t1 = ts()
    await cin()
    t1 = ts()
    for _ in range(N):
        await cin()
    t2 = ts()
    dt = t2 - t1
    tchan = dt / (4 * N)
    tchan_us = tchan * 1_000_000
    print(f"Run {run_no} DT = {dt:.4f}.  Time per ch : {dt:.4f}/(4*{N}) = {tchan:.8f} s = {tchan_us:.4f} us")
    # print("consumer done, posioning channel")
    return tchan


# pylint: disable-next=redefined-outer-name, invalid-name
async def comms_time_bm(run_no, Delta2=plugNplay.Delta2):
    """Run the benchmark witht the provided Delta2 implementation (default=Delta2)"""
    a = Channel("a")
    b = Channel("b")
    c = Channel("c")
    d = Channel("d")

    rets = await Parallel(
        Prefix(c.read, a.write, prefixItem=0),    # initiator
        Delta2(a.read, b.write, d.write),         # forwarding to two
        Successor(b.read, c.write),               # feeding back to prefix
        Sequence(
            consumer(d.read, run_no),             # timing process
            poison_chans(a, b, c, d)
        ))
    return rets[-1][0]  # return the results from consumer


# pylint: disable-next=redefined-outer-name, invalid-name
def run_bm(Delta2=plugNplay.Delta2):
    "Run the benchmark a number of times to check variation in execution time"
    print(f"Running with Delta2 = {Delta2}")
    N_BM = 10
    tchans = []
    for i in range(N_BM):
        tchans.append(asyncio.run(comms_time_bm(i, Delta2)))
    t_min = 1_000_000 * min(tchans)
    t_avg = 1_000_000 * sum(tchans) / len(tchans)
    t_max = 1_000_000 * max(tchans)
    print(f"Min {t_min:7.3f}  Avg {t_avg:7.3f} Max {t_max:7.3f}")
    return (t_min, t_avg, t_max)


def run_cprofile():
    "Run commstime through cProfile"
    cProfile.run("commstime_bm()", 'commstime.prof')
    p = pstats.Stats('commstime.prof')
    p.strip_dirs().sort_stats('cumtime').print_stats()


tpd = run_bm(plugNplay.ParDelta2)
tsd = run_bm(plugNplay.SeqDelta2)
hdrs = ['    min', '    avg', '    max'] * 2
vals = tpd + tsd
print("For easier markdown tables:")
print("| " + " | ".join([" ".join(sys.argv)] + hdrs) + " |")
print("| " + " | ".join([" ".join(sys.argv)] + [f"{v:7.3f}" for v in vals]) + " |")
