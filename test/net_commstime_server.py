#!/usr/bin/env python3
import asyncio
import common
import apycsp
import apycsp.net
from apycsp import Channel

# Very simple server that only hosts the channels. The CSP processes run in the client(s)

args = common.handle_common_args([
    (("-p", "--port"), dict(help="specify port number (alternatively host:port) to bind server to", action="store", default="8890"))
])


async def serve_test():
    chnames = ['a', 'b', 'c', 'd']
    chans = [Channel(n) for n in chnames]
    for c in chans:
        apycsp.net.register_channel(c, c.name)

    serv = await apycsp.net.start_server(args.port)
    async with serv:
        await serv.serve_forever()
    await serv.close()
    await serv.wait_closed()


try:
    asyncio.run(serve_test())
except KeyboardInterrupt:
    print("Done")
