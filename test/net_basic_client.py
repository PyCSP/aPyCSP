#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio

loop = asyncio.get_event_loop()

apycsp.net.setup_client()
apycsp.net.send_message_sync({'op' : 'ping'})
apycsp.net.send_message_sync({'op' : 'print', 'args' : 'foo\bar'})


@apycsp.process
async def reader(ch):
    for i in range(10):
        print("About to read")
        ret = await ch.read()
        print(" - got message", ret)

rchan = apycsp.net.RemoteChan('net_t1')

loop.run_until_complete(reader(rchan))


