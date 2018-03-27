#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
CSP Channels. 

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""
import asyncio
import inspect
import functools
from .Guards import Guard

# ------------------------------------------------------------
# Some helper decorators, functions and classes.
#
def synchronized(func):
    """Decorator for creating java-like monitor functions. """
    # We just need to make sure we can correctly decorate both coroutines and ordinary methods and functions. 
    is_coroutine = inspect.iscoroutinefunction(func)
    #print(f"synchronzing {func}, is_coroutine={is_coroutine}")
    @functools.wraps(func)
    async def a_call(self, *args, **kwargs):
        #print("sync", is_coroutine, func, args, kwargs)
        with await self._cond:
            #print("sync", is_coroutine, func, args, kwargs, "got cond")
            if is_coroutine:
                return await func(self, *args, **kwargs)
            return func(self, *args, **kwargs)
    return a_call

def chan_poisoncheck(func):
    "Decorator for making sure that poisoned channels raise exceptions"
    # We just need to make sure we can correctly decorate both coroutines and ordinary methods and functions. 
    is_coroutine = inspect.iscoroutinefunction(func)
    #print(f"poisonchecking {func}, is_coroutine={is_coroutine}")
    @functools.wraps(func)
    async def _call(self, *args, **kwargs):
        if self.poisoned:
            raise ChannelPoisonException()
        try:
            if is_coroutine:
                return await func(self, *args, **kwargs)
            return func(self, *args, **kwargs)
        finally:
            if self.poisoned:
                raise ChannelPoisonException()
    return _call

async def poisonChannel(ch):
    "Poisons a channel or a channel end"
    await ch.poison()
    
class ChannelPoisonException(Exception): 
    pass
    
# ------------------------------------------------------------
# Channel Ends
#

class ChannelEnd(object):
    """The channel ends are objects that replace the Channel read()
    and write() methods, and adds methods for forwarding poison()
    and pending() calls. 

    NB: read() and write() are not forwarded! That could allow the
    channel ends to be confused with proper channels, which would
    defeat the purpose of the channel ends.
    
    Also, ALT is not supported by default (no enable() or disable()).
    You need the Guard version of the ChannelEnd to do that (see
    ChannelInputEndGuard)."""
    def __init__(self, chan):
        self._chan = chan
    def channel(self):
        "Returns the channel that this channel end belongs to."
        return self._chan
    # simply pass on most calls to the channel by default
    async def poison(self):
        return await self._chan.poison()
    def pending(self):
        return self._chan.pending()

class ChannelOutputEnd(ChannelEnd):
    def __init__(self, chan):
        ChannelEnd.__init__(self, chan)
    async def __call__(self, val):
        return await self._chan._write(val)
    def __repr__(self):
        return "<ChannelOutputEnd wrapping %s>" % self._chan

class ChannelInputEnd(ChannelEnd):
    def __init__(self, chan):
        ChannelEnd.__init__(self, chan)
    async def __call__(self):
        return await self._chan._read()
    def __repr__(self):
        return "<ChannelInputEnd wrapping %s>" % self._chan

class ChannelInputEndGuard(ChannelInputEnd, Guard):
    '''This Channel input end is used for channels that can be used as
    input guards.  The "enable" and "disable" calls will be passed on
    to the channel.

    The channel end inherits from "Guard", which is necessary for
    "Alternate" to accept it (TODO: type checking in alternate).
    Inheriting from "Guard" also means that it is clearer that this is
    how a channel can be used as a guard.

    This guard calls the input enable/disable methods in the channel
    (_ienable, _idisable).  It does NOT support the X2Any channels.
    '''
    def __init__(self, chan):
        ChannelInputEnd.__init__(self, chan)
    def __repr__(self):
        return "<ChannelInputEndWGuard wrapping %s>" % self._chan
    async def enable(self, guard):
        return await self._chan._ienable(guard)
    async def disable(self):
        return await self._chan._idisable()


# TODO: we could support ChannelOutput guards with the following semantics:
# - the guard is true if a reader has committed to a read() (and is blocked waiting)
# - only one end of the channel can be a guard (safely)
#   (if both ends should be used as guards, we might need to oracle process to resolve multiple Alt/guard offers)

# ------------------------------------------------------------
# Channels
#

class Channel(object):
    def __init__(self, name):
        self.name = name
        self.poisoned = False
        self.write = ChannelOutputEnd(self)
        self.read  = ChannelInputEnd(self)
    def _write(self, val):
        raise "default method"
    def _read(self):
        raise "default method"
    async def poison(self):
        self.poisoned = True

