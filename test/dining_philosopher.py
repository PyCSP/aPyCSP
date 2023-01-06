#!/usr/env/python3

"""
Implementation of Dining Philosophers based on the description in Chapter 2.5 of:

   Communicating Sequential Processes C. A. R. Hoare

The solution in the book suggests adding a footman that limits access to the
table so that only 4 out of the 5 philosophers may enter at the same time.

This solution adds one more process: a state monitor for simple tracing.
Any process (philosopher, fork, footman) sends a message to the state updater
when they intend to do an action. The state monitor then prints out a line on
the screen, providing a trace of the events as they are intended
(not necessarily as they happen).

This makes the program longer, but it's useful for debugging and experimenting
with alternatives.
"""

import random
import asyncio
import itertools
from common import handle_common_args, CSPTaskGroup
from apycsp import process, Channel, Alternative, Parallel, Sequence

handle_common_args()

verbose_poison = True    # Whether processes should report when they are killed by poison


async def a_enumerate(seq, start=0):
    i = start
    async for val in seq:
        yield i, val
        i += 1


async def rwait(min_s, max_s):
    "Wait a random number of seconds between min_s and max_s"
    await asyncio.sleep(min_s + (max_s - min_s) * random.random())


async def report(chan_out, pid, state):
    """Utility function for making report slightly smaller"""
    await chan_out(dict(pid=pid, state=state))


@process(verbose_poison=verbose_poison)
async def update_state(cin, states):
    """
    The first message is a list of the initial state of each process.
    """
    # An alternative could be to receive the state as a first message, but that is
    # easily a bad idea as that places restriction on when other processes can start.
    states = states.copy()
    # Make room for last changed flag
    for k, v in states.items():
        states[k] = v + " "

    async for n, info in a_enumerate(cin):
        states[info['pid']] = info['state'] + "*"  # add a star to signify that this was the changed state

        if n % 10 == 0:
            print("------------", n)
            print("  ".join([pid for pid in states.keys()]))

        print(" ".join([s for s in states.values()]))

        # Clear last changed
        for k, v in states.items():
            states[k] = v[:-1] + " "


@process(verbose_poison=verbose_poison)
async def fork(pid, cin, state_info):
    """To pick up a fork, a philosopher sends a channel to the fork and then
    writes to the channel to:
    1) pick up the fork
    2) put down the fork
    """
    while True:
        # wait for fork grab
        await report(state_info, pid, 'wg')
        phil_hand = await cin()

        # wait for philosopher to pick up fork
        await report(state_info, pid, 'wu')
        await phil_hand()

        # wait for philosopher to put down fork
        await report(state_info, pid, 'wd')
        await phil_hand()


@process(verbose_poison=verbose_poison)
async def philosopher(pid, fm_enter, fm_leave, fork_left, fork_right, state_info, max_eats=-1):
    """
    """
    hleft  = Channel(f"phil-{pid}-left-hand")
    hright = Channel(f"phil-{pid}-right-hand")
    print(f"Phil {pid} got fl {fork_left._chan.name} fr {fork_right._chan.name}")

    async def up_fork(hand, fork, state):
        await rwait(0.3, 1)
        await report(state_info, pid, state)
        await fork(hand.read)
        await hand.write(pid)

    async def down_fork(hand, fork, state):
        await rwait(0.3, 1)
        await report(state_info, pid, state)
        await hand.write(pid)

    seq = range(0, max_eats)
    if max_eats < 0:
        seq = itertools.count()

    for n in seq:
        await report(state_info, pid, "sl")
        await rwait(2, 5)

        # Wait for admission to table
        await report(state_info, pid, "wt")   # wait for admission
        await fm_enter(pid)

        # Grab forks
        await up_fork(hleft, fork_left, state="gl")
        await up_fork(hright, fork_right, state="gr")

        # Eat
        await report(state_info, pid, "es")   # eat spaghetti
        await rwait(2, 5)

        # Drop forks
        await down_fork(hleft, fork_left, state="gl")
        await down_fork(hright, fork_right, state="gr")

        # Leave table
        await report(state_info, pid, "lt")
        await fm_leave(pid)
    await report(state_info, pid, "xx")
    print(f"Philosopher {pid} decided to go somewhere else")


