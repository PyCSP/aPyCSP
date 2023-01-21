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


# pylint: disable-next=C0103
def Spawn(proc):
    """For running a process in the background. Actual execution is only
    possible as long as the event loop is running."""
    loop = asyncio.get_running_loop()
    return loop.create_task(proc)
