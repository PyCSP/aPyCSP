#!/usr/bin/env python3
import time
import asyncio
import common
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
        return [await apycsp.net.setup_client()]

    lst = []
    for sp in args.serv:
        lst.append(await apycsp.net.setup_client(sp))
    return lst


@process
async def consumer(cin):
    "Commstime consumer process"
    # N = 5000
    N = 500
    ts = time.time
    t1 = ts()
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


async def CommsTimeBM():
    # Get access to remote channels.
    # TODO: we can only run this benchmark once before we need to restart the server side
    # as we will need to re_create the channels between each benchmark run (the first run will poison them).
    a = await apycsp.net.get_channel_proxy("a")
    b = await apycsp.net.get_channel_proxy("b")
    c = await apycsp.net.get_channel_proxy("c")
    d = await apycsp.net.get_channel_proxy("d")

    print("Running commstime")
    rets = await Parallel(
        Prefix(c.read, a.write, prefixItem=0),    # initiator
        Delta2(a.read, b.write, d.write),         # forwarding to two
        Successor(b.read, c.write),               # feeding back to prefix
        consumer(d.read))                         # timing process
    return rets[-1]


async def run_client():
    await setup()
    await CommsTimeBM()


asyncio.run(run_client())
print("NB: the channels are poisoned. This requires restarting the server to re-run")
