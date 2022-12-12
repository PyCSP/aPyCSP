aPyCSP - PyCSP using coroutines and asyncio.
============================================

This is one of the two most up to date implementations of PyCSP. 
The other one is the thread based implementation at
[https://github.com/PyCSP/PyCSP-locksharing](https://github.com/PyCSP/PyCSP-locksharing).

This implementation uses Python coroutines and the asyncio library. 

Some of the main advantages compared to older implementations are:
- support for input _and_ output guards
- arbitrary number of readers and writers (as well as guarded reads and writes through ALT) can be queued on channel ends
- there is no need for specific channel types that limit the number of readers and writers
- the implementation is faster and uses less memory per @process. 
- It is also easier to read and understand, partly due to reduced complexity. 

Compared to the thread based version: 
- support for a higher number of concurrent processes
- less memory overhead per process
- less context switching overhead

The major drawbacks are: 
- incompatible with the thread based version (requires coroutine syntax, see below)
- there is currently no direct support for using aPyCSP in a multithreaded program. 
- blocking operations in processes should be replaced with asyncio (or similar) versions. 

For the other implementations of PyCSP, please check: 
- [https://pycsp.github.io](https://pycsp.github.io) for an overview of the PyCSP repositories. 
- [https://github.com/PyCSP](https://github.com/PyCSP) for the main PyCSP github organisation. 


### Syntax compared with a thread based version

Coroutines in Python use some extensions to the Python syntax, which
means that the aPyCSP API is slightly different than in a thread based
version.

As an example, consider the following older thread based PyCSP code: 

``` Python
    cout('something')
    ...
    alt = Alternative(....)
    res = alt.select()
    val = res()
    print("Got result from alt: ", val)
```

In aPyCSP, many constructs are awaitable coroutines, which require a change to how they are used: 

``` Python
    await cout('something')
    ...
    alt = Alternative(....)
    g, res = await alt.select()
    print("Got result from alt: ", val)
```

The main differences are that: 
* Any method or function that might "block" is replaced with 'async def' coroutines
* Function calls, context managers etc that might block/yield must be modified to equivalent await-statements
* The Process class is gone and replaced with a normal async def function as we don't need Thread objects. 


### Performance improvement using uvloop (optional)

The performance of aPyCSP can be improved by using uvloop to replace
the asyncio scheduler. The examples and benchmarks can be executed
with uvloop by specifying the -u parameter. 
