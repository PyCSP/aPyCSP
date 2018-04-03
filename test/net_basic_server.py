#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio

loop = asyncio.get_event_loop()
serv = apycsp.net.start_server()

@apycsp.process
async def writer(ch):
    i = 0
    while True:
        i += 1
        print("Server about to write", i)
        await ch.write(f"This is message {i}")

def serve_test():
    ch = apycsp.One2OneChannel('net_t1')
    apycsp.net.register_channel(ch, 'net_t1')
    loop.create_task(writer(ch))

serve_test()
    
try:
    loop.run_forever()
except KeyboardInterrupt:
    print("Done")

serv.close()
loop.run_until_complete(serv.wait_closed())