class BlackHoleChannel(Channel):
    def __init__(self, name=None):
        Channel.__init__(self, name)
    @chan_poisoncheck
    def _write(self, obj=None):
        pass
    @chan_poisoncheck
    def _read(self):
        raise "BlackHoleChannels are not readable"

class One2OneChannel(Channel):
    # Based on implementation of one-to-one channel: One2OneChannelImpl.java
    """
    NB:
    - the reading end of this channel may ALT on this channel
    - the writing end is committed (can not use ALT)
    """
    def __init__(self, name=None):
        Channel.__init__(self, name)
        self.read  = ChannelInputEndGuard(self)   # read can be used as an input guard.
        self.rwMonitor = asyncio.Condition()
        self._cond = self.rwMonitor  # TODO: cleaner sync
        self._pending = False        # For synhronization. True if a reader or writer has committed and waits for the other
        self.hold = None             # object transmitted through channel
        self._ialt = None            # to keep a reference back to the Alternative construct the channel is "enabled" in

    # A couple of points to be aware of with regards to read() and write():
    # - there are never more than one reader and one writer (since it's a one2one channel)
    #   so there is no third process that can enter and cause problems.
    #   (otherwise, somebody else could have entered the channel after, for instance
    #   the reader has signaled the writer and blocked on wait(), but before the
    #   writer has had the chance to wake up and re-aquire the lock/condition)
    # - since the _read and _write operations are synchronized, we generally have two cases:
    #   a) reader enters first, or b) writer enters first.
    # - Note to students: try to identify phases of _read() and _write() that can be labeled
    #   entry and exit protocol. 
    @synchronized
    @chan_poisoncheck
    async def _write(self, obj = None):
        #print("_write", obj)
        self.hold = obj
        if self._pending:
            #print("_write: got pending, about to notify rwmonitor")
            # reader entered first and is waiting for us.
            # start the exit protocol (set pending to False and notify the other end)
            self._pending = False
            self.rwMonitor.notify()
        else:
            #print("_write: no pending")
            # we entered first, tell reader that we are waiting
            self._pending = True
            if self._ialt != None:
                # The channel is enabled as an input guard, so do the wake-up-call. 
                await self._ialt.schedule()
        #print("_write: await rwMonitor.wait()")
        await self.rwMonitor.wait()

    @synchronized
    @chan_poisoncheck
    async def _read(self):
        #print("_read: kjdkfjdf")
        if self._pending:
            # writer entered first and is waiting for us
            # start the exit protocol (set pending to False and notify the other end)
            #print("_read: pending")
            self._pending = False
        else:
            # we entered first, tell writer that we are waiting
            #print("_read: should await rwMonitor")
            self._pending = True    
            await self.rwMonitor.wait()
        hold = self.hold            # grab a copy before waking up writer 
        self.rwMonitor.notify()
        return hold

    @synchronized
    async def poison(self):
        if self.poisoned:
            return
        self.poisoned = True
        self.rwMonitor.notify_all()
        if self._ialt:
            # also wake up any input guards.
            await self._ialt.schedule()   

    # ALT support
    @synchronized
    @chan_poisoncheck
    def _ienable(self, alt):
        """Turns on ALT selection for the channel. Returns true if the channel has a committed writer."""
        # NB: Alts will overwrite each other if both ends use ALT !!!
        if self._pending:
            # got a committed writer, tell the ALT construct
            return True
        self._ialt = alt
        return False

    @synchronized
    @chan_poisoncheck
    def _idisable(self):
        """Turns off ALT selection for the channel. Returns true if the channel has a committed writer."""
        self._ialt = None
        return self._pending

    @synchronized
    @chan_poisoncheck
    def pending(self):
        """Returns whether there is data pending on the channel (NB: strictly speaking,
        whether a reader or writer has committed)."""
        return self._pending

    
class Any2OneChannel(One2OneChannel):
    """Allows more than one writer to send to one reader. Supports ALT on the reader end."""
    def __init__(self, name=None):
        One2OneChannel.__init__(self, name)
        self.writerLock = asyncio.Lock()
    async def _write(self, obj = None):
        with await self.writerLock:  # ensure that only one writer attempts to write at any time
            return await super()._write(obj)
    
class One2AnyChannel(One2OneChannel):
    """Allows one writer to write to multiple readers. It does, however, not support ALT."""
    def __init__(self, name=None):
        One2OneChannel.__init__(self, name)
        self.read  = ChannelInputEnd(self)  # make sure ALT is not supported 
        self.readerLock = asyncio.Lock()
    async def _read(self):
        with await self.readerLock:  # ensure that only one reader attempts to read at any time
            return await super()._read()

