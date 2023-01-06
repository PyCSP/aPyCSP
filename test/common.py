#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import argparse
import sys
import asyncio
sys.path.append("..")  # Trick to import pycsp without setting PYTHONPATH
from apycsp import Spawn

# Common arguments are added and handled here. The general outline for a program is to
# use common.handle_common_args() with a list of argument specs to add.

argparser = argparse.ArgumentParser()
argparser.add_argument("-u", "--uvloop", help='use uvloop', action="store_const", const=True, default=False)


def handle_common_args(argspecs=None):
    """argspecs is a list of arguments for argparser.add_argument, with
    each item a tuple of (*args, **kwargs).
    Returns the parsed args.
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
    def __init__(self):
        self.group = []

    def spawn(self, proc):
        handle = Spawn(proc)
        self.group.append(handle)
        return handle

    async def __aenter__(self):
        return self

    async def __aexit__(self, type, value, traceback):
        print("TaskGroup waiting for procs to finish")
        ret = await asyncio.gather(*self.group)
        print("TaskGroup done")
        return ret
