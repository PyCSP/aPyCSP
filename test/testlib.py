import common
import apycsp

# plugNplay: experimental version to pinpoint the PAR overhead
import asyncio
@process
async def ParDelta2_t(cin, cout1, cout2):
    l = asyncio.get_event_loop()
    #l = asyncio.get_event_loop()
    case = 10
    while True:
        t = await cin()
        # JCSP version uses a Par here, so we do the same.
        if case == 10:
            done, pending = await asyncio.wait([cout1(t), cout2(t)])
            [x.result() for x in done] # need to do this to catch exceptions
        elif case == 11:
            done, pending = await asyncio.wait([cout1(t)])
            [x.result() for x in done]
            done, pending = await asyncio.wait([cout2(t)])
            [x.result() for x in done]
        elif case == 15:
            # Doesn't work. run_until_complete is already running outside this scope.
            l.run_until_complete(asyncio.wait([cout1(t), cout2(t)]))
        elif case == 20:
            res = await asyncio.gather(cout1(t), cout2(t))
        elif case == 21:
            res = await asyncio.gather(cout1(t))
            res = await asyncio.gather(cout2(t))
        elif case == 30:
            await cout1(t)
            await cout2(t)
        else:
            raise Exception("Fooo")
        #print(res)

