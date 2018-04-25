#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
Contains common CSP processes such as Id, Delta, Prefix etc. 

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""

from apycsp import process, Channel, ChannelPoisonException, Alternative, Parallel


@process
async def Identity(cin, cout):
    """Copies its input stream to its output stream, adding a one-place buffer
    to the stream."""
    while 1:
        t = await cin()
        await cout(t)

@process
async def Prefix(cin, cout, prefixItem=None):
    t = prefixItem
    while True:
        await cout(t)
        t = await cin()

@process
async def SeqDelta2(cin, cout1, cout2):
    # Sequential version TODO: JCSP version sends the output in parallel. 
    while True:
        t = await cin()
        await cout1(t)
        await cout2(t)

@process
async def ParDelta2(cin, cout1, cout2):
    while True:
        t = await cin()
        # JCSP version uses a Par here, so we do the same.
        # NB: cout1(t) generates a coroutine, which is equivalent with a CSP process.
        # This is therefore safe to do. 
        await Parallel(cout1(t),
                       cout2(t))

Delta2 = ParDelta2
        
@process
async def Successor(cin, cout):
    """Adds 1 to the value read on the input channel and outputs it on the output channel.
    Infinite loop.
    """
    while True:
        await cout(await cin()+1)

@process
async def SkipProcess():
    pass

@process
async def Mux2(cin1, cin2, cout):
    alt = Alternative(cin1, cin2)
    while True:
        ch, val = await alt.priSelect()
        await cout(val)
