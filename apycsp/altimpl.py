#!/usr/bin/env python3
"""Experimental implementation of the "VM" / CSP OP / opqueue concept. 

Instead of a complicated set of thread-like coroutines, we simplify
the implementation by taking advantage of two things:

a) we queue operations on channels as opcodes + data (and potentially
   futures that can be set when completing)

b) we take advantage of cooperative multitasking, executing without
   locks and knowing that we will not be preempted.

The channel and ALT implementations could then be implemented in a
less convoluted manner, should be easier to reason about and
understand, and it turns out the channels and processes are
significantly faster and use less memory than the other
implementation. We can also support multiple readers using ALT on the
same channel. It should be possible to use a similar trick to
implement ALT for writing on the channel as well.

We do have to change the semantics slightly though: 

- enable and disable need to be synchronous calls that cannot yield.
  They can, however, create couroutines and enter them in the event
  loop as well as setting the results of futures.

- disable no longer checks for ready guards, it's strickly for
  unrollig registration of the ALT on the guards.

- when a 'ready' condition is found, the channel end / guard is
  responsible for immediately executing the action and returning the
  result as well as the ready state. This can happen in enable(), but
  also in timers etc.

This simplifies another aspect: only one guard can become active at
the same time as we enforce resolving and immediately unrolling when
we notice the first ready guard.

TODO: more detailt descriptions later.
"""

import asyncio
import collections
import functools
import inspect


# ******************** Core code ********************

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
    # We just need to make sure we can correctly decorate both
    # coroutines and ordinary methods and functions.  NB: we need to
    # await here instead of optimizing the await away using a normal
    # def for p_wrap as we need to check for exceptions here. If we
    # just create a coroutine and return it directly, we will fail to
    # catch exceptions.
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

# ******************** Base guards (channel ends should inherit from a Guard) ********************
# 
# don't let anything yield while runnning enable, disable priselect.
# NB: what would not let us run remote ALTs... but the basecode cannot
# do this anyway (there is no callback for schedule()).

class Guard(object):
    # JCSPSRC/src/com/quickstone/jcsp/lang/Guard.java
    def enable(self, alt):
        return (False, None)
    def disable(self, alt):
        return False

class Skip(Guard):
    # JCSPSRC/src/com/quickstone/jcsp/lang/Skip.java
    def enable(self, alt):
        #Thread.yield() in java version
        return (True, None)
    def disable(self, alt):
        return True

class Timer(Guard):
    def __init__(self, seconds):
        self.expired = False
        self.alt = None
        self.seconds = seconds
        self.cb = None

    def enable(self, alt):
        self.alt = alt
        self.cb = asyncio.call_later(self.seconds, self.expire)
        return (False, None)

    def disable(self, alt):
        self.cb.cancel() # TODO: is this enough to make sure expire is not called after this?
        self.alt = None
        
    async def expire(self):
        self.expired = True
        self.alt.schedule(self)


# ******************** Channels ********************

class ChannelEnd(object):
    """The channel ends are objects that replace the Channel read()
    and write() methods, and adds methods for forwarding poison() calls. 
    Specific read/write channel ends are used for implementing ALT 
    semantics for the channel ends. """
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

class _ChanOP:
    """Used to store channel cmd/ops for the op queues"""
    def __init__(self, cmd, obj, alt = None):
        self.cmd = cmd
        self.obj = obj
        self.fut = None # future is used for commands that have to wait
        self.alt = alt
    def __repr__(self):
        return f"<_ChanOP: {self.cmd}>"
    
