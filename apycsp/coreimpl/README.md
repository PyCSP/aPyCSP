Experimental implementation of the "VM" / CSP OP / opqueue concept.

Instead of a complicated set of thread-like coroutines, we simplify
the implementation by taking advantage of two things:

a) we queue operations on channels as opcodes + data (and potentially
   futures that can be set when completing)

b) we take advantage of cooperative multitasking, executing without
   locks and knowing that we will not be preempted.

The channel and ALT implementations could then be implemented in a
less convoluted manner, should be easier to reason about and
understand, and it turns out the channels and processes are
significantly faster and use less memory than the other
implementation. We can also support multiple readers using ALT on the
same channel. It should be possible to use a similar trick to
implement ALT for writing on the channel as well.

We do have to change the semantics slightly though: 

- enable and disable need to be synchronous calls that cannot yield.
  They can, however, create couroutines and enter them in the event
  loop as well as setting the results of futures.

- disable no longer checks for ready guards, it's strickly for
  unrollig registration of the ALT on the guards.

- when a 'ready' condition is found, the channel end / guard is
  responsible for immediately executing the action and returning the
  result as well as the ready state. This can happen in enable(), but
  also in timers etc.

This simplifies another aspect: only one guard can become active at
the same time as we enforce resolving and immediately unrolling when
we notice the first ready guard. We effectively get an "Oracle" for free. 

TODO: more detailed descriptions later.
"""
