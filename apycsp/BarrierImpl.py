#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
PyCSP Barrier based on the JCSP barrier. 

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 
"""

import asyncio

class Barrier(object):
    def __init__(self, nEnrolled):
        self.lock = asyncio.Condition()
        self.reset(nEnrolled)
    async def reset(self, nEnrolled):
        with await self.lock:
            self.nEnrolled = nEnrolled
            self.countDown = nEnrolled
            if nEnrolled < 0:
                raise Exception("*** Attempth to set a negative nEnrolled on a barrier")
    async def sync(self):
        "Synchronize the invoking process on this barrier."
        with await self.lock:
            self.countDown -= 1
            if self.countDown > 0:
                await self.lock.wait()
            else:
                self.countDown = self.nEnrolled
                self.lock.notify_all()
    async def enroll(self):
        with await self.lock:
            self.nEnrolled += 1
            self.countDown += 1
    async def resign(self):
        with await self.lock:
            self.nEnrolled -= 1
            self.countDown -= 1
            if self.countDown == 0:
                self.countDown = self.nEnrolled
                self.lock.notify_all()
            elif self.countDown < 0:
                raise Exception("*** A process has resigned on a barrier when no processes were enrolled ***")
        
