#!/usr/bin/env python3
import common
import apycsp
import apycsp.net
import asyncio
from apycsp import Channel

# Very simple server that only hosts the channels. The CSP processes run in the client(s)

args = common.handle_common_args([
    (("-p", "--port"), dict(help="specify port number (alternatively host:port) to bind server to", action="store", default="8890"))
])

loop = asyncio.get_event_loop()
serv = apycsp.net.start_server(args.port)

def serve_test():
    chnames = ['a', 'b', 'c', 'd']
    chans = [Channel(n) for n in chnames]
    for c in chans:
        apycsp.net.register_channel(c, c.name)
    #loop.create_task(writer(ch1))
    #loop.create_task(silent_writer(ch2))

serve_test()
    
try:
    loop.run_forever()
except KeyboardInterrupt:
    print("Done")

serv.close()
loop.run_until_complete(serv.wait_closed())
