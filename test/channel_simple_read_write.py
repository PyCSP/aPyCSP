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
    (('-b', '--base'), dict(help="use base implementation instead of altimpl", action="store_true", default=False))
])
if args.base:
    print("Using base impl")
    from apycsp import One2OneChannel as Channel, process, run_CSP
else:
    print("Using altimpl")
    from apycsp.altimpl import Channel, process, run_CSP

    
@process
async def writer(N, cout):
    for i in range(N):
        await cout(i)

@process
async def reader_verb(N, cin):
    for i in range(N):
        v = await cin()
        print(v)
        
async def reader(N, cin):
    for i in range(N):
        v = await cin()

N = 10
c = Channel('a')
run_CSP(writer(N, c.write),
        reader_verb(N, c.read))

for i in range(5):
    N = 1000
    print(f"Run {i}:")
    t1 = time.time()
    run_CSP(writer(N, c.write),
            reader(N, c.read))
    t2 = time.time()
    dt_ms    = (t2-t1) * 1000
    dt_op_us = (dt_ms / N) * 1000
    print(f"  DT    = {dt_ms} ms")
    print(f"  DT/op = {dt_op_us} us")

