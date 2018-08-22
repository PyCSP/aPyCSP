#!/usr/bin/env python3
"""Core implementation of the aPyCSP library. See README.md for more information"""

import asyncio
import collections
import functools
import sys
#import inspect


# ******************** Core code ********************

class ChannelPoisonException(Exception): 
    pass

def process(func):
    """Annotates a coroutine as a process and takes care of poison propagation. """
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
    # NB: we need to await here as we need to check for exceptions. If we
    # just create a coroutine and return it directly, we will fail to
    # catch exceptions in the wrapper. 
    @functools.wraps(func)
    async def p_wrap(self, *args, **kwargs):
        try:
            if not self.poisoned:
                return await func(self, *args, **kwargs)
        finally:
            if self.poisoned:
                raise ChannelPoisonException()
    return p_wrap


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

# ******************** Base and simple guards (channel ends should inherit from a Guard) ********************
#

class Guard:
    """Base Guard class."""
    # JCSPSRC/src/com/quickstone/jcsp/lang/Guard.java
    def enable(self, alt):
        return (False, None)
    def disable(self, alt):
        return False

class Skip(Guard):
    # JCSPSRC/src/com/quickstone/jcsp/lang/Skip.java
    def enable(self, alt):
        return (True, None) #Thread.yield() in java version
    def disable(self, alt):
        return True

class Timer(Guard):
    def __init__(self, seconds):
        self.expired = False
        # TODO: to make it more general, allow 'alt' to be an op code queue? It wouldn't quite fit as enable() starts
        # the timer, so we'd need a timer per queued opcode in that case. 
        self.alt = None          
        self.seconds = seconds
        self.cb = None

    def enable(self, alt):
        self.alt = alt
        self.cb = asyncio.call_later(self.seconds, self.expire)
        return (False, None)

    def disable(self, alt):
        # TODO: is cb.cancel() enough to make sure expire is not called after this?
        self.cb.cancel() 
        self.alt = None
        
    async def expire(self):
        self.expired = True
        self.alt.schedule(self)


# ******************** Channels ********************

class ChannelEnd:
    """The channel ends are objects that wrap the Channel read()
    and write() methods, and adds methods for forwarding poison() calls. 
    The channel ends are used for implementing ALT semantics and guards. """
    def __init__(self, chan):
        self._chan = chan
    def channel(self):
        "Returns the channel that this channel end belongs to."
        return self._chan
    async def poison(self):
        return await self._chan.poison()

class PendingChanWriteGuard(Guard):
    """Used to store a pending write that will only be executed if 
    the this particular guard is ready to be executed and is selected. 
    """
    def __init__(self, chan, obj):
        self.chan = chan
        self.obj = obj
    def enable(self, alt):
        return self.chan.wenable(alt, self)
    def disable(self, alt):
        return self.chan.wdisable(alt)
    def __repr__(self):
        return f"<PendingChanWriteGuard for {self.chan.name}>"

class ChannelWriteEnd(ChannelEnd):
    """Write end of a Channel. This end cannot be used directly as a Guard as
    we need to implement a lazy/pending write that is only executed if the 
    write guards is selected in the ALT. The current solution is to 
    call ch.write.alt_pending_write(value) to get a PendingChanWriteGuard
    which is used as a write guard and will execute the write if selected. 
    """
    def __init__(self, chan):
        ChannelEnd.__init__(self, chan)
    async def __call__(self, val):
        return await self._chan._write(val)
    def __repr__(self):
        return "<ChannelWriteEnd wrapping %s>" % self._chan
    def alt_pending_write(self, obj):
        """Returns a pending write guard object that will only write if this guard 
        is selected by the ALT
        """
        return PendingChanWriteGuard(self._chan, obj)

class ChannelReadEnd(ChannelEnd, Guard):
    def __init__(self, chan):
        Guard.__init__(self)
        ChannelEnd.__init__(self, chan)
    async def __call__(self):
        return await self._chan._read()
    def enable(self, alt):
        return self._chan.renable(alt)
    def disable(self, alt):
        return self._chan.rdisable(alt)
    def __repr__(self):
        return "<ChannelReadEnd wrapping %s>" % self._chan
    # support async for ch.read: 
    if sys.version_info >= (3,7,0):
        print("Using 3.7 version of aiter")
        def __aiter__(self):
            return self
    else:
        async def __aiter__(self):
            return self
    async def __anext__(self):
        return await self._chan._read()

