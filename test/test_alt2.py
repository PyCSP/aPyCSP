#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
# See LICENSE.txt for licensing details (MIT License).

import asyncio
from apycsp import process, Alternative, Channel, Parallel
from apycsp.utils import handle_common_args


@process
async def p1_a(cout, cin, pid):
    print(f"Bip 1a-{pid}")
    og = cout.alt_pending_write(42)
    alt = Alternative(og, cin)
    for _ in range(10):
        print(f"ding 1a-{pid}")
        async with alt as (g, val):
            print(f"  p1_a{pid}: got from select:", g, type(g), val)


# opposite order of alt guards
@process
async def p1_b(cout, cin, pid):
    print(f"Bip 1a-{pid}")
    og = cout.alt_pending_write(42)
    alt = Alternative(cin, og)
    for _ in range(10):
        print(f"ding 1b-{pid}")
        async with alt as (g, val):
            print("  p1_b{pid}: got from select:", g, type(g), val)


async def test_alts():
    print("-------------- test1 -------------")
    a = Channel("a")
    b = Channel("b")
    await Parallel(
        p1_a(a.write, b.read, 1),
        p1_a(b.write, a.read, 2))

    # Check that the channels are still in a decent state
    a.verify()
    b.verify()


async def test_alt_exception_multi_op_same_channel():
    print("-------------- test2 -------------")
    # TODO: the reason why this is happening is that rw_nowait is
    # calling alt.schedule for the alts in both ends of the channel
    # so, the alt waking up the other alt is re-scheduled! We should ignore this schedule, or avoid to call it.
    # or is it?
    # Two guards firing at the same time is a bit problematic if you consider CSP and traces.

    # See comment in priSchedule()
    # We could just return here, but then there is nobody to await the read end... or is it?
    # We don't get an error message when exiting, so something is cleaning up this... TODO: inspect
    # test = p1_b(1, 2, 3) # this creates a warning that it was never awaited
    # so what happens is
    print("This will probably fail")
    c = Channel("a")
    caught_it = False
    try:
        await Parallel(p1_a(c.write, c.read, 1))
    except Exception as e:
        print("It did... : ", e.args)
        caught_it = True
    c.verify()
    assert caught_it, "Should have gotten an exception on the alt"


def test_funcs():
    asyncio.run(test_alts())
    asyncio.run(test_alt_exception_multi_op_same_channel())


if __name__ == "__main__":
    handle_common_args()
    test_funcs()
