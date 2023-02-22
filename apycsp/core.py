#!/usr/bin/env python3

"""
Core code
"""

import functools
import types
import asyncio


class PoisonException(Exception):
    """Used to interrupt processes accessing poisoned channels."""


# TODO: use_pwrap = False?  that way, optionally get  func() => wrapper,  await func() returns result?
def process(verbose_poison=False):
    """Decorator for creating process functions.
    Annotates a function as a process and takes care of insulating parents from accidental
    poison propagation.

    If the optional 'verbose_poison' parameter is true, the decorator will print
    a message when it captures the PoisonException after the process
    was poisoned.
    """
    def inner_dec(func):
        @functools.wraps(func)
        async def proc_wrapped(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except PoisonException:
                if verbose_poison:
                    print(f"Process poisoned: {proc_wrapped}({args=}, {kwargs=})")
        return proc_wrapped

    # Decorators with optional arguments are a bit tricky in Python.
    # 1) If the user did not specify an argument, the first argument will be the function to decorate.
    # 2) If the user specified an argument, the arguments are to the decorator.
    # In the first case, retturn a decorated function.
    # In the second case, return a decorator function that returns a decorated function.
    if isinstance(verbose_poison, (types.FunctionType, types.MethodType)):
        # Normal case, need to re-map verbose_poison to the default instead of a function,
        # or it will evaluate to True
        func = verbose_poison
        verbose_poison = False
        return inner_dec(func)
    return inner_dec


# pylint: disable-next=C0103
async def Parallel(*procs):
    """Used to run a set of processes concurrently.
    Takes a list of processes which are started.
    Waits for the processes to complete, and returns a list of return values from each process.
    """
    # TODO: asyncio.gather specifies that the results will be in the order of the provided coroutines.
    # Should this be the external expectation as well?
    # https://docs.python.org/3/library/asyncio-task.html
    return await asyncio.gather(*procs)


# pylint: disable-next=C0103
async def Sequence(*procs):
    """Runs and waits for each process or coroutine in sequence.
    The return values from each process are returned in the same order as the processes
    were specified.
    """
    return [await p for p in procs]


# Recent versions of Python added a warning in the asyncio documentation:
#
# - https://docs.python.org/3/library/asyncio-task.html#creating-tasks
#
# The problem is that asyncio only creates a weak reference to tasks,
# so if the caller of create_task does not store a strong reference to it,
# it might be removed by the GC. To reproduce, you can try something like:
#
# async def sometask():
#    # Wait for something.
#    await asyncio.get_running_loop().create_future()
#
# async def trigger():
#    asyncio.create_task(sometask())
#    await asyncio.sleep(0.1)   # let sometask have a chance to start up and wait for the future
#    gc.collect()
#
# asyncio.run(trigger())
#
# Note that waiting for asyncio.sleep does not trigger this as sleep
# (apparently) keeps a reference to the task. Waiting for a future exposes the
# issue though.
#
# The solution to this is to store a strong reference somewhere. I am not happy
# about this as it requires storing task lists in multiple places:
#
# - inside asyncio (weak ref)
# - inside apycsp (unless all responsibility is clearly explained, warned about and
#   delegated to the user of apycsp)
# - by the user of apycsp
#
# Making sure that all three are kept up to date and consistent adds complexity
# and could potentially lead to memory leaks or other bugs.
#
# For now, the solution is to store a reference here and let a done callback
# remove the reference.  This makes Spawn behave more as you would expect from
# firing off a background task.
#
# A flag is provided to turn this behaviour off, if desired.
#
# NB: The documentation for add_done_callback says
# "This method should only be used in low-level callback-based code."
# https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.add_done_callback
#

__spawned_procs = set()   # track spawned procs


# pylint: disable-next=C0103
def Spawn(proc, track_ref=True):
    """For running a process in the background. Actual execution is only
    possible as long as the event loop is running.

    If track_ref is True, stores a reference to the task to avoid accidental garbage
    collection of the task.
    For more information, check comments above the Spawn() source code.
    """
    loop = asyncio.get_running_loop()
    task = loop.create_task(proc)

    def removeit(task):
        """Debug"""
        print("Spawn-Removeit", task._state, task)
        __spawned_procs.discard(task)

    if track_ref:
        # Store a reference to the task and add a callback that will remove the reference when
        # the task completes.
        __spawned_procs.add(task)
        task.add_done_callback(__spawned_procs.discard)
        # task.add_done_callback(removeit)

    return task
