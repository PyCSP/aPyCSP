#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio
import argparse

aparser = argparse.ArgumentParser()
aparser.add_argument("-u", "--uvloop", help='use uvloop', action="store_const", const=True, default=False)
args = aparser.parse_args()

if args.uvloop:
    print("Using uvloop as an event loop")
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())




loop = asyncio.get_event_loop()
serv = apycsp.net.start_server()

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

def serve_test():
    ch1 = apycsp.One2OneChannel('net_t1')
    ch2 = apycsp.One2OneChannel('net_t2')
    apycsp.net.register_channel(ch1, 'net_t1')
    apycsp.net.register_channel(ch2, 'net_t2')
    loop.create_task(writer(ch1))
    loop.create_task(silent_writer(ch2))

serve_test()
    
try:
    loop.run_forever()
except KeyboardInterrupt:
    print("Done")

serv.close()
loop.run_until_complete(serv.wait_closed())