@process(verbose_poison=verbose_poison)
async def footman(pid, ask_join, ask_leave, state_info):
    at_table = 0    # Number of philosophers at the table
    while True:
        await report(state_info, pid, f"a{at_table}")

        alt = Alternative(ask_join, ask_leave)
        if at_table == 4:
            # Table full enough, only accept leaving
            alt = Alternative(ask_leave)
        ch, _ = await alt.select()
        if ch == ask_join:
            at_table += 1
        elif ch == ask_leave:
            at_table -= 1
        else:
            print("WARNING, footman confused", ch)


@process
async def start_group(N=5, max_eats=3):
    state_info = Channel("state_info")
    ask_join = Channel("ask_join")
    ask_leave = Channel("ask_join")
    fork_ch = [Channel(f"fork_{i}") for i in range(N)]

    proc_ids = ['FM'] + [f'F{i}'for i in range(N)] + [f"P{i}" for i in range(N)]
    init_state = {pid : '--' for pid in proc_ids}
    poison_chans = [ask_join, ask_leave] + fork_ch

    # Use a taskgroup to make sure every process is finishing before returning
    async with CSPTaskGroup() as tg:
        tg.spawn(update_state(state_info.read, init_state))
        tg.spawn(footman("FM", ask_join.read, ask_leave.read, state_info.write))
        for i in range(N):
            tg.spawn(fork(f"F{i}", fork_ch[i].read, state_info.write))

        # Run philosophers and wait for them to complete
        await Parallel(*[
            philosopher(f"P{i}", ask_join.write, ask_leave.write, fork_ch[i].write, fork_ch[(i + 1) % N].write, state_info.write, max_eats)
            for i in range(N)
        ])
        print("Philosophers done")

        # Poison channels to processes. This demonstrates how poison propagation leads to the
        # state_info channel being poisoned as well.
        print("Poisoning channels:")
        for ch in poison_chans:
            print("- poisoning", ch.name)
            await ch.poison()


# Extra processes for the start_group version that uses Sequence and Parallel
@process
async def print_msg(msg):
    print(msg)


@process
async def apply_poison(chans):
    print("Poisoning channels:")
    for ch in chans:
        print("- poisoning", ch.name)
        await ch.poison()


@process
async def start_group_2(N=5, max_eats=3):
    """This does the same as start_group(), except it doesn't use a TaskGroup.
    This required a few more processes to do this cleanly.

    It also exposed another problem: sending some state as the _first_ message to
    update_state makes things difficult to compose unless we add another channel
    for that simple purpose. A simpler solution was just to pass the state
    as a parameter when creating the process.

    It looks shorter and simpler, but also moved some code out to other process functions.
    Some comments also disappeared.
    """
    state_info = Channel("state_info")
    ask_join = Channel("ask_join")
    ask_leave = Channel("ask_join")
    fork_ch = [Channel(f"fork_{i}") for i in range(N)]

    proc_ids = ['FM'] + [f'F{i}'for i in range(N)] + [f"P{i}" for i in range(N)]
    init_state = {pid : '--' for pid in proc_ids}
    poison_chans = [ask_join, ask_leave] + fork_ch

    await Parallel(
        update_state(state_info.read, init_state),
        footman("FM", ask_join.read, ask_leave.read, state_info.write),
        *[fork(f"F{i}", fork_ch[i].read, state_info.write) for i in range(N)],
        Sequence(
            Parallel(*[
                philosopher(f"P{i}", ask_join.write, ask_leave.write, fork_ch[i].write, fork_ch[(i + 1) % N].write, state_info.write, max_eats)
                for i in range(N)
            ]),
            print_msg("Philosophers done"),
            apply_poison(poison_chans)))


# asyncio.run(start_group())
asyncio.run(start_group_2())
