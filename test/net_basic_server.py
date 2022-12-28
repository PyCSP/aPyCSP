#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio
# import sigpauser

args = common.handle_common_args([
    (("-p", "--port"), dict(help="specify port number (alternatively host:port) to bind server to", action="store", default="8890"))
])
common.handle_common_args()


@apycsp.process
async def writer(ch):
    i = 0
    while True:
        i += 1
        print("Server about to write", i)
        await ch.write(f"This is message {i}")


@apycsp.process
async def silent_writer(ch):
    while True:
        await ch.write(42)


async def serve_test():
    ch1 = apycsp.Channel('net_t1')
    ch2 = apycsp.Channel('net_t2')
    apycsp.net.register_channel(ch1, 'net_t1')
    apycsp.net.register_channel(ch2, 'net_t2')
    apycsp.Spawn(writer(ch1))
    apycsp.Spawn(silent_writer(ch2))
    serv = await apycsp.net.start_server(args.port)
    async with serv:
        await serv.serve_forever()
    await serv.close()
    await serv.wait_closed()


try:
    asyncio.run(serve_test())
except KeyboardInterrupt:
    print("Done")
