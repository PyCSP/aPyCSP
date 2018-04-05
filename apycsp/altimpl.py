#!/usr/bin/env python3

# experimental implementation of the queue concept. 

import asyncio
import collections
import functools
import inspect

class ChannelPoisonException(Exception): 
    pass

# Copied from the baseimpl
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

def chan_poisoncheck(func):
    "Decorator for making sure that poisoned channels raise exceptions"
    # We just need to make sure we can correctly decorate both coroutines and ordinary methods and functions. 
    @functools.wraps(func)
    async def p_wrap(self, *args, **kwargs):
        if self.poisoned:
            raise ChannelPoisonException()
        try:
            return await func(self, *args, **kwargs)
        finally:
            if self.poisoned:
                raise ChannelPoisonException()
    return p_wrap


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

# This is a generic channel object, 
class Channel:
    def __init__(self, name="", loop=None):
        if loop == None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.name = name
        self.poisoned = False
        self.wqueue = collections.deque()  
        self.rqueue = collections.deque() # could also contain "ALT" ops.
        self.read = ChannelInputEnd(self)
        self.write = ChannelOutputEnd(self)

    def _wait_for_op(self, queue, op):
        """Used when we need to queue an operation and wait for its completion. 
        Returns a future we can wait for that will, upon completion, contain
        the result from the operation.
        """
        fut = self.loop.create_future()
        op[-1] = fut
        queue.append(op)
        return fut

    def _rw_nowait(self, wcmd, rcmd):
        """Excecute a 'read/write' and wakes up any futures. Returns the return value for (write, read)"""
        obj = wcmd[1]
        if wcmd[-1]:
            wcmd[-1].set_result(0)
        if rcmd[-1]:
            rcmd[-1].set_result(obj)
        return (0, obj)

    if 0:
        # TODO: adding this decorator adds about a microsecond to the op time... Can we improve it? 
        @chan_poisoncheck
        async def _write(self, obj):
            wcmd = ['write', obj, None]  # The none is replaced with a future if we have to wait
            if len(self.wqueue) > 0 or len(self.rqueue) == 0:
                # a) somebody else is already waiting to write, so we're not going to
                #    change the situation any with this write. simply append ourselves and wait
                #    for somebody to wake us up with the result.
                # b) nobody is waiting for our write. (TODO: buffered channels)
                return await self._wait_for_op(self.wqueue, wcmd)
            # find matching read cmd. TODO: need to inspect for alts etc.
            # if the read _is_ an alt: don't run the rw_nowait, but instead
            # return a dummy reader object that will be returned by the alt. 
            # The reader object will then wake up the writer when it actually
            # reads from the channel.
            # Alternatively, an alt actually reads and returns both the guard and the
            # completed operation. Care must be taken to not complete multiple guards if we context switch.... 
            rcmd = self.rqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[0]

        
        @chan_poisoncheck
        async def _read(self):
            rcmd = ['read', None]
            if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                # readers ahead of us, or no writiers
                return await self._wait_for_op(self.rqueue, rcmd)
            # find matchin write cmd.
            wcmd = self.wqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[1]
    else:
        # For comparison: doing the same without decorators
        async def _write(self, obj):
            if self.poisoned:
                raise ChannelPoisonException()
            try:
                wcmd = ['write', obj, None]  # The none is replaced with a future if we have to wait
                if len(self.wqueue) > 0 or len(self.rqueue) == 0:
                    return await self._wait_for_op(self.wqueue, wcmd)
                rcmd = self.rqueue.popleft()
                return self._rw_nowait(wcmd, rcmd)[0]
            finally:
                if self.poisoned:
                    raise ChannelPoisonException()

        async def _read(self):
            if self.poisoned:
                raise ChannelPoisonException()
            try:
                rcmd = ['read', None]
                if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                    # readers ahead of us, or no writiers
                    return await self._wait_for_op(self.rqueue, rcmd)
                # find matchin write cmd.
                wcmd = self.wqueue.popleft()
                return self._rw_nowait(wcmd, rcmd)[1]
            finally:
                if self.poisoned:
                    raise ChannelPoisonException()
    

    async def poison(self):
        # TODO: this doesn't need to be an async method any longer, but we keep it like this
        # to make the interface compatible with the baseimpl.
        if self.poisoned:
            return
        self.poisoned = True
        #self.rwMonitor.notify_all()
        #if self._ialt:
        #    # also wake up any input guards.
        #    await self._ialt.schedule()
        def poison_queue(queue):
            while len(queue) > 0:
                op = queue.popleft()
                op[-1].set_result(None)
        poison_queue(self.wqueue)
        poison_queue(self.rqueue)
        
        

One2OneChannel = Channel
One2AnyChannel = Channel
Any2OneChannel = Channel
Any2AnyChannel = Channel


async def poisonChannel(ch):
    "Poisons a channel or a channel end"
    await ch.poison()
    
