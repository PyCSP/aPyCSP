#!/usr/bin/env python3
"""
Channels.
"""

import collections
import asyncio
from enum import Enum
from .core import PoisonException
from .guards import Guard


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

    # Support for reading from the channel end using "async for ch.read"
    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chan.poisoned:
            raise StopAsyncIteration
        try:
            return await self._chan._read()
        except PoisonException:
            # The iterator interface should not terminate using PoisonException
            raise StopAsyncIteration


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
        # necessary to support removing more than one operation on the same alt.
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
