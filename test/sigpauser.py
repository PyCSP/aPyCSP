#!/usr/bin/env python3
#
# Experimental code to let us pause and resume a PyCSP process.
#
# kill -USR1 pid to pause
# kill -USR2 pid to continue

import signal
import time
import os

suspended = False


def pausehandler(signum, frame):
    global suspended
    suspended = True
    print("INT got", signum, frame)
    time.sleep(1)
    while suspended:
        print("INT waiting")
        time.sleep(1)
    print("INT Done")


def conthandler(signum, frame):
    global suspended
    print("CONT")
    suspended = False


signal.signal(signal.SIGUSR1, pausehandler)
signal.signal(signal.SIGUSR2, conthandler)
# signal.pause() # wait until a signal is received.
print("Pid of this process : ", os.getpid())
