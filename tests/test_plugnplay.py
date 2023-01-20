#!/usr/bin/env python3

"""Testing the plugNplay module.
"""
import types
import asyncio
from apycsp import Channel, process, Parallel, Sequence
from apycsp.plugNplay import Identity, Prefix, Delta2, ParDelta2, SeqDelta2
from apycsp.plugNplay import Successor, SkipProcess, Mux2, poison_chans

# sometimes N is good enough.
# pylint: disable=invalid-name


@process(verbose_poison=True)
async def write_vals(vals, cout):
    """Write each value from the sequence vals out to cout, one by one"""
    for v in vals:
        await cout(v)
    print(f"write_vals done writing {len(vals)} messages")


@process
async def read_n(N, cin):
    """Read N values from cin and terminate, returning a list of the read values."""
    vals = [await cin() for _ in range(N)]
    print(f"read_vals done reading {len(vals)} messages")
    return vals


@process
async def drain(cin):
    """Reads from the channel until the channel is poisoned.
    Returns the messages.
    """
    # Interestingly, the following can't be done because list cannot take
    # an async generator. The second doesn't help as it still is an async generator.
    # return list(cin)
    # return list(v async for v in cin)
    return [v async for v in cin]


@process
async def write_vals_and_poison(vals, cout):
    """Write each value from the sequence vals out to cout, one by one.
    Then poison the channel."""
    for v in vals:
        await cout(v)
    print(f"write_vals_and_poison poisoning channnel {cout}")
    await cout.poison()


@process
async def read_n_and_poison(N, cin):
    """Read N values from cin and terminate, returning a list of the read values.
    Then poison the channel.
    """
    vals = [await cin() for _ in range(N)]
    print(f"read_n_and_poison poisoning channnel {cin} after {len(vals)} reads")
    await cin.poison()
    return vals


async def test_identity():
    """Test the Identity process."""
    print("\nTesting Identity")
    print("-------------------")
    N = 10
    vals = list(range(N))
    ch1 = Channel('ch1')
    ch2 = Channel('ch2')
    rets = await Parallel(
        # Try to write more than the reader needs
        Sequence(
            write_vals(vals, ch1.write),
            poison_chans(ch1)),
        Sequence(
            Identity(ch1.read, ch2.write),
            poison_chans(ch2)),
        # The reader should be able to poison the rest when it is satisfied
        drain(ch2.read)
    )
    print(rets)
    assert vals == rets[-1], f"Identity: write {vals} do not match read {rets[-1]}"


async def test_prefix():
    """Test the Prefix process
    It poisons the read end, which is the wrong end to apply poison, so it demonstrates
    a trick to make the poison propagate properly.
    """
    print("\nTest the Prefix process")
    print("-------------------")

    vals = list(range(10))
    ch1 = Channel('ch1')
    ch2 = Channel('ch2')
    rets = await Parallel(
        Sequence(
            write_vals(vals[1:], ch1.write),
            poison_chans(ch1)),
        Sequence(
            Prefix(ch1.read, ch2.write, vals[0]),
            poison_chans(ch2)),
        drain(ch2))
    assert rets[-1] == vals, "Should get the same values back as the ones written {vals} {rets[-1]}"


async def delta_tester(delta_proc):
    """Helper function to test the delta processes"""
    print("\nTesting the {delta_proc} process")
    print("-------------------")
    vals = list(range(10))
    ch1 = Channel('ch1')
    ch2 = Channel('ch2')
    ch3 = Channel('ch3')
    # Need to apply poison to kill the delta process.
    rets = await Parallel(
        write_vals_and_poison(vals, ch1.write),
        Sequence(
            delta_proc(ch1.read, ch2.write, ch3.write),
            poison_chans(ch2, ch3)),
        drain(ch2.read),
        drain(ch3.read))
    print(rets)
    assert rets[-1] == vals, "Should get the same values back as the ones written {vals} {rets[-1]}"
    assert rets[-2] == vals, "Should get the same values back as the ones written {vals} {rets[-2]}"

    # TODO: timing testing is harder. Considering letting each writer and reader timestamp before and
    # after each operation, pass it back here and then examine the timestamp traces to verify that
    # everything happens in the same order.


async def test_delta2():
    """Test the Delta2 process"""
    await delta_tester(Delta2)


async def test_par_delta2():
    """Test the ParDelta2 process"""
    await delta_tester(ParDelta2)


async def test_seq_delta2():
    """Test the SeqDelta2 process"""
    await delta_tester(SeqDelta2)


async def test_successor():
    """Test the Successor process."""
    print("\nTesting Successor")
    print("-------------------")
    vals = list(range(11))
    ch1 = Channel()
    ch2 = Channel()
    rets = await Parallel(
        write_vals_and_poison(vals[:-1], ch1.write),
        Successor(ch1.read, ch2.write),
        read_n(len(vals) - 1, ch2.read))
    assert rets[-1] == vals[1:], f"Should get values increased by one. Got {rets[-1]}"


async def test_mux2():
    "Test the Mux2 process"""
    def gen_vals(pid):
        return [(pid, v) for v in vals]

    print("\nTesting Mux2")
    print("-------------------")
    vals = list(range(10))
    ch1 = Channel('ch1')
    ch2 = Channel('ch2')
    ch3 = Channel('ch3')
    rets = await Parallel(
        Sequence(
            Parallel(
                write_vals(gen_vals(1), ch1.write),
                write_vals(gen_vals(2), ch2.write)),
            poison_chans(ch1)),
        Sequence(
            Mux2(ch1.read, ch2.read, ch3.write),
            poison_chans(ch2, ch3)),
        read_n(len(vals) * 2, ch3.read))
    print("Got from reader", rets[-1])
    rvals = sorted(rets[-1])
    expected = sorted(gen_vals(1) + gen_vals(2))
    assert rvals == expected, f"Expected to get all values sent from writer. Got {rets[-1]}"


async def test_skip():
    print("\nTesting Successor")
    print("-------------------")

    process_net = Sequence(SkipProcess())
    await process_net

    # Not much to test for the Skip process. Just check that it's there.
    # in apycsp, it's just an awaiable, so there's not that much to inspect.
    assert isinstance(process_net, types.CoroutineType)


if __name__ == "__main__":
    asyncio.run(test_identity())
    asyncio.run(test_prefix())
    asyncio.run(test_delta2())
    asyncio.run(test_par_delta2())
    asyncio.run(test_seq_delta2())
    asyncio.run(test_successor())
    asyncio.run(test_mux2())
    asyncio.run(test_skip())
