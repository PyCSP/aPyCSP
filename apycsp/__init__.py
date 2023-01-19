#!/usr/bin/env python3
"""Core implementation of the aPyCSP library. See README.md for more information.


Poison applied to a channel should only influence any operations that try to
enter the channel _after_ the poison was applied, or the ones that were already
queued. Checking for poison on returning for an operation could cause a race
condition where, for instance, a reader is woken up with a value that was read,
but some other process manages to poison the channel before the reader is
scheduled to execute. When the reader gets to execute, it is wrongfully
poisoned.

TODO: changed behaviour: Do not try to propagate poison to other channels from
@process.  It's the wrong place to do this as it places responsibility of the
writer of the process to know something about the network around it.

"""

import collections
import functools
import types
from enum import Enum
import asyncio


# ******************** Core code ********************

class PoisonException(Exception):
    """Used to interrupt processes accessing poisoned channels."""


# TODO: use_pwrap = False?  that way, optionally get  func() => wrapper,  await func() returns result?
def process(verbose_poison=False):
    """Decorator for creating process functions.
    Annotates a function as a process and takes care of insulating parents from accidental
    poison propagation.

    If the optional 'verbose_poison' parameter is true, the decorator will print
    a message when it captures the PoisonException after the process
    was poisoned.
    """
    def inner_dec(func):
        @functools.wraps(func)
        async def proc_wrapped(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except PoisonException:
                if verbose_poison:
                    print(f"Process poisoned: {proc_wrapped}({args=}, {kwargs=})")
        return proc_wrapped

    # Decorators with optional arguments are a bit tricky in Python.
    # 1) If the user did not specify an argument, the first argument will be the function to decorate.
    # 2) If the user specified an argument, the arguments are to the decorator.
    # In the first case, retturn a decorated function.
    # In the second case, return a decorator function that returns a decorated function.
    if isinstance(verbose_poison, (types.FunctionType, types.MethodType)):
        # Normal case, need to re-map verbose_poison to the default instead of a function,
        # or it will evaluate to True
        func = verbose_poison
        verbose_poison = False
        return inner_dec(func)
    return inner_dec


# pylint: disable-next=C0103
async def Parallel(*procs):
    """Used to run a set of processes concurrently.
    Takes a list of processes which are started.
    Waits for the processes to complete, and returns a list of return values from each process.
    """
    # TODO: asyncio.gather specifies that the results will be in the order of the provided coroutines.
    # Should this be the external expectation as well?
    # https://docs.python.org/3/library/asyncio-task.html
    return await asyncio.gather(*procs)


# pylint: disable-next=C0103
async def Sequence(*procs):
    """Runs and waits for each process or coroutine in sequence.
    The return values from each process are returned in the same order as the processes
    were specified.
    """
    return [await p for p in procs]


# pylint: disable-next=C0103
def Spawn(proc):
    """For running a process in the background. Actual execution is only
    possible as long as the event loop is running."""
    loop = asyncio.get_running_loop()
    return loop.create_task(proc)


# ******************** Base and simple guards (channel ends should inherit from a Guard) ********************
#

class Guard:
    """Base Guard class."""
    # Based on JCSPSRC/src/com/quickstone/jcsp/lang/Guard.java
    def enable(self, alt):    # pylint: disable=W0613
        """Enable guard. Returns (True, return value) if a guards ready when enabled."""
        return (False, None)

    def disable(self, alt):    # pylint: disable=W0613
        """Disable guard."""
        return False


class Skip(Guard):
    """Based on JCSPSRC/src/com/quickstone/jcsp/lang/Skip.java"""
    def enable(self, alt):
        # Thread.yield() in java version
        return (True, None)

    def disable(self, alt):
        return True


class Timer(Guard):
    """Timer that enables a guard after a specified number of seconds.
    """
    def __init__(self, seconds):
        self.expired = False
        self.alt = None
        self.seconds = seconds
        self.timer = None
        self.loop = asyncio.get_running_loop()

    def enable(self, alt):
        self.expired = False
        self.alt = alt
        self.timer = self.loop.call_later(self.seconds, self._expire)
        return (False, None)

    def disable(self, alt):
        # See loop in asyncio/base_events.py. Cancelled coroutines are never called.
        self.timer.cancel()
        self.alt = None

    def _expire(self, ret=None):
        self.expired = True
        self.alt.schedule(self, ret)

    def __repr__(self):
        return f"<Timer ({self.seconds} S), exp: {self.expired}>"


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
        """Poisons the channel"""
        return await self._chan.poison()


class PendingChanWriteGuard(Guard):
    """Used to store a pending write that will only be executed if
    this particular guard is ready to be executed and is selected.
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
        return f"<ChannelWriteEnd wrapping {self._chan}>"

    def alt_pending_write(self, obj):
        """Returns a pending write guard object that will only write if this guard
        is selected by the ALT.
        """
        return PendingChanWriteGuard(self._chan, obj)


class ChannelReadEnd(ChannelEnd, Guard):
    """Read end of a channel.

    This can be used directly as a guard. As a guard, it will evaluate to ready
    if the read operation can complete (or woken up by a matching write operation).
    The return value from the guard will then be the value returned by the read.

    The channel end also supports being used as an iterator (async for ch.read)"
    """
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
        return f"<ChannelReadEnd wrapping {self._chan}>"

    # Support "async for ch.read"
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._chan._read()


class _ChanOpcode(Enum):
    READ = 'r'
    WRITE = 'w'


CH_READ = _ChanOpcode.READ
CH_WRITE = _ChanOpcode.WRITE


# pylint: disable-next=R0903
class _ChanOP:
    """Used to store channel cmd/ops for the op queues."""
    __slots__ = ['cmd', 'obj', 'fut', 'alt', 'wguard']    # reduce some overhead

    def __init__(self, cmd, obj, alt=None):
        self.cmd = cmd    # read or write
        self.obj = obj
        self.fut = None   # Future is used for commands that have to wait
        self.alt = alt    # None if normal read, reference to the ALT if tentative/alt
        self.wguard = None

    def __repr__(self):
        return f"<_ChanOP: {self.cmd}>"


class Channel:
    """CSP Channels for aPyCSP. This is a generic channel that can be used with multiple readers
    and writers. The channel ends also supports being used as read guards (read ends) and for
    creating lazy/pending writes that be submitted as write guards in an ALT.

    Note that the following rules apply:
    1) An operation that is submitted (read or write) is immediately paired with the first corresponding operation in the queue
    2) If no corresponding operation exists, the operation is added to the end of the queue

    Following from these rules, the queue can only be either empty or have a queue of a single
    type of operation (read or write).
    """
    def __init__(self, name="", loop=None):
        if loop is None:
            loop = asyncio.get_running_loop()
        self.loop = loop
        self.name = name
        self.poisoned = False
        self.queue = collections.deque()
        self.read = ChannelReadEnd(self)
        self.write = ChannelWriteEnd(self)

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name} ql={len(self.queue)} p={self.poisoned}>"

    def queue_len(self):
        """Mainly for verification. Number of queued operations."""
        return len(self.queue)

    def _wait_for_op(self, op):
        """Used when we need to queue an operation and wait for its completion.
        Returns a future we can wait for that will, upon completion, contain
        the result from the operation.
        """
        op.fut = self.loop.create_future()
        self.queue.append(op)
        return op.fut

    def _rw_nowait(self, wcmd, rcmd):
        """Execute a 'read/write' and wakes up any futures.
        Returns the return value for (write, read).
        NB: an ALT operation should submit a non-ALT here to avoid having
        an extra schedule() called on it.
        """
        obj = wcmd.obj
        if wcmd.fut:
            wcmd.fut.set_result(0)
        if rcmd.fut:
            rcmd.fut.set_result(obj)
        if wcmd.alt is not None:
            # Handle the alt semantics for a sleeping write ALT.
            wcmd.alt.schedule(wcmd.wguard, 0)
        if rcmd.alt is not None:
            # Handle the alt semantics for a sleeping read ALT.
            rcmd.alt.schedule(self.read, obj)
        return (0, obj)

    def _pop_matching(self, op):
        """Remove and return the first matching operation from the queue, or return None if not possible"""
        if len(self.queue) > 0 and self.queue[0].cmd == op:
            return self.queue.popleft()
        return None

    # NB: See docstring for the channels. The queue is either empty, or it has
    # a number of queued operations of a single type. There is never both a
    # read and a write in the same queue.
    async def _read(self):
        if self.poisoned:
            raise PoisonException
        rcmd = _ChanOP(CH_READ, None)
        if (wcmd := self._pop_matching(CH_WRITE)) is not None:
            # Found a match
            return self._rw_nowait(wcmd, rcmd)[1]

        # No write to match up with. Wait.
        return await self._wait_for_op(rcmd)

    async def _write(self, obj):
        if self.poisoned:
            raise PoisonException
        wcmd = _ChanOP(CH_WRITE, obj)
        if (rcmd := self._pop_matching(CH_READ)) is not None:
            return self._rw_nowait(wcmd, rcmd)[0]

        # No read to match up with. Wait.
        return await self._wait_for_op(wcmd)

    async def close(self):
        """At the moment, close and poison are identical.
        """
        return await self.poison()

    async def poison(self):
        """Poison a channel and wake up all ops in the queues so they can catch the poison."""
        # This doesn't need to be an async method any longer, but we
        # keep it like this to simplify poisoning of remote channels.

        if self.poisoned:
            return  # already poisoned

        # Cancel any operations in the queue
        while len(self.queue) > 0:
            op = self.queue.popleft()
            if op.fut:
                # op.fut.set_result(None)
                op.fut.set_exception(PoisonException("poisoned while sleeping/waiting for op"))
            if op.alt:
                op.alt.poison(self)

        self.poisoned = True

    def _remove_alt_from_queue(self, alt):
        """Remove an alt from the queue."""
        # TODO: this is inefficient, but should be ok for now.
        # Since a user could, technically, submit more than one operation to the same queue with an alt, it is
        # necessary to support removing more than one operation on the same alt .
        self.queue = collections.deque(filter(lambda op: op.alt != alt, self.queue))

    def renable(self, alt):
        """enable for the input/read end"""
        if self.poisoned:
            raise PoisonException(f"renable on channel {self} {alt=}")

        rcmd = _ChanOP(CH_READ, None)
        if (wcmd := self._pop_matching(CH_WRITE)) is not None:
            # Found a match
            ret = self._rw_nowait(wcmd, rcmd)[1]
            return (True, ret)

        # Can't match the operation on the other queue, so it must be queued.
        rcmd.alt = alt
        self.queue.append(rcmd)
        return (False, None)

    def rdisable(self, alt):
        """Removes the ALT from the queue."""
        self._remove_alt_from_queue(alt)

    def wenable(self, alt, pguard):
        """Enable write guard."""
        if self.poisoned:
            raise PoisonException(f"wenable on channel {self} {alt=} {pguard=}")

        wcmd = _ChanOP(CH_WRITE, pguard.obj)
        if (rcmd := self._pop_matching(CH_READ)) is not None:
            # Make sure it's treated as a write without a sleeping future.
            ret = self._rw_nowait(wcmd, rcmd)[0]
            return (True, ret)

        # Can't execute the write directly. Queue the write guard.
        wcmd.alt = alt
        wcmd.wguard = pguard
        self.queue.append(wcmd)
        return (False, None)

    def wdisable(self, alt):
        """Removes the ALT from the queue."""
        self._remove_alt_from_queue(alt)

    # Support iteration over channel to read from it (async for):
    def __aiter__(self):
        return self

    async def __anext__(self):
        """Instead of raising poison, let the loop terminate normally.
        Emulate more of the channel close() semantics.
        """
        if self.poisoned:
            raise StopAsyncIteration
        try:
            return await self._read()
        except PoisonException:
            # The iterator interface should not terminate using PoisonException
            raise StopAsyncIteration

    def verify(self):
        """Checks the state of the channel using assert."""
        if self.poisoned:
            assert len(self.queue) == 0, "Poisoned channels should never have queued messages"

        assert len(self.queue) == 0 or all(x.cmd == self.queue[0].cmd for x in self.queue), \
               "Queue should be empty, or only contain messages with the same operation/cmd"
        return True


async def poison_channel(ch):
    "Poisons a channel or a channel end."
    await ch.poison()


# TODO: strictly speaking, asyncio provides both synchronous and async/buffered queueing on the channel out of the box.
# - for synchronous - wait for the operation to complete (be mached with a read/write)
# - for queued - submit n operations and wait for them to complete later.
# - for the programmer, there is usually not much of a difference waiting on a lock to be allowed into the
#   channel and being queued on the channel.
# - the main difference is the semantics of ALT (see below) and whether a write should be considered completed if it is
#    written on a channel.
# TODO:
# - This could be an option on the normal channel.
#   (we could just reassign the _write on channels with buffer set).
# - Buffer limit.
# - ALT writes should be considered as successful and transformed into normal
#   writes if there is room in the buffer, otherwise, we will have to
#   consider them again when there is room.
# - When write ops are retired, we need to consdier waking up alts and writes
#   that are sleeping on a write.
class BufferedChannel(Channel):
    """Buffered Channel. """
    def __init__(self, name="", loop=None):
        super().__init__(name=name, loop=loop)

    async def _write(self, obj):
        if self.poisoned:
            raise PoisonException
        wcmd = _ChanOP(CH_WRITE, obj)
        if (rcmd := self._pop_matching(CH_READ)) is not None:
            return self._rw_nowait(wcmd, rcmd)[0]

        # The main difference with normal write: simply append a write op without a future and return to the user.
        self.queue.append(wcmd)
        return 0


# ******************** ALT ********************
#
class Alternative:
    """Alternative. Selects from a list of guards.

    This differs from the old thread-based implementation in the following way:
    1. Guards are enabled, stopping on the first ready guard if any.
    2. If the alt is waiting for a guard to go ready, the first guard to
       switch to ready will immediately jump into the ALT and execute the necessary bits
       to resolve and execute operations (like read in a channel).
       This is possible as there is no lock and we're running single-threaded code.
       This means that searching for guards in disable_guards is no longer necessary.
    3. disable_guards is simply cleanup code removing the ALT from the guards.
    This requires that all guard code is synchronous / atomic.

    NB:
    - This implementation supports multiple ALT readers on a channel
      (the first one will be resolved).
    - As everything is resolved atomically it is safe to allow allow
      ALT writers and ALT readers in the same channel.
    - The implementation does not, however, support a single Alt to send a read
      _and_ a write to the same channel as they might both resolve.
      That would require the select() function to return more than one guard.
    - Don't let anything yield while runnning enable, disable pri_select.
      NB: that would not let us run remote ALTs/Guards... but the reference implementation cannot
      do this anyway (there is no callback for schedule()).
    """
    # States for the Alternative construct.
    _ALT_INACTIVE = "inactive"
    _ALT_READY    = "ready"
    _ALT_ENABLING = "enabling"
    _ALT_WAITING  = "waiting"

    def __init__(self, *guards):
        self.guards = guards
        self.state = self._ALT_INACTIVE
        self.enabled_guards = []  # List of guards we successfully enabled (and would need to disable on exit).
        self.wait_fut = None      # Wait future when we need to wait for any guard to complete.
        self.loop = asyncio.get_running_loop()

    def _enable_guards(self):
        "Enable guards. Selects the first ready guard and stops, otherwise it will enable all guards."
        assert len(self.enabled_guards) == 0, "Running _enable_guards() on an alt with existing enabled guards"
        try:
            for g in self.guards:
                self.enabled_guards.append(g)
                enabled, ret = g.enable(self)
                if enabled:
                    # Current guard is ready, so use this immediately (works for pri_select).
                    self.state = self._ALT_READY
                    return (g, ret)
            return (None, None)
        except PoisonException as e:
            # Disable any enabled guards.
            self._disable_guards()
            self.state = self._ALT_INACTIVE
            # Re-throwing the exception to reach the caller of alt.select.
            raise e

    # This should not need to check for poison as any already enabled guards should have blabbered
    # about the poison directly through alt.poison().
    # Also, _disable_guards() is called when _enable_guards() detects poison.
    def _disable_guards(self):
        "Disables guards that we successfully entered in enable_guards."
        for g in self.enabled_guards:
            g.disable(self)
        self.enabled_guards = []

    # TODO: pri_select always tries the guards in the same order. The first successful will stop the attemt and unroll the other.
    # If all guards are enabled, the first guard to succeed will unroll the others.
    # The result is that other types of select could be provided by reordering the guards before trying to enable them.

    async def select(self):
        """Calls the default select method (currently pri_select) to wait for any one guard to become ready.
        Returns a tuple with (selected guard, return value from guard).
        """
        return await self.pri_select()

    async def pri_select(self):
        """Waits for any of the guards to become ready.

        It generally uses three phases internally:
        1) enable, where it enables guards, stopping if any is found to be ready
        2) wait - it will wait until one of the guards becomes ready and calls schedule.
           This phase is skipped if a guard was selected in the enable phase.
        3) diable - any guards enabled in the enable phase will be disabled.

        A guard that wakes up in phase 2 will notify the alt by calling schedule() on the alt.
        See Channel for an example.

        Returns a tuple with (selected guard, return value from guard).
        """
        # 1) First, enable guards.
        self.state = self._ALT_ENABLING
        g, ret = self._enable_guards()
        if g:
            # We found a guard in enable_guards, skip to phase 3.
            self._disable_guards()
            self.state = self._ALT_INACTIVE
            return (g, ret)

        # 2) No guard has been selected yet. Wait for one of the guards to become "ready".
        self.state = self._ALT_WAITING
        self.wait_fut = self.loop.create_future()
        g, ret = await self.wait_fut
        # By this time, schedule() will have resolved everything and executed phase 3.
        # The selected guard and return value are available in (g, ret)
        # Poion that propagated while sleeping will be handled by poison using set_exception().
        self.state = self._ALT_INACTIVE
        return (g, ret)

    def schedule(self, guard, ret):
        """A wake-up call to processes ALTing on guards controlled by this object.
        Called by the (self) selected guard.
        """
        if self.state != self._ALT_WAITING:
            # So far, this has only occurred with a single process that tries to alt on both the read and write end
            # of the same channel. In that case, the first guard is enabled, waiting for a matching operation. The second
            # guard then matches up with the first guard. They are both in the same ALT which is now in an enabling phase.
            # If a wguard enter first, the rguard will remove the wguard (flagged as an ALT), match it with the
            # read (flagged as RD). rw_nowait will try to run schedule() on the wguard's ALT (the same ALT as the rguard's ALT)
            # which is still in the enabling phase.
            # We could get around this by checking if both ends reference the same ALT, but it would be more complicated code,
            # and (apart from rendesvouz with yourself) the semantics of reading and writing from the channel
            # is confusing for a normal Alt (you would need something like a ParAlt).
            # Furthermore, the results from the alt need to signal that there were two selected guards (and results).
            # There is a risk of losing events that way. A workaround to detect this earlier could be to examine
            # the guard list when running select() and trigger an exception here, but that would only work if
            # we know beforehand which guards might create this problem.
            msg = f"Error: running schedule on an ALT that was in state {self.state} instead of waiting."
            raise Exception(msg)
        # NB: It should be safe to set_result as long as we don't yield in it.
        self.wait_fut.set_result((guard, ret))
        self._disable_guards()

    def poison(self, guard):
        """Used to poison an alt that has enabled guards"""
        msg = f"ALT {self} was poisoned by guard {guard}"
        # print(msg)
        # Running disable_guards is safe as long as none of the guards try to set the wait_fut
        self._disable_guards()
        if self.wait_fut.done():
            print("WARNING: alt.wait_fut was already done in alt.poison. This will raise an exception.")
        self.wait_fut.set_exception(PoisonException(msg))

    # Support for asynchronous context managers. Instead of the following:
    #    (g, ret) = ALT.select():
    # we can use this as an alternative:
    #    async with ALT as (g, ret):
    #     ....
    # We may need to specify options to Alt if we want other options than pri_select.
    async def __aenter__(self):
        return await self.select()

    async def __aexit__(self, exc_type, exc, tb):
        return None
