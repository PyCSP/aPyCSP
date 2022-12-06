# aPyCSP

Experimental version of the 0.3 line of PyCSP using asyncio. 

The initial implementation of this library was kept close to the the
PyCSP implementation to simplify comparisons. This means that some of
the newer functionality from more recent PyCSP implementations (such
as "retire") does not exist yet. 

The main differences are that: 
* We do not support multithreading at the moment; it's replaced with asyncio whenever possible 
* Any method or function that might "block" is replaced with 'async def' coroutines
* Function calls, context managers etc that might block/yield must be modified to equivalent await-statements
* The Process class is gone and replaced with a normal async def function as we don't need Thread objects. 

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
    g, res = await alt.select()
    print("Got result from alt: ", val)
```

Some of the main advantages of this version compared to the multithreaded version are:
* support for input _and_ output guards
* arbitrary number of readers, writers and guarded reads and writes (through ALT) can be queued on channel ends
* there is no need for specific channel types that limit the number of readers and writers
* the implementation is faster and uses less memory per @process. 
* It is also easier to read and understand, partly due to reduced complexity. 


For the other implementations of PyCSP, please check: 
- [https://pycsp.github.io](https://pycsp.github.io) for an overview of the PyCSP repositories. 
- [https://github.com/PyCSP](https://github.com/PyCSP) for the main PyCSP github organisation. 