class _ChanOP:
    """Used to store channel cmd/ops for the op queues"""
    def __init__(self, cmd, obj, alt = None):
        self.cmd = cmd
        self.obj = obj
        self.fut = None # future is used for commands that have to wait
        self.alt = alt
    def __repr__(self):
        return f"<_ChanOP: {self.cmd}>"

    
class Channel:
    """CSP Channels for aPyCSP. This is a generic channel that can be used with multiple readers
    and writers. The channel ends also supports being used as read guards (read ends) and for 
    creating lazy/pending writes that be submitted as write guards in an ALT. 
    """
    def __init__(self, name="", loop=None):
        if loop == None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.name = name
        self.poisoned = False
        self.wqueue = collections.deque()  
        self.rqueue = collections.deque() 
        self.read = ChannelReadEnd(self)
        self.write = ChannelWriteEnd(self)

    def __repr__(self):
        return "<Channel {} wq {} rq {}>".format(self.name, len(self.wqueue), len(self.rqueue))

    def _wait_for_op(self, queue, op):
        """Used when we need to queue an operation and wait for its completion. 
        Returns a future we can wait for that will, upon completion, contain
        the result from the operation.
        """
        fut = self.loop.create_future()
        op.fut = fut
        queue.append(op)
        return fut

    def _rw_nowait(self, wcmd, rcmd):
        """Execute a 'read/write' and wakes up any futures. Returns the
        return value for (write, read).  
         NB: a _read ALT calling _rw_nowait should represent its own
        command as a normal 'read' instead of an ALT to avoid having
        an extra schedule() called on it. The same goes for a _write
        op.
        """
        obj = wcmd.obj
        if wcmd.fut:
            wcmd.fut.set_result(0)
        if rcmd.fut:
            rcmd.fut.set_result(obj)
        if wcmd.cmd == 'ALT':
            # Handle the alt semantics for a sleeping write ALT. 
            wcmd.alt.schedule(wcmd.wguard, 0)
        if rcmd.cmd == 'ALT':
            # Handle the alt semantics for a sleeping read ALT. 
            rcmd.alt.schedule(self.read, obj)
        return (0, obj)

    # TODO: moved the decorated versions of _read and _write to test/common_exp.py for easier
    # experimenting with alternative implementations.
    # This is currently the fastest version that uses the least amount of memory, but the context manager version
    # is almost as lean at an execution time cost closer to the decorator version.
    # TODO: consider how to solve poison checking for the ALT as well. 
    async def _read(self):
        try:
            if self.poisoned:
                return
            rcmd = _ChanOP('read', None)
            if len(self.rqueue) > 0 or len(self.wqueue) == 0:
                # readers ahead of us, or no writers
                return await self._wait_for_op(self.rqueue, rcmd)
            # find matching write cmd.
            wcmd = self.wqueue.popleft()
            return self._rw_nowait(wcmd, rcmd)[1]
        finally:
            if self.poisoned:
                raise ChannelPoisonException()
        
    async def _write(self, obj):
        try:
            if self.poisoned:
                return
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
        finally:
            if self.poisoned:
                raise ChannelPoisonException()

    async def poison(self):
        """Poison a channel and wake up all ops in the queues so they can catch the poison."""
        # This doesn't need to be an async method any longer, but we
        # keep it like this to simplify poisoning of remote channels.
        if self.poisoned:
            return
        def poison_queue(queue):
            while len(queue) > 0:
                op = queue.popleft()
                if op.fut:
                    op.fut.set_result(None)
        self.poisoned = True
        poison_queue(self.wqueue)
        poison_queue(self.rqueue)        


    def _remove_alt_from_pqueue(self, queue, alt):
        """Common method to remove an alt from the read or write queue"""
        # TODO: this is inefficient, but should be ok for now.
        # a slightly faster alternative might be to store a reference to the cmd in a dict
        # with the alt as key, and then use deque.remove(cmd).
        # an alt may have multiple channels, and a guard may be used by multiple alts, so
        # there is no easy place for a single cmd to be stored in either.
        # deque now supports del deq[something], and deq.remove(), but need to find the obj first.
        #print("......remove_alt_pq : ", queue, list(filter(lambda op: not(op.cmd == 'ALT' and op.alt == alt), queue)))
        # TODO: one option _could_ be to use an ordered dict (new dicts are ordered as well), but we would need to
        # have a unique key that can be used to cancel commands later (and remove the first entry when popping)
        # collections.OrderedDict() has a popitem() method..
        return collections.deque(filter(lambda op: not(op.cmd == 'ALT' and op.alt == alt), queue))

    # TODO: read and write alts needs poison check, but we need de-register guards properly before we
    # consider throwing an exception. 
    def renable(self, alt):
        """enable for the input/read end"""
        if len(self.rqueue) > 0 or len(self.wqueue) == 0:
            # reader ahead of us or no writers
            # The code is similar to _read(), and we
            # need to enter the ALT as a potential reader
            rcmd = _ChanOP('ALT', None, alt=alt)
            self.rqueue.append(rcmd)
            return (False, None)
        # We have a waiting writer that we can match up with, so we execute the read and return
        # the  read value as well as True for the guard.
        # make sure it's treated as a read to avoid having rw_nowait trying to call schedule
        rcmd = _ChanOP('read', None) 
        wcmd = self.wqueue.popleft()
        ret = self._rw_nowait(wcmd, rcmd)[1]
        return (True, ret)
    
    def rdisable(self, alt):
        """Removes the ALT from the reader queue"""
        self.rqueue = self._remove_alt_from_pqueue(self.rqueue, alt)

    def wenable(self, alt, pguard):
        """enable write guard"""
        if len(self.wqueue) > 0 or len(self.rqueue) == 0:
            # can't execute the write directly, so we queue the write guard
            wcmd = _ChanOP('ALT', pguard.obj, alt=alt)
            wcmd.wguard = pguard
            self.wqueue.append(wcmd)
            return (False, None)
        # make sure it's treated as a write without a sleeping future
        wcmd = _ChanOP('write', pguard.obj) 
        rcmd = self.rqueue.popleft()
        ret = self._rw_nowait(wcmd, rcmd)[0]
        return (True, ret)
        
    def wdisable(self, alt):
        """Removes the ALT from the writer queue"""
        self.wqueue = self._remove_alt_from_pqueue(self.wqueue, alt)
        

    # support async for channel:
    if sys.version_info >= (3,7,0):
        print("Using 3.7 version of aiter")
        def __aiter__(self):
            return self
    else:
        async def __aiter__(self):
            return self
    async def __anext__(self):
        return await self._read()
        

