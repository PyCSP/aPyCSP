#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

# trick to allow us to import pycsp without setting PYTHONPATH
import sys
import argparse
sys.path.append("..")
import common_exp      # noqa E402  -- suppress flake8 warning

# Common arguments are added and handled here. The general outline for a program is to
# use common.handle_common_args() with a list of argument specs to add.

argparser = argparse.ArgumentParser()
argparser.add_argument("-u", "--uvloop", help='use uvloop', action="store_const", const=True, default=False)
argparser.add_argument("-rw_deco", help='use decorators for read/write ops on channels', action='store_const', const=True, default=False)
argparser.add_argument("-rw_ctxt", help='use context manager for read/write ops on channels', action='store_const', const=True, default=False)
argparser.add_argument("-rw_ctxt2", help='use context manager in the channel for read/write ops on channels', action='store_const', const=True, default=False)


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
    if args.rw_deco:
        common_exp.set_channel_rw_decorator()
    if args.rw_ctxt:
        common_exp.set_channel_contextmgr()
    if args.rw_ctxt2:
        common_exp.set_channel_contextmgr2()
    return args


def avg(vals):
    "Returns the average of values"
    return sum(vals) / len(vals)
