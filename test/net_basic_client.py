#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio
import time

common.handle_common_args()

loop = asyncio.get_event_loop()

apycsp.net.setup_client()
apycsp.net.send_message_sync({'op' : 'ping'})
apycsp.net.send_message_sync({'op' : 'print', 'args' : 'foo\nbar'})


@apycsp.process
async def reader(ch):
    for i in range(10):
        print("About to read")
        ret = await ch.read()
        print(" - got message", ret)

rchan = apycsp.net.RemoteChan('net_t1')

print("Simple experiment")
loop.run_until_complete(reader(rchan))

def measure_rt(print_hdr=True):
    if print_hdr:
        print("\n--------------------------- ")
        print("Measuring remote op roundtrip time")
    N = 1000
    t1 = time.time()
    for i in range(N):
        apycsp.net.send_message_sync({'op' : 'ping'})
    t2 = time.time()
    dt_ms = (t2-t1) * 1000
    us_msg = 1000 * dt_ms / N
    print(f"  - sending {N} messages took {dt_ms} ms")
    print(f"  - us per message : {us_msg}")


def measure_ch_read(print_hdr=True):
    if print_hdr:
        print("\n--------------------------- ")
        print("Reading from remote channel")
    @apycsp.process
    async def reader(rchan, N):
        tot = 0
        for i in range(N):
            v = await rchan.read()
            tot += v
        if tot != 42 * N:
            print("Total not the expected value", tot, 42*N)

    N = 1000
    t1 = time.time()
    rchan = apycsp.net.RemoteChan('net_t2') 
    loop.run_until_complete(reader(rchan, N))
    t2 = time.time()
    dt_ms = (t2-t1) * 1000
    us_msg = 1000 * dt_ms / N
    print(f"  - read {N} messages took {dt_ms} ms")
    print(f"  - us per message : {us_msg}")


for i in range(5):
    measure_rt(i==0)
for i in range(5):
    measure_ch_read(i==0)

