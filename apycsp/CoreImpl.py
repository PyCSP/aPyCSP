#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
PyCSP implementation of the CSP Core functionality (Channels, Processes, PAR, ALT).

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""

import time
import asyncio
import types
from .Channels import *
import functools
import inspect

# The old pycsp implements this using an object of type Process to interface with threads.
# At the moment, we're managing with a simple decorator function. 
def process(func):
    @functools.wraps(func)
    async def proc_wrapped(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ChannelPoisonException as e:
            # Propagate poison to any channels and channelends passed as parameters to the process
            for ch in [x for x in args if isinstance(x, ChannelEnd) or isinstance(x, Channel)]:
                await ch.poison()
    return proc_wrapped

# TODO: should consider alternative naming of these functions. 
def run_CSP(*procs):
    """Runs the CSP processes in parallel (equivalent to a PAR)
    Intended to be used by the outer sequential program that starts running a CSP network. 
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(asyncio.gather(*procs))

def run_CSP_seq(*procs):
    """Runs the CSP processes in one by one (equivalent to a SEQ). 
    Intended to be used by the outer sequential program that starts running a CSP network. 
    """
    loop = asyncio.get_event_loop()
    return [loop.run_until_complete(p) for p in procs]

async def Parallel(*procs):
    return await asyncio.gather(*procs)

async def Sequence(*procs):
    return [await p for p in procs]

def Spawn(proc):
    """For running a process in the background. Actual execution is only
    possible as long as the event loop is running"""
    loop = asyncio.get_event_loop()
    return loop.create_task(proc)



# States for the Alternative construct
_ALT_INACTIVE = "inactive"
_ALT_READY    = "ready"
_ALT_ENABLING = "enabling"
_ALT_WAITING  = "waiting"

class Alternative(object):
    """Alternative. Selects from a list of guards."""
    def __init__(self, *guards):
        self.guards = guards
        self.selected = None
        self._altMonitor = asyncio.Condition() 
        self._cond = self._altMonitor # for @synchronized
        self.state = _ALT_INACTIVE
        
    @synchronized
    async def _enableGuards(self):
        "Enable guards. If any guard currently 'ready', select the first."
        for g in self.guards:
            if await g.enable(self):
                # Current guard is ready, so use this immediately (works for priSelect)
                self.selected = g
                self.state = _ALT_READY
                return
        self.selected = None

    @synchronized
    async def _disableGuards(self):
        "Disables guards in reverse order from _enableGuards()."
        if self.selected == None:
            for g in reversed(self.guards):
                if await g.disable():
                    self.selected = g
        else:
            # TODO: should perhaps check to see whether entire range was visited in "_enableGuards"
            for g in reversed(self.guards):
                await g.disable()

    async def select(self):
        return await self.priSelect()
    
    async def priSelect(self):
        # First, enable guards. 
        self.state = _ALT_ENABLING
        await self._enableGuards()
        with await self._altMonitor:
            if self.state == _ALT_ENABLING:
                # No guard has been selected yet. Equivalent to self.selected == None. 
                # Wait for one of the guards to become "ready".
                # The guards wake us up by calling schedule() on the alt (see One2OneChannel)
                self.state = _ALT_WAITING
                await self._altMonitor.wait()
                self.state = _ALT_READY   # assume we have selected one when woken up
        await self._disableGuards()
        self.state = _ALT_INACTIVE
        return self.selected
    
    @synchronized
    def schedule(self):
        """A wake-up call to processes ALTing on guards controlled by this object.
        Called by the guard."""
        if self.state == _ALT_ENABLING:
            # NB/TODO: why allow this? it complicates matters and is hardly likely to help much.
            # must be easier to use the same RLock around most of priSelect (as indicated in the function).
            # in that case, this should never happen since we keep the lock, and a guard should not
            # be allowed to release that lock in the enable() function..... 
            self.state = _ALT_READY
        elif self.state == _ALT_WAITING:
            self.state = _ALT_READY
            self._altMonitor.notify()

    # Support for asynchronous context managers. This lets us use this pattern as an alternative to
    # a = ALT.select(): 
    # async with ALT as a:
    #     ....
    # NB: we may need to specify options to Alt if we want other options than priSelect
    async def __aenter__(self):
        return await self.select()

    async def __aexit__(self, exc_type, exc, tb):
        # TODO: we might want to run some cleanups here.
        return None
