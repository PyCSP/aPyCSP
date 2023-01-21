#!/usr/bin/env python3
"""
ALT
"""

import asyncio
from .core import PoisonException


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
