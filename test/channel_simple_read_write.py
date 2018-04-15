#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License).
"""
from common import *
import apycsp
import time
from apycsp import Channel, process, run_CSP

args = handle_common_args()

@process
async def writer(N, cout):
    for i in range(N):
        await cout(i)
        
@process
async def reader(N, cin):
    for i in range(N):
        v = await cin()
        
@process
async def reader_verb(N, cin):
    for i in range(N):
        v = await cin()
        print(v, end=" ")

# We're doing the timing inside the reader and writer procs to time the
# channel overhead without the process start/stop overhead.
# We add 10 write+reads as a warmup time and to make sure both are ready. 
@process
async def writer_timed(N, cout):
    global t1
    for i in range(10):
        await cout(i)
    t1 = time.time()
    for i in range(N):
        await cout(i)

@process
async def reader_timed(N, cin):
    global t2
    for i in range(N+10):
        v = await cin()
    t2 = time.time()
        

N = 10
c = Channel('a')
run_CSP(writer(N, c.write),
        reader_verb(N, c.read))

def run_timing(read_end, write_end):
    dts = []
    for i in range(5):
        N = 1000
        print(f"Run {i}:", end="")
        #t1 = time.time()
        run_CSP(writer_timed(N, write_end),
                reader_timed(N, read_end))
        #t2 = time.time()
        dt_ms    = (t2-t1) * 1000
        dt_op_us = (dt_ms / N) * 1000
        print(f"  DT    = {dt_ms:8.3f} ms  per op: {dt_op_us:8.3f} us")
        dts.append(dt_op_us)
    print(" -- min {:.3f} avg {:.3f} max {:.3f} ".format(min(dts), avg(dts), max(dts)))
        

print("timing with channel ends")
run_timing(c.read, c.write)    

print("timing with _read and _write directly")
run_timing(c._read, c._write)    

