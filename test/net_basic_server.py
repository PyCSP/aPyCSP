#!/usr/bin/env python3

import common
import apycsp
import apycsp.net
import asyncio

args = common.handle_common_args([
    (("-p", "--port"), dict(help="specify port number (alternatively host:port) to bind server to", action="store", default="8890"))
])
common.handle_common_args()

loop = asyncio.get_event_loop()
serv = apycsp.net.start_server(args.port)

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
