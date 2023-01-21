#!/usr/bin/env python3

"""
Base and simple guards (channel ends should inherit from a Guard)
"""
import asyncio


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
