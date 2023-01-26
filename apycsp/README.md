The implementation of the main library for aPyCSP is organised as follows:

- `__init__.py`  - package setup
- `alternative.py` - The external choice (Alternative)
- `channels.py` - Channel implementations
- `core.py` - Core functionality
- `guards.py` - The main Guard class and example/utility guards

Other files and subdirectories:
- `net` is an implementation of a network library for using channels remotely.
- `plugNplay` includes some standard processes, mainly based on processes from older versions of PyCSP and JCSP.
- `utils.py` - utilities for the implementation and for testing, benchmarking and examples.