async def poisonChannel(ch):
    "Poisons a channel or a channel end"
    await ch.poison()
    

# TODO:
# - this could be an option on the normal channel.
# - buffer limit
# - ALT writes should be considered as successful and transformed into normal
#   writes if there is room in the buffer, otherwise, we will have to
#   consider them again when there is room. 
# - when write ops are retired, we need to consdier waking up alts and writes
#   that are sleeping on a write
class BufferedChannel(Channel):
    """Buffered Channel. """
    def __init__(self, name="", loop=None):
        super().__init__(name=name, loop=loop)

    @chan_poisoncheck
    async def _write(self, obj):
        wcmd = _ChanOP('write', obj)
        if len(self.wqueue) > 0 or len(self.rqueue) == 0:
            # a) somebody else is already waiting to write, so we're not going to
            #    change the situation any with this write.
            # b) nobody is waiting for our write.
            # The main difference with normal write: simply append a write op without a future and return to the user.
            self.wqueue.append(wcmd)
            return 0
        # find matching read cmd. 
        rcmd = self.rqueue.popleft()
        return self._rw_nowait(wcmd, rcmd)[0]

    
# ******************** ALT ********************
#
# This differs from the thread-based implementation in the following way:
# 1. guards are enabled, stopping on the first ready guard if any.
# 2. if the alt is waiting for a guard to go ready, the first guard to
#    switch to ready will immediately jump into the ALT and execute the necessary bits
#    to resolve and prepare operations (like read in a channel).
#    This is possible as there is no lock and we're running single-threaded code. 
#    This means that searching for guards in disableGuards is no longer necessary. 
# 3. disableGuards is simply cleanup code removing the ALT from the guards.
# This requires that all guard code is synchronous.
# 
# NB:
#
# - this implementation should be able to support multiple ALT readers
#   on a channel (the first one will be resolved)
# - as we're resolving everything in a synchronous function and no
#   longer allow multiple guards to go true at the same time, it
#   should be safe to allow ALT writers and ALT readers in the same
#   channel!
# - don't let anything yield while runnning enable, disable priselect.
#   NB: that would not let us run remote ALTs/Guards... but the reference implementation cannot
#   do this anyway (there is no callback for schedule()).


