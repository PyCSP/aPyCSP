#!/usr/bin/env python3

from contextlib import contextmanager
import apycsp
from apycsp import chan_poisoncheck, _ChanOP, ChannelPoisonException

# experimental implementation tricks for aPyCSP

# ############################################################
#
# Make sure we can switch back to the original channel implementation
#
Channel_Orig = apycsp.Channel


def set_channel_orig():
    apycsp.Channel = Channel_Orig


# ############################################################
#
# Decorated read and write ops.
#

class Channel_W_DecoratorOps(apycsp.Channel):
    # TODO: adding this decorator adds about 0.7 microseconds to the op time _and_ it adds memory usage for
    # processes waiting on a channel (call/await/future stack)... (5092 vs 4179 bytes per proc in n_procs.py)
    # Can we improve it?
    @chan_poisoncheck
    async def _write(self, obj):
        wcmd = _ChanOP('write', obj)
        if len(self.wqueue) > 0 or len(self.rqueue) == 0:
            # a) somebody else is already waiting to write, so we're not going to
            #    change the situation any with this write. simply append ourselves and wait
            #    for somebody to wake us up with the result.
            # b) nobody is waiting for our write. (TODO: buffered channels)
            return await self._wait_for_op(self.wqueue, wcmd)
        # find matching read cmd.
        rcmd = self.rqueue.popleft()
        return self._rw_nowait(wcmd, rcmd)[0]

    @chan_poisoncheck
    async def _read(self):
        rcmd = _ChanOP('read', None)
        if len(self.rqueue) > 0 or len(self.wqueue) == 0:
            # readers ahead of us, or no writers
            return await self._wait_for_op(self.rqueue, rcmd)
        # find matching write cmd.
        wcmd = self.wqueue.popleft()
        return self._rw_nowait(wcmd, rcmd)[1]


def set_channel_rw_decorator():
    print("** Replacing asyncio.Channel with version with decorated read/writes")
    apycsp.Channel = Channel_W_DecoratorOps


# ############################################################
#
# Context manager.
#
# This appears to have similar execution time to the decorators, but the decorator is easier to spot.
# On the other hand, this can be used inside a method which could be more flexible for ALT poison checking...
# It uses about as much memory as the non-decorated version

class PoisonChecker:
    def __init__(self, chan):
        self.chan = chan

    def __enter__(self):
        if self.chan.poisoned:
            raise ChannelPoisonException()
        return self.chan

    def __exit__(self, *exc_details):
        if self.chan.poisoned:
            raise ChannelPoisonException()


class Channel_W_ContextMgrOps(apycsp.Channel):
    def __init__(self, name="", loop=None):
        super().__init__(name, loop)
        self.poisoncheck = PoisonChecker(self)

    # using context managers
    async def _write(self, obj):
        with self.poisoncheck:
            wcmd = _ChanOP('write', obj)
            if len(self.wqueue) > 0 or len(self.rqueue) == 0:
                return await self._wait_for_op(self.wqueue, wcmd)
            rcmd = self.rqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[0]

    async def _read(self):
        with self.poisoncheck:
            rcmd = _ChanOP('read', None)
            if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                return await self._wait_for_op(self.rqueue, rcmd)
            wcmd = self.wqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[1]


def set_channel_contextmgr():
    print("** Replacing asyncio.Channel with version with context manager object")
    apycsp.Channel = Channel_W_ContextMgrOps


# ############################################################
#
# Variaion of context manager using the channel itself.
# Mainly to experiment with overheads
#

class Channel_W_ContextMgrOps2(apycsp.Channel):
    # using context managers
    async def _write(self, obj):
        with self:
            wcmd = _ChanOP('write', obj)
            if len(self.wqueue) > 0 or len(self.rqueue) == 0:
                return await self._wait_for_op(self.wqueue, wcmd)
            rcmd = self.rqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[0]

    async def _read(self):
        with self:
            rcmd = _ChanOP('read', None)
            if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                return await self._wait_for_op(self.rqueue, rcmd)
            wcmd = self.wqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[1]

    # context manager for the channel checks for poison
    def __enter__(self):
        if self.poisoned:
            raise ChannelPoisonException()
        return self

    def __exit__(self, *exc_details):
        if self.poisoned:
            raise ChannelPoisonException()


def set_channel_contextmgr2():
    print("** Replacing asyncio.Channel with version with context manager on the channel")
    apycsp.Channel = Channel_W_ContextMgrOps2


# ############################################################
#
# Context manager using contextlib.contextmanager
#

@contextmanager
def chan_poisoncheck(chan):
    if chan.poisoned:
        raise ChannelPoisonException()
    yield chan
    if chan.poisoned:
        raise ChannelPoisonException()


class Channel_W_Contextlib_Manager(apycsp.Channel):
    # using context managers
    async def _write(self, obj):
        with chan_poisoncheck(self):
            wcmd = _ChanOP('write', obj)
            if len(self.wqueue) > 0 or len(self.rqueue) == 0:
                return await self._wait_for_op(self.wqueue, wcmd)
            rcmd = self.rqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[0]

    async def _read(self):
        with chan_poisoncheck(self):
            rcmd = _ChanOP('read', None)
            if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                return await self._wait_for_op(self.rqueue, rcmd)
            wcmd = self.wqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[1]


def set_channel_contextlib_manager():
    print("** Replacing asyncio.Channel with contextlib based contextmanager")
    apycsp.Channel = Channel_W_Contextlib_Manager
