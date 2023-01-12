* 2022-12-27
  - Breaking changes in the API: Examples triggered deprecation
    warnings from asyncio. Some of this was related to using
    `get_event_loop`.  This has been changed to get_running_loop(),
    but this does not start a new loop of a loop is not already
    running. Therefore, some of the examples had to be modified.
    Furthermore, run_CSP was removed. The recommended way to run 
    CSP processes is inside async functions and methods.
  - The net library was updated to work with newer Python versions.
  - aPyCSP channels were changed to use a single queue in the 
    implementation. This simplifies some of the implementation and 
    verification of correctness. 
* 2023-01-11
  - Reorganised the repository a bit, separating test code from 
    examples and experimental code.
  - moved common.py from other subdirectories to apycsp/utils.py
    It should be safer to use virtualenvs to run the code from
    the separate directories rather than using sys.path hack during 
    development. That also fixes some dev environment issues 
    (ex: not finding imports).



    
    
