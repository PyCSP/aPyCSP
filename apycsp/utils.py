#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2023 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import argparse
import asyncio
from apycsp import Spawn, PoisonException

# Common arguments are added and handled here. The general outline for a program is to
# use common.handle_common_args() with a list of argument specs to add.

argparser = argparse.ArgumentParser()
argparser.add_argument("-u", "--uvloop", help='use uvloop', action="store_const", const=True, default=False)


def handle_common_args(argspecs=None):
    """argspecs is a list of arguments for argparser.add_argument, with
    each item a tuple of (*args, **kwargs).
    Returns the parsed args.

    NB: Using argparser with pytest does not work particularly well.
    """
    if argspecs is None:
        argspecs = []
    for spec in argspecs:
        argparser.add_argument(*spec[0], **spec[1])
    args = argparser.parse_args()
    if args.uvloop:
        # faster option for the event loop.
        # https://magic.io/blog/uvloop-blazing-fast-python-networking/
        # https://github.com/MagicStack/uvloop
        print("Using uvloop as an event loop")
        import uvloop
        # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        uvloop.install()
    return args


def avg(vals):
    "Returns the average of values"
    return sum(vals) / len(vals)


class CSPTaskGroup:
    """Inspired by 3.11 TaskGroup.
    See https://docs.python.org/3/library/asyncio-task.html

    The main functionality here is to spawn processes, interact with them and
    make sure all of them have finished before stopping.

    In many cases, it is better to define processes that are executed using
    Sequence or Parallel.

    The semantics of providing sequence or parallel as methods here needs a bit of thought.
    - It may not be necessary as Parallel and Sequence can be used directly, and they already
      wait for the processes to finish.
    - It may be useful for spawning groups of processes that should run in the background,
      and then wait for all of them to finish.

    This is in the test/examples code as I have not thought about the semantics and the idea yet.
    I'm just using it for test-code at the moment.
    """
    def __init__(self, name=None, verbose=True, poison_shield=False):
        self.group = []
        self.verbose = verbose
        self.name = name
        if name is None:
            self.name = id(self)
        self.poisoned = False
        self.poison_shield = poison_shield

    def spawn(self, proc):
        """Spawns a process. The process is registered with the group, and
        the context will wait for this process before it exits."""
        handle = Spawn(proc)
        self.group.append(handle)
        return handle

    async def __aenter__(self):
        return self

    async def __aexit__(self, et, exc, traceback):
        if self.verbose:
            print(f"TaskGroup {self.name} waiting for procs to finish")
        if exc is not None:
            print("Caught exception", et, exc, traceback)
            if isinstance(exc, PoisonException) and self.poison_shield:
                self.poisoned = True
                return
            raise exc
        try:
            ret = await asyncio.gather(*self.group)
        except PoisonException as cp:
            if self.verbose:
                print("Caught exception while waiting for asyncio.gather", cp)
            self.poisoned = True
            if self.poison_shield:
                return
            raise cp
        if self.verbose:
            print(f"TaskGroup {self.name} done")
        return ret

    def __repr__(self):
        return f"<CSPTaskGroup, gsize={len(self.group)}>"


async def aenumerate(coroutine, start=0):
    """Coroutine version of enumerate that can be used in an async for"""
    async for val in coroutine:
        yield (start, val)
        start += 1
