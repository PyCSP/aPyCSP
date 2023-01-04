#!/usr/bin/env python3
"""
See description in net_commstime_server.py.
This is the client side that runs the actual benchmark.
"""

import time
import asyncio
import common
import os
import apycsp
import apycsp.net
from apycsp.plugNplay import Delta2, Prefix, Successor
from apycsp import Parallel, process

args = common.handle_common_args([
    (("-s", "--serv"), dict(help="specify server as host:port (use multiple times for multiple servers)", action="append", default=[]))
])


async def setup():
    """Sets up connections and returns a list of connections."""
    if len(args.serv) < 1:
        return [await apycsp.net.setup_client(can_serve=True)]

    lst = []
    for sp in args.serv:
        lst.append(await apycsp.net.setup_client(sp, can_serve=True))
    return lst


@process
async def consumer(cin):
    "Commstime consumer process"
    # N = 5000
    N = 500
    ts = time.time
    # Make sure everyting is running first
    t1 = ts()
    for i in range(10):
        await cin()
    t1 = ts()
    for _ in range(N):
        await cin()
    t2 = ts()
    dt = t2 - t1
    tchan = dt / (4 * N)
    print("DT = %f.\nTime per ch : %f/(4*%d) = %f s = %f us" %
          (dt, dt, N, tchan, tchan * 1000000))
    print("consumer done, posioning channel")
    await cin.poison()
    return tchan


async def CommsTimeBM(prefix, chan_lst):
    # Get access to remote channels.
    a, b, c, d = [await apycsp.net.get_channel_proxy(chname) for chname in chan_lst]

    print("Running commstime")
    rets = await Parallel(
        Prefix(c.read, a.write, prefixItem=0),    # initiator
        Delta2(a.read, b.write, d.write),         # forwarding to two
        Successor(b.read, c.write),               # feeding back to prefix
        consumer(d.read))                         # timing process
    return rets[-1]


async def run_commstime(N=5):
    prefix_short = str(os.getpid())
    start_ch = await apycsp.net.get_channel_proxy("start")
    reply_ch = apycsp.net.create_registered_channel(f"{prefix_short}-reply")

    for run_no in range(N):
        prefix = f"{prefix_short}-{run_no}"
        print("Preparing run", prefix, start_ch)
        await start_ch.write(dict(cmd="setup", prefix=prefix, reply_chname=reply_ch.name))
        ret = await reply_ch.read()
        # print('got ret', ret)

        await CommsTimeBM(prefix, ret['chan_lst'])

        await start_ch.write(dict(cmd="cleanup", prefix=prefix, reply_chname=reply_ch.name))
        await reply_ch.read()


async def run_client():
    await setup()
    await run_commstime()


asyncio.run(run_client())
print("NB: the channels are poisoned. This requires restarting the server to re-run")
