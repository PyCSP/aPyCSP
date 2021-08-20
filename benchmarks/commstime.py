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

import os
import time
from common import handle_common_args
import apycsp
from apycsp import process, run_CSP
from apycsp.plugNplay import Delta2, Prefix, Successor

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
    print("Run %d DT = %f.  Time per ch : %f/(4*%d) = %f s = %f us" %
          (run_no, dt, dt, N, tchan, tchan * 1000000))
    # print("consumer done, posioning channel")
    await cin.poison()
    return tchan


def CommsTimeBM(run_no, Delta2=Delta2):
    # Create channels
    a = Channel("a")
    b = Channel("b")
    c = Channel("c")
    d = Channel("d")

    rets = run_CSP(Prefix(c.read, a.write, prefixItem=0),    # initiator
                   Delta2(a.read, b.write, d.write),         # forwarding to two
                   Successor(b.read, c.write),               # feeding back to prefix
                   consumer(d.read, run_no))                 # timing process
    return rets[-1]


def run_bm(Delta2=apycsp.plugNplay.Delta2):
    print(f"Running with Delta2 = {Delta2}")
    N_BM = 10
    tchans = []
    for i in range(N_BM):
        tchans.append(CommsTimeBM(i, Delta2))
    print("Min {:7.3f}  Avg {:7.3f} Max {:7.3f}".format(1_000_000 * min(tchans),
                                                        1_000_000 * sum(tchans) / len(tchans),
                                                        1_000_000 * max(tchans)))


run_bm(apycsp.plugNplay.ParDelta2)
run_bm(apycsp.plugNplay.SeqDelta2)
# A bit of a hack, but windows does not have uname()
try:
    os.uname()
except:
    print("Sleeping for a while to allow windows users to read benchmark results")
    time.sleep(15)


def run_cprofile():
    import cProfile
    import pstats
    cProfile.run("commstime_bm()", 'commstime.prof')
    p = pstats.Stats('commstime.prof')
    p.strip_dirs().sort_stats('cumtime').print_stats()
