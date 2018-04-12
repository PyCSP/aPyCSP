#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License).
"""
from common import *
import apycsp
import time

args = handle_common_args([
    (('-l', '--lock'), dict(help="use lock implementation instead of core implementation", action="store_true", default=False))
])
if args.lock:
    print("Using lock implementation")
    from apycsp.lockimpl import One2OneChannel as Channel, process, run_CSP
else:
    print("Using core implementation")
    from apycsp import Channel, process, run_CSP

    
@process
async def writer(N, cout):
    for i in range(N):
        await cout(i)

@process
async def reader_verb(N, cin):
    for i in range(N):
        v = await cin()
        print(v, end=" ")
        
async def reader(N, cin):
    for i in range(N):
        v = await cin()

N = 10
c = Channel('a')
run_CSP(writer(N, c.write),
        reader_verb(N, c.read))
print("timing with channel ends")
for i in range(5):
    N = 1000
    print(f"Run {i}:", end="")
    t1 = time.time()
    run_CSP(writer(N, c.write),
            reader(N, c.read))
    t2 = time.time()
    dt_ms    = (t2-t1) * 1000
    dt_op_us = (dt_ms / N) * 1000
    print(f"  DT    = {dt_ms:8.3f} ms  per op: {dt_op_us:8.3f} us")

print("timing with _read and _write directly")
for i in range(5):
    N = 1000
    print(f"Run {i}:", end="")
    t1 = time.time()
    run_CSP(writer(N, c._write),
            reader(N, c._read))
    t2 = time.time()
    dt_ms    = (t2-t1) * 1000
    dt_op_us = (dt_ms / N) * 1000
    print(f"  DT    = {dt_ms:8.3f} ms  per op: {dt_op_us:8.3f} us")
    