class Any2AnyChannel(One2AnyChannel):
    def __init__(self, name=None):
        One2AnyChannel.__init__(self, name)
        self.writerLock = asyncio.Lock()
    async def _write(self, obj = None):
        with await self.writerLock:  # ensure that only one writer attempts to write at any time
            return await super()._write(obj)

# TODO: Robert
# TODO: could use Queue as well, but that's another level of threading locks. 
class FifoBuffer(object):
    """NB: This class is not thread-safe. It should be protected by the user."""
    def __init__(self, maxlen=10):
        self.maxlen = maxlen
        self.q = []

    def empty(self):
        return len(self.q) == 0

    def full(self):
        return len(self.q) == self.maxlen

    def put(self, obj):
        assert not self.full()
        self.q.append(obj)

    def get(self):
        assert not self.empty()
        return self.q.pop(0)

# NB/TODO:
# - The naming is different from JCSP, where a buffered channel is, for instance
#   One2OneChannelX.java

# TODO: Robert
class BufferedOne2OneChannel(Channel):
    def __init__(self, name=None, buffer=None, bufsize=10):
        Channel.__init__(self, name)
        if bufsize < 1:
            raise "Buffered Channels can not have a buffer with a size less than 1!"
        self.read  = ChannelInputEndGuard(self)   # allow ALT
        self.rwMonitor = asyncio.Condition()
        self._cond = self.rwMonitor               
        self._ialt = None
        if buffer is None:
            self.buffer = FifoBuffer(bufsize)
        else:
            self.buffer = buffer

    @synchronized
    @chan_poisoncheck
    async def _write(self, obj = None):
        # there will always be some space here since we block _after_ making the channel full,
        # forcing write to wait until a reader has removed at least one slot. 
        # write will not exit until there is at least one empty slot. 
        # (TODO: slightly confusing for people used to reader/writer problems in other systems?)
        self.buffer.put(obj)
        if self._ialt:
            await self._ialt.schedule()
        else:
            self.rwMonitor.notify()
        if self.buffer.full():
            # wait until the buffer is non-full
            while self.buffer.full():
                await self.rwMonitor.wait()

    @synchronized
    @chan_poisoncheck
    async def _read(self):
        if self.buffer.empty():
            while self.buffer.empty():
                if self.poisoned:
                    raise ChannelPoisonException(self)
                await self.rwMonitor.wait()
        # poisoning by the writer will also cause 
        # this end to wakeup, so check for poison again
        if self.poisoned:
            raise ChannelPoisonException(self)
        self.rwMonitor.notify()
        return self.buffer.get()

    @synchronized
    async def poison(self):
        if self.poisoned:
            return # 
        self.poisoned = True
        self.rwMonitor.notify_all()
        if self._ialt:
            # also wake up any input guards... (see notes in one2onechannel)
            self._ialt.schedule()

    @synchronized
    def _ienable(self, alt):
        """Turns on ALT selection for the channel. Returns true if the channel has 
        data that can be read, or if the channel has been poisoned."""
        if self.poisoned:
            return True
        if self.buffer.empty():
            self._ialt = alt
            return False
        return True

    # TODO: do a chan_poisoncheck instead? 
    @synchronized
    def _idisable(self):
        """Turns off ALT selection for the channel. Returns true if the channel 
        contains data that can be read, or if the channel has been poisoned."""
        self._ialt = None
        return self.poisoned or not self.buffer.empty()

    @synchronized
    @chan_poisoncheck
    def pending(self):
        return self.buffer.empty()

class BufferedAny2OneChannel(BufferedOne2OneChannel):
    """Allows more than one writer to send to one reader. Supports ALT on the reader end."""
    def __init__(self, name=None, buffer=None):
        BufferedOne2OneChannel.__init__(self, buffer)
        self.writerLock = asyncio.Lock()
    async def _write(self, obj = None):
        with await self.writerLock:  # ensure that only one writer attempts to write at any time
            return await super()._write(obj)

class BufferedOne2AnyChannel(BufferedOne2OneChannel):
    """Allows one writer to write to multiple readers. It does, however, not support ALT."""
    def __init__(self, name=None, buffer=None):
        BufferedOne2OneChannel.__init__(self, buffer)
        self.readerLock = asyncio.Lock()
        self.read  = ChannelInputEnd(self)  # make sure ALT is NOT supported 
    async def _read(self):
        with await self.readerLock:  # ensure that only one reader attempts to read at any time
            return await super()._read()
    
class BufferedAny2AnyChannel(BufferedOne2AnyChannel):
    def __init__(self, name=None, buffer=None):
        BufferedOne2AnyChannel.__init__(self, buffer)
        self.writerLock = asyncio.Lock()
    async def _write(self, obj = None):
        with await self.writerLock:  # ensure that only one writer attempts to write at any time
            return await super()._write(obj)
