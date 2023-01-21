n#!/usr/bin/env python3
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

# flake8:  noqa: F401
# pylint: disable=unused-import
from .core import PoisonException, process, Parallel, Sequence, Spawn
from .guards import Guard, Skip, Timer
from .channels import Channel, ChannelEnd, PendingChanWriteGuard, ChannelWriteEnd
from .channels import ChannelReadEnd, poison_channel, BufferedChannel
from .alternative import Alternative
