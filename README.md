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


The other implementations are available as follows: 
- the lock based asyncio version: [https://github.com/jmbjorndalen/aPyCSP_lockver](https://github.com/jmbjorndalen/aPyCSP_lockver)
- the thread based reference implementation: [https://github.com/jmbjorndalen/pycsp_classic](https://github.com/jmbjorndalen/pycsp_classic)
- the current PyCSP implementation: [https://github.com/runefriborg/pycsp](https://github.com/runefriborg/pycsp)




