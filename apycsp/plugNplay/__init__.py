#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
Contains common CSP processes such as Id, Delta, Prefix etc. 

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""

from apycsp import process, Channel, ChannelPoisonException, Alternative


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
async def Delta2(cin, cout1, cout2):
    # TODO: JCSP version sends the output in parallel. Should this be modified to do the same? 
    while True:
        t = await cin()
        await cout1(t)
        await cout2(t)

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
        c = await alt.priSelect()
        await cout(await c())
