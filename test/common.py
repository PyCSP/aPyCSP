#!/usr/bin/env python3
# -*- coding: latin-1 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

# trick to allow us to import pycsp without setting PYTHONPATH
import sys
sys.path.append("..")
import apycsp
import argparse
import asyncio

# Common arguments are added and handled here. The general outline for a program is to
# use common.handle_common_args() with a list of argument specs to add. 

argparser = argparse.ArgumentParser()
argparser.add_argument("-u", "--uvloop", help='use uvloop', action="store_const", const=True, default=False)

def handle_common_args(argspecs=[]):
    """argspecs is a list of arguments for argparser.add_argument, with 
    each item a tuple of (*args, **kwargs). 
    Returns the parsed args.
    """
    global args
    for spec in argspecs:
        argparser.add_argument(*spec[0], **spec[1])
    args = argparser.parse_args()
    if args.uvloop:
        # faster option for the event loop.  
        # https://magic.io/blog/uvloop-blazing-fast-python-networking/
        print("Using uvloop as an event loop")
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return args
    
