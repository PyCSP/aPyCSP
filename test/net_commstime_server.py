#!/usr/bin/env python3

"""Simple server example that hosts the channels used for CommsTime.
The CSP processes runs in the client.

The idea behind the example is that a client should be able to connect multiple
times.

To do this, the channels must be given unique names (assigned by adding a
prefix provided by the client). This uses two-way communication:
- A client begins to set up the experiment by sending 'setup' with a chosen prefix on the start channel.
- The server sets up the channel and returns the channel names by writing to a channel hosted in the client.
- The client runs the benchmark.
- The client signals that the benchmark is done by sending 'cleanup' on the start channel.
- The server cleans up / removes the channels.
- The server writes a return value to the client, signalling that it is safe to start again.

This example also shows how both the client and the sever chan host channels.

See the discussion in apycsp.net for deeper issues with network channels.
"""
import asyncio
import common
import apycsp
import apycsp.net
from apycsp import process

args = common.handle_common_args([
    (("-p", "--port"), dict(help="specify port number (alternatively host:port) to bind server to", action="store", default="8890"))
])


@process
async def setup_commstime_chans(start_ch):
    """Used to set up channels for commstime.
    Waits on the start_channel before it sets up the commstime channels.
    Writes on the complete channel when ready and goes back to waiting for a start message.
    """
    chnames = ['a', 'b', 'c', 'd']
    try:
        while True:
            cmd = await start_ch.read()
            if cmd['cmd'] == 'setup':
                print("Setting up channels for", cmd)
                chan_lst = [apycsp.net.create_registered_channel(cmd['prefix'] + '-' + n) for n in chnames]
                complete_ch = await apycsp.net.get_channel_proxy(cmd['reply_chname'])
                # print("Got remote reply channel", complete_ch)
                await complete_ch.write(dict(chan_lst=[ch.name for ch in chan_lst]))

            if cmd['cmd'] == 'cleanup':
                print("Cleaning up for", cmd)
                # Remove poisoned channels
                for ch in chan_lst:
                    apycsp.net.unregister_channel(ch.name)

                complete_ch = await apycsp.net.get_channel_proxy(cmd['reply_chname'])
                # See discussion at the top of asyncio.net. The client may terminate before the buffered 'ack' is
                # sent. It is possible to drain buffers to work around this, but the problem is deeper (semantics of channels
                # across lost connections).
                try:
                    await complete_ch.write(cmd)
                except ConnectionError as e:
                    print("Lost connection while writing reply for completed cleanup")
                    print(e)
                # asyncio.create_task(complete_ch.write(cmd))
    except Exception as e:
        print("Got exception in commstime managment loop", e)
        raise


async def serve_test():
    start_ch = apycsp.net.create_registered_channel("start")

    apycsp.Spawn(setup_commstime_chans(start_ch))

    serv = await apycsp.net.start_server(args.port)
    async with serv:
        await serv.serve_forever()
    await serv.close()
    await serv.wait_closed()


try:
    asyncio.run(serve_test())
except KeyboardInterrupt:
    print("Done")
