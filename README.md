# aPyCSP

Experimental version of the 0.3 line of PyCSP using asyncio. 

The initial implementation of this library is kept close to the the
PyCSP implementation to simplify comparisons. This means that some of
the newer functionality from more recent PyCSP implementations (such
as "retire") does not exist yet.

The main differences are that: 
* we do not support multithreading at the moment; it's replaced with asyncio whenever possible 
* threading.Condition, RLock etc are replaced with asyncio equivalents
* Any method or function that might "block" is replaced with 'async def' coroutines
* Function calls, context managers etc that might block/yield must be modified to equivalent await-statements
* The Process class is gone and replaced with a normal decorator function as we don't need Thread objects. 

This means that the current source code is not directly compatible
with the thread based PyCSP version.

As an example, consider the following old PyCSP code: 

``` Python
    cout('something')
    ...
    alt = Alternative(....)
    res = alt.select()
    val = res()
    print("Got result from alt: ", val)
```

Using the asyncio version, we need to write: 

``` Python
    await cout('something')
    ...
    alt = Alternative(....)
    res = await alt.select()
    val = await res()
    print("Got result from alt: ", val)
```


Future considerations
============

I have not made any attempt at optimising the implementation so
far. As of 2018-03-28, the implementaion is slightly faster than the
thread based implementation (17.8us vs 26.6us on commstime). 

A simplified channel implementation is much faster than the tread
based implementation, but does not provide all the mechanisms for ALT,
and doesn't use asyncio.Condition and Lock, poison checking decorators etc. 

It might be possible to "hide" the differences between the thread and
asyncio version. An example is aParallel vs Parallel, but it would be
better with a more flexible and safer method that doesn't require the
user to use different names for the functions.

Memory usage
------

It uses less memory per process for a simple process experiment (~5KB
vs 13KB when measuring only RSS), and since it's not limited to max
threads per user, it scales to more CSP processes. 

On a 64GB computer, the thread based version maxed out at 9900
processes (running out of threads before running out of memory) while
this version is capable of 12 million processes consuming about 58GB
RAM.


Multithreading
----------

Multithreading has not been invest igated yet. Asyncio has some
support for it, but the event loops are thread local, which means that
moving a task/coroutine between threads might require moving the
coroutine between event loops. There might also be an issue with
synchronization between coroutines running in different threads that
should be considered. 


gather/wait overhead
----------------

On my computer, asyncio.gather or wait both add around 8 microseconds
to the runtime to commstime. 

A sequential Delta2 (send to both output channels in sequence) reports
a chan time of 18-19us. Running the sends/writes in a Parallel or
using gather or wait manually both add around 8us. Running them
sequentially through two gather/waits in sequence adds another 8us, so
there is clearly an overhead of about 8us each time we use them.

This should be investigated further to see if we can find something
that does the same with lower overhead. Could this be a result of
being appended to an event queue of some sort?






