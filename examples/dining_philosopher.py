#!/usr/bin/env python3

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

Interesting observation
-----------------------
Watching the trace, you can probably observe something interesting: a
philosopher may put down the left and then the right forks as the two events
immediately following each other. Initially, this might look like a
bug. Shouldn't the left fork report the next state before the philosopher is
able to drop the right fork?

The behaviour is correct, however. When the philosopher writes on the left
fork's channel, it does one of two things:
- waits for the read from the fork (if the fork is late offering to be put down)
- completes the matching of the philosopher's write with the fork's read,
  rendezvousing them in time.

When the write completes, they have both participated in the same read-write
event, and they are both allowed to continue executing.  _When_ each of them is
allowed to execute is up to the scheduler, however.  This means that, in
principle, the philosopher might be able to put down the other fork, leave the
table, sleep some, get back to the table and prepare for grabbing the forks
again before the left fork is allowed to report on switching states.

"""

import random
import asyncio
import itertools
from apycsp import process, Channel, Alternative, Parallel, Sequence
from apycsp.utils import handle_common_args, CSPTaskGroup

try:
    from rich import print
    uses_rich = True
except ModuleNotFoundError:
    uses_rich = False

handle_common_args()

verbose_poison = True    # Whether processes should report when they are killed by poison


async def a_enumerate(seq, start=0):
    """Iterate over a sequence that requires async for.
    """
    i = start
    async for val in seq:
        yield i, val
        i += 1


async def rwait(min_s, max_s):
    "Wait a random number of seconds between min_s and max_s"
    await asyncio.sleep(min_s + (max_s - min_s) * random.random())


def reporter(state_info, pid):
    """Shorthand for writing state + action(s).

    Retuns a function which takes ('state', *actions) as parameters.

    The function returns the result of the action (if one) or a
    list of results if it is not a single action.
    If no actions are specified, it will return an empty list.
    """
    async def func(state, *actions):
        # Send intended state
        await state_info((pid, state))
        # Now do actions.
        if len(actions) == 1:
            return await actions[0]
        else:
            return [await a for a in actions]
    return func


def pretty_state(state, was_changed):
    """Returns the name of the state, with a * attached
    if the state was changed. Adds an single space if not.

    If rich is installed: add colors."""
    pstate = state + " "
    if was_changed:
        pstate = state + "*"
    if not uses_rich:
        return pstate

    scols = {
        # forks
        'wg' : 'gray',
        'wu' : 'yellow',
        'wd' : 'blue',

        # philosophers
        'sl' : 'green',
        'wt' : 'yellow',
        'gl' : 'cyan',
        'gr' : 'bright_cyan',
        'es' : 'purple',
        'dl' : 'yellow',
        'dr' : 'bright_yellow',
        'xx' : 'white',  # done
    }
    if was_changed:
        return f"[red][bold]{pstate}[/bold][/red]"
    col = scols.get(state, 'white')
    return f"[{col}]{pstate}[/{col}]"


@process(verbose_poison=verbose_poison)
async def update_state(cin, states):
    """
    The first message is a list of the initial state of each process.
    """
    # An alternative could be to receive the state as a first message, but that is
    # easily a bad idea as that places restriction on when other processes can start.
    states = states.copy()

    async for n, (pid, state) in a_enumerate(cin):
        states[pid] = state

        if n % 10 == 0:
            # Print header
            print("----" * len(states), n)
            print("  ".join([p for p in states.keys()]))

        print(" ".join([pretty_state(s, p == pid) for p, s in states.items()]))


@process(verbose_poison=verbose_poison)
async def fork(pid, cin, state_info):
    """To pick up a fork, a philosopher sends a channel to the fork and then
    writes to the channel to:
    1) pick up the fork
    2) put down the fork
    """
    do = reporter(state_info, pid)

    while True:
        # wait for fork grab
        phil_hand = await do('wg', cin())

        # wait for philosopher to pick up fork
        await do('wu', phil_hand())

        # wait for philosopher to put down fork
        await do('wd', phil_hand())


@process(verbose_poison=verbose_poison)
async def philosopher(pid, fm_enter, fm_leave, fork_left, fork_right, state_info, max_eats=-1,
                      fork_waits=[0.1, 0.3], eat_waits=[0.5, 1.5], sleep_waits=[0.5, 1.5]):
    """
    """
    hleft  = Channel(f"phil-{pid}-left-hand")
    hright = Channel(f"phil-{pid}-right-hand")
    print(f"Phil {pid} got fl {fork_left._chan.name} fr {fork_right._chan.name}")

    async def up_fork(hand, fork):
        await rwait(*fork_waits)
        await fork(hand.read)
        await hand.write(pid)

    async def down_fork(hand, fork):
        await rwait(*fork_waits)
        await hand.write(pid)

    seq = range(0, max_eats)
    if max_eats < 0:
        seq = itertools.count()

    do = reporter(state_info, pid)

    for n in seq:
        # Sleep
        await do("sl", rwait(*sleep_waits))

        # Wait for admission to table
        await do("wt", fm_enter(pid))

        # Grab forks
        await do("gl", up_fork(hleft, fork_left))
        await do("gr", up_fork(hright, fork_right))

        # Eat spaghetti
        await do("es", rwait(*eat_waits))

        # Drop forks
        await do("dl", down_fork(hleft, fork_left))
        await do("dr", down_fork(hright, fork_right))

        # Leave table
        await do("lt", fm_leave(pid))
    await do("xx")
    print(f"Philosopher {pid} decided to go somewhere else")


@process(verbose_poison=verbose_poison)
async def footman(pid, ask_join, ask_leave, state_info):
    at_table = 0    # Number of philosophers at the table
    while True:
        await state_info((pid, f"a{at_table}"))

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


print("Running dining philosophers with a task group")
print("---------------------------------------------")
asyncio.run(start_group())

print("Running dining philosophers using Sequence and Parallel")
print("-------------------------------------------------------")
asyncio.run(start_group_2())
