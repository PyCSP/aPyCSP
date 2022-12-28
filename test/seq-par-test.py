#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2007 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import asyncio
from common import handle_common_args
from apycsp import process, Parallel, Sequence

handle_common_args()


@process
async def TestProc(n):
    print("This is test proc", n)
    return f'proc{n}'


async def run_test():
    print("---- Testing Sequence")
    r = await Sequence(
        TestProc(1),
        TestProc(2),
        TestProc(3))
    print("Return values", r)

    print("\n---- Test of Parallel")
    r = await Parallel(
        TestProc(1),
        TestProc(2),
        TestProc(3))
    print("Return values", r)


asyncio.run(run_test())
