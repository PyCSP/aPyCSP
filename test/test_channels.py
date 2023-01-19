#!/usr/bin/env python3

"""
NB: run the tests with pytest --asyncio-mode=auto

Testing a concurrent library has a few interesting challenges.

Challenge 1 - wait until a coroutine has blocked in the correct state
---------------------------------------------------------

It is easy to spawn a few writers that should queue up on a channel:
    writers = [Spawn(ch.write(i)) for i in range(N)]

The problem is that immediately after this statement, it is likely that the
writers haven't even started. Checking the state of the channel to verify N
writers queued up is not safe to do there. To make the loop scheduler pick the
writers and let them run to completion, the will need to yield.

Writing to a different channel, or signaling in any other way does not
guarantee that the coroutine will have managed to continue to the next event
(blocking on the channel) before the reader of the signal event manages to
check the channel.

At the moment, the solution is to sleep for a little bit. This could still lead
to race conditions, but at least it doesn't involve hacks such asinspecting the
_ready and _scheduled queues in the event loop.



"""
import asyncio
from apycsp import Channel, Spawn, Parallel, Sequence, PoisonException, process
from apycsp.plugNplay import Identity
from apycsp.utils import aenumerate


def check_event_procs():
    """Check base_events.py, _run_once()"""
    # pylint: disable=protected-access
    loop = asyncio.get_running_loop()
    # print(loop)
    # print(dir(loop))
    print('scheduled', loop._scheduled)
    print('ready', loop._ready)
    if len(loop._ready) > 0:
        print(loop._ready[0]._callback)


async def unsafe_wait_until_blocked(procs):
    """Placeholder until a better method for making sure the
    processes have blocked is found.
    One sleep per proc/coroutine should put this coroutine at the end of
    the run queue for every scheduled proc just to be on the safe side."""
    for _ in procs:
        await asyncio.sleep(0.1)


@process
async def print_proc(msg):
    "Simply prints the message"
    print(msg)


@process
async def n_writer(N, pid, cout, sleep=None):
    """Process that sends N messages, printing out status for every write.
    If sleep is not None, it will try to use that as a sleep interval between each operation.
    Will print a message if poisoned."""
    try:
        for i in range(1, N + 1):
            msg = f"p{pid}-m{i}/{N}"
            print("Writer sending", msg)
            await cout(msg)
            if sleep:
                await asyncio.sleep(sleep)
        print("Writer finished")
        return (pid, 'ok')
    except PoisonException as cp:
        print(f"writer {pid} got poisoned")
        raise cp


@process
async def n_reader(N, pid, cin, sleep=None):
    """Process that reads N messages, printing out status for every read + the received message.
    If sleep is not None, it will try to use that as a sleep interval between each operation.
    Will print a message if poisoned."""
    try:
        for i in range(1, N + 1):
            print(f"reader {pid} trying to read {i}/{N}")
            msg = await cin()
            print(f"reader {pid} got {msg} on read {i}/{N}")
            if sleep:
                await asyncio.sleep(sleep)
        print("Reader finished")
        return (pid, 'ok')
    except PoisonException as cp:
        print(f"reader {pid} got poisoned")
        raise cp


@process
async def inf_reader(pid, cin, sleep=None):
    """Process that reads from a channel until the channel is poisoned or closed."""
    async for i, msg in aenumerate(cin):
        print(f"reader {pid} got msg #{i}: {msg}")
        if sleep:
            await asyncio.sleep(sleep)
    print(f"reader {pid} terminating")


async def test_read_write(N=5):
    """Tests basic reading and writing to a channel with a series of N writers first writing
    to the channel, and then N readers reading.
    """
    print("Test simple channel read/write")
    ch = Channel()

    # ch.write is (apart from poison checking) effectively a @process, so, for this particular
    # test, reading and writing does not require creating process definitions.
    writers = [Spawn(ch.write(i)) for i in range(N)]

    await unsafe_wait_until_blocked(writers)
    ch.verify()
    assert ch.queue_len() == N, f"Queue should be length {N}, is length {ch.queue_len()}"
    # check_event_procs()

    vals = []
    for i in range(1, N + 1):
        vals.append(await ch.read())
        assert ch.queue_len() == N - i, f"After reading {i} messages, queue should be {N-i}, is {ch.queue_len()}"
        ch.verify()
    assert set(vals) == set(range(N)), f"Set of received values (in any order) should be the same as written {vals}"
    svals = [await wr for wr in writers]
    assert all(val == 0 for val in svals)


