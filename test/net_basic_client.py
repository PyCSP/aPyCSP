#!/usr/bin/env python3


import time
import common
import apycsp
import apycsp.net
import asyncio

args = common.handle_common_args([
    (("-s", "--serv"), dict(help="specify server as host:port (use multiple times for multiple servers)", action="append", default=[]))
])


async def setup():
    """Sets up connections and returns a list of connections."""
    if len(args.serv) < 1:
        return [await apycsp.net.setup_client()]

    lst = []
    for sp in args.serv:
        lst.append(await apycsp.net.setup_client(sp))
    return lst


async def ping(conns):
    """Simple ping test to each of the provided connections"""
    for conn in conns:
        await conn.send_recv_cmd({'op' : 'ping'})
        await conn.send_recv_cmd({'op' : 'print', 'args' : 'foo\nbar'})


@apycsp.process
async def reader(ch):
    for _ in range(10):
        print("About to read")
        ret = await ch.read()
        print(" - got message", ret)


async def measure_rt(conns, print_hdr=True):
    """Measure ping roundtrip time over each of the provided connctions."""
    for conn in conns:
        if print_hdr:
            print("\n--------------------------- ")
            print("Measuring remote op roundtrip time", conn)
        N = 1000
        t1 = time.time()
        for _ in range(N):
            conn.send_recv_cmd({'op' : 'ping'})
        t2 = time.time()
        dt_ms = (t2 - t1) * 1000
        us_msg = 1000 * dt_ms / N
        print(f"  - sending {N} messages took {dt_ms} ms")
        print(f"  - us per message : {us_msg}")


async def measure_ch_read(conns, print_hdr=True):
    """Measure channel read time over each of the provided connections."""
    if print_hdr:
        print("\n--------------------------- ")
        print("Reading from remote channel")

    @apycsp.process
    async def _reader(rchan, N):
        tot = 0
        for _ in range(N):
            v = await rchan.read()
            tot += v
        if tot != 42 * N:
            print("Total not the expected value", tot, 42 * N)

    N = 1000
    t1 = time.time()
    rchan = await apycsp.net.get_channel_proxy('net_t2')
    await _reader(rchan, N)
    t2 = time.time()
    dt_ms = (t2 - t1) * 1000
    us_msg = 1000 * dt_ms / N
    print(f"  - read {N} messages took {dt_ms} ms")
    print(f"  - us per message : {us_msg}")


async def run_client():
    conns = await setup()
    print("**************************")
    print("Running ping test")
    print("**************************")
    await ping(conns)

    print("**************************")
    print("Simple read experiment")
    print("**************************")
    rchan1 = await apycsp.net.get_channel_proxy('net_t1')
    await reader(rchan1)

    print("**************************")
    print("More testing")
    print("**************************")
    for i in range(5):
        await measure_rt(conns, i == 0)
    for i in range(5):
        await measure_ch_read(conns, i == 0)


asyncio.run(run_client())
