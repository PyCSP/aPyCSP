#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import random
import asyncio
from apycsp import process, Channel, Alternative, Parallel
from apycsp.utils import handle_common_args

handle_common_args()


@process
async def producer(ch, name):
    await asyncio.sleep(random.random())
    await ch(name)


@process
async def consumer(ch1, ch2):
    alt = Alternative(ch1, ch2)
    for _ in range(2):
        async with alt as (_, v):
            print(v)


async def run_test():
    ch1 = Channel('ch1')
    ch2 = Channel('ch2')
    await Parallel(
        producer(ch1.write, 'p1'),
        producer(ch2.write, 'p2'),
        consumer(ch1.read, ch2.read))


asyncio.run(run_test())