async def run_test_NW_writers_NR_readers(NW=1, NR=5, sleep=None):
    """Used for testing cases with varying cases of readers and writers to
    a single channel."""
    TOTAL_OPS = 4 * NR * NW
    N_WRITES = TOTAL_OPS // NW
    N_READS  = TOTAL_OPS // NR

    print(f"------ testing {NW} writers and {NR} readers, with a total of {TOTAL_OPS} operations, {sleep=} -----")
    ch = Channel()
    ch.verify()
    res = await Parallel(
        *[n_writer(N_WRITES, f"w-{rn}", ch.write, sleep) for rn in range(NW)],
        *[n_reader(N_READS,  f"r-{rn}", ch.read, sleep) for rn in range(NR)]
    )
    assert all(r[1] == 'ok' for r in res), "All results should be 'ok'"
    assert len(res) == NW + NR, "Number of ok results should be equal to number of readers+writers"
    print(res)
    ch.verify()


async def test_1_writer_5_readers():
    await run_test_NW_writers_NR_readers(1, 5)


async def test_5_writer_1_readers():
    await run_test_NW_writers_NR_readers(5, 1)


async def test_1_writer_1_readers():
    await run_test_NW_writers_NR_readers(1, 1)


async def test_5_writer_5_readers():
    await run_test_NW_writers_NR_readers(5, 5)


async def test_3_writer_3_readers_sleep():
    await run_test_NW_writers_NR_readers(3, 3, 0.1)


async def test_poison_writer():
    a = Channel("a")
    b = Channel("b")
    c = Channel("c")
    d = Channel("d")
    print("----------- testing channel poison from writer end-------")
    all_chans = [a, b, c, d]

    res = await Parallel(
        Sequence(
            n_writer(10, "writer", a.write),
            print_proc("Writer done"),
            a.poison()
        ),
        # The following processes should only terminate if poisoned
        Sequence(
            Identity(a.read, b.write),
            print_proc("Identity 1 done"),
            b.poison(),
        ),
        Sequence(
            Identity(b.read, c.write),
            print_proc("Identity 2 done"),
            c.poison(),
        ),
        Sequence(
            Identity(c.read, d.write),
            print_proc("Identity 3 done"),
            d.poison(),
        ),
        n_reader(100, "reader", d.read),
    )
    assert all(ch.verify() for ch in all_chans), "All channels should verify as ok"
    assert all(ch.poisoned for ch in all_chans), "All channels should be poisoned"
    pgroup = [r for r in res if r == [None, None, None]]
    # print(pgroup)
    assert len(pgroup) == 3, "Should have had 3 poisoned processes in a group"
    assert res.count(None) == 1, "Should have only 1 top level process that was poisoned"
    # look for the result from the Sequence with the writer
    w_res = [r for r in res if isinstance(r, (list, tuple))][0]
    assert w_res[0][0] == 'writer', "Should be the writer process"
    assert w_res[0][1] == 'ok', 'writer should be ok'
    assert w_res[1] is None, 'a.poison() should have returned None'


async def test_poison_reader():
    ch = Channel("poioson-read")
    print("----------- testing channel poison from reader end -------")

    res = await Parallel(
        # The following processes should only terminate if poisoned
        n_writer(100, "writer-1", ch.write),
        n_writer(100, "writer-2", ch.write),
        Sequence(
            n_reader(20, "reader", ch.read),
            ch.poison()
        ),
    )
    assert ch.verify(), "All channels should verify as ok"
    assert ch.poisoned, "All channels should be poisoned"
    assert res.count(None) == 2, "Should have had 2 poisoned processes"
    # look for the result from the Sequence with the reader
    w_res = [r for r in res if isinstance(r, (list, tuple))][0]
    assert w_res[0][0] == 'reader', "Should be the reader process"
    assert w_res[0][1] == 'ok', 'reader should be ok'
    assert w_res[1] is None, 'ch.poison() should have returned None'



async def test_read_until_channel_poisoned():
    """Tests the async for reading from channels"""
    ch = Channel("poison-read")
    print("----------- testing async for reading from channel -------")
    res = await Parallel(
        Sequence(
            n_writer(100, "writer-1", ch.write),
            ch.poison()
        ),
        # inf_reader('r-1', ch)
        inf_reader('r-1', ch.read)
    )
    print(res)
    

# TODO: channel.poison() should perhaps only insert a poison token on the channel.
# if writes queued:
# - writes should be poisoned from now.
# - reads should be allowed to drain the queue until empty, then poisoned.

if __name__ == "__main__":
    for name, fun in sorted([(name, fun) for name, fun in locals().items() if name.startswith("test_")]):
        print(name)
        asyncio.run(fun())
    asyncio.run(test_poison_reader())