# TODO: this implementation could implement buffered channels with a simple twist:
# - the condition for suspending a write could be modified such that a
#   write will succeed even if multiple writes are already queued up.
# - ALT writes should be considered as successful and transformed into normal
#   writes if there is room in the buffer, otherwise, we will have to
#   consider them again when there is room. 
# - when write ops are retired, we need to consdier waking up alts and writes
#   that are sleeping on a write
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
        self.rqueue = collections.deque() # could also contain "ALT" ops.
        self.read = ChannelReadEnd(self)
        self.write = ChannelWriteEnd(self)

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
        """Excecute a 'read/write' and wakes up any futures. Returns the
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

    if 0:
        # TODO: adding this decorator adds about a microsecond to the op time... Can we improve it? 
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
                wcmd = _ChanOP('write', obj)
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
                rcmd = _ChanOP('read', None)
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
        """Poison a channel and wake up all ops in the queues so they can catch the poison."""
        # TODO: this doesn't need to be an async method any longer, but we keep it like this
        # to make the interface compatible with the baseimpl.
        if self.poisoned:
            return
        self.poisoned = True
        def poison_queue(queue):
            while len(queue) > 0:
                op = queue.popleft()
                if op.fut:
                    op.fut.set_result(None)
        poison_queue(self.wqueue)
        poison_queue(self.rqueue)        


    def _remove_alt_from_pqueue(self, queue, alt):
        """Common method to remove an alt from the read or write queue"""
        # TODO: this is inefficient, but should be ok for now.
        # a slightly faster alternative might be to store a reference to the cmd in a dict
        # with the alt as key, and then use deque.remove(cmd).
        # an alt may have multiple channels, and a guard may be used by multiple alts, so
        # there is no easy place for a single cmd to be stored in either. 
        nqueue = collections.deque()
        for op in queue:
            if not (op.cmd == 'ALT' and op.alt == alt):
                nqueue.append(op)
        return nqueue

    # TODO: read and write alts needs poison check. 
    def renable(self, alt):
        """enable for the input/read end"""
        if len(self.rqueue) > 0 or len(self.wqueue) == 0:
            # reader ahead of us or no writers
            # The code is similar to _read(), and we
            # need to enter the ALT as a potential reader
            rcmd = _ChanOP('ALT', None, alt=alt)
            self.rqueue.append(rcmd)
            return (False, None)
        # we have a waiting writer that we can match up with, so we execute the read and return
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
        
        
One2OneChannel = Channel
One2AnyChannel = Channel
Any2OneChannel = Channel
Any2AnyChannel = Channel


async def poisonChannel(ch):
    "Poisons a channel or a channel end"
    await ch.poison()
    

# ******************** ALT ********************


# States for the Alternative construct
_ALT_INACTIVE = "inactive"
_ALT_READY    = "ready"
_ALT_ENABLING = "enabling"
_ALT_WAITING  = "waiting"

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

class Alternative(object):
    """Alternative. Selects from a list of guards."""
    def __init__(self, *guards):
        self.guards = guards
        self.state = _ALT_INACTIVE
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
                self.state = _ALT_READY
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
        self.state = _ALT_ENABLING
        g, ret = self._enableGuards()
        if g:
            # we found a guard in enableGuards
            self._disableGuards()
            self.state = _ALT_INACTIVE
            return (g, ret)
        
        # No guard has been selected yet. Wait for one of the guards to become "ready".
        # The guards wake us up by calling schedule() on the alt (see Channel for example)
        self.state = _ALT_WAITING
        self.wait_fut = self.loop.create_future()
        g, ret = await self.wait_fut
        # By this time, everything should be resolved and we have a selected guard
        # and a return value (possibly None). We have also disabled the garuds.
        self.state = _ALT_INACTIVE
        return (g, ret)
    
    def schedule(self, guard, ret):
        """A wake-up call to processes ALTing on guards controlled by this object.
        Called by the guard."""
        if self.state != _ALT_WAITING:
            raise f"Error: running schedule on an ALT that was in state {self.state} instead of waiting."
        # NB: It should be safe to set_result as long as we don't yield in it
        self.wait_fut.set_result((guard, ret))
        self._disableGuards()
        

    # Support for asynchronous context managers. This lets us use this pattern as an alternative to
    # a = ALT.select(): 
    # async with ALT as a:
    #     ....
    # We may need to specify options to Alt if we want other options than priSelect
    async def __aenter__(self):
        return await self.select()

    async def __aexit__(self, exc_type, exc, tb):
        return None
