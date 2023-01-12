#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2007 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import asyncio
from apycsp import process, Parallel, Sequence
from apycsp.utils import handle_common_args


@process
async def TestProc(n):
    print("This is test proc", n)
    return f'proc{n}'


async def test_seq():
    print("---- Testing Sequence")
    res = await Sequence(
        TestProc(1),
        TestProc(2),
        TestProc(3))
    print("Return values", res)
    assert all([r == f'proc{n}' for n, r in enumerate(res, start=1)]), "Results should be correct and in order"
    assert len(res) == 3, "Should be one result per proc"


async def test_par():
    print("\n---- Test of Parallel")
    res = await Parallel(
        TestProc(1),
        TestProc(2),
        TestProc(3))
    print("Return values", res)
    assert all([f'proc{n}' in res for n, r in enumerate(res, start=1)]), "All process return values should be in res"
    assert len(res) == 3, "Should be one result per proc"


if __name__ == '__main__':
    handle_common_args()
    asyncio.run(test_seq())
    asyncio.run(test_par())
