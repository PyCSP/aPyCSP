#!/usr/bin/env python3
"""Core implementation of the aPyCSP library. See README.md for more information.

"""

# flake8:  noqa: F401
# pylint: disable=unused-import
from .core import PoisonException, process, Parallel, Sequence, Spawn
from .guards import Guard, Skip, Timer
from .channels import Channel, ChannelEnd, PendingChanWriteGuard, ChannelWriteEnd
from .channels import ChannelReadEnd, poison_channel, BufferedChannel
from .alternative import Alternative