class Alternative:
    # States for the Alternative construct
    _ALT_INACTIVE = "inactive"
    _ALT_READY    = "ready"
    _ALT_ENABLING = "enabling"
    _ALT_WAITING  = "waiting"
    
    """Alternative. Selects from a list of guards."""
    def __init__(self, *guards):
        self.guards = guards
        self.state = self._ALT_INACTIVE
        self.enabled_guards = [] # list of guards we successfully enabled (and would need to disable on exit)
        self.wait_fut = None # wait future when we need to wait for any guard to complete
        self.loop = asyncio.get_event_loop()

    def _enableGuards(self):
        "Enable guards. Selects the first ready guard and stops, otherwise it will enable all guards."
        self.enabled_guards = [] # TODO: check and raise an error if the list was not already empty
        for g in self.guards:
            self.enabled_guards.append(g)
            enabled, ret = g.enable(self)
            if enabled:
                # Current guard is ready, so use this immediately (works for priSelect)
                self.state = self._ALT_READY
                return (g, ret)
        return (None, None)

    def _disableGuards(self):
        "Disables guards that we successfully entered in enableGuards."
        for g in self.enabled_guards:
            g.disable(self)
        self.enabled_guards = []

    async def select(self):
        return await self.priSelect()
    
    async def priSelect(self):
        # First, enable guards. 
        self.state = self._ALT_ENABLING
        g, ret = self._enableGuards()
        if g:
            # we found a guard in enableGuards
            self._disableGuards()
            self.state = self._ALT_INACTIVE
            return (g, ret)
        
        # No guard has been selected yet. Wait for one of the guards to become "ready".
        # The guards wake us up by calling schedule() on the alt (see Channel for example)
        self.state = self._ALT_WAITING
        self.wait_fut = self.loop.create_future()
        g, ret = await self.wait_fut
        # By this time, everything should be resolved and we have a selected guard
        # and a return value (possibly None). We have also disabled the guards.
        self.state = self._ALT_INACTIVE
        return (g, ret)
    
    def schedule(self, guard, ret):
        """A wake-up call to processes ALTing on guards controlled by this object.
        Called by the (self) selected guard."""
        if self.state != self._ALT_WAITING:
            # So far, this has only occurred with a single process that tries to alt on both the read and write end
            # of the same channel. In that case, the first guard is enabled but has to wait, and the second
            # guard matches up with the first guard. They are both in the same ALT which is now in an enabling phase.
            # If a wguard enter first, the rguard will remove the wguard (flagged as an ALT), match it with the
            # read (flagged as RD). rw_nowait will try to run schedule() on the wguard's ALT (the same ALT as the rguard's ALT)
            # which is still in the enabling phase.
            # We could get around this by checking if both ends reference the same ALT, but it would be more complicated code,
            # and (apart from rendesvouz with yourself) the semantics of reading and writing from the channel
            # is confusing. You could end up writing without observing the result (the read has, strictly speaking,
            # completed though). 
            msg = f"Error: running schedule on an ALT that was in state {self.state} instead of waiting."
            raise Exception(msg)
            #return
        # NB: It should be safe to set_result as long as we don't yield in it
        self.wait_fut.set_result((guard, ret))
        self._disableGuards()
        

    # Support for asynchronous context managers. Instead of the following:
    #    (g, ret) = ALT.select():
    # we can use this as an alternative: 
    #    async with ALT as (g, ret):
    #     ....
    # We may need to specify options to Alt if we want other options than priSelect
    async def __aenter__(self):
        return await self.select()

    async def __aexit__(self, exc_type, exc, tb):
        return None
