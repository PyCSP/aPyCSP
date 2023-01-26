Termination and poison
======================

To terminate processes in process networks, PyCSP originally built a
poison mechanism based on the one used in JCSP
[sputh2005]. Poison would be injected into channels, and any process
trying to access the channel after that would have a PoisonException
raised.

The text below does not deal with sending termination tokens across
channels. That was partially discussed in the JCSP paper.

Dealing with poison
--------------------
To cleanly terminate a process, the process had to catch the exception
and propagate the poison to other channels it accessed so the rest of the
processes in the group could be terminated.

To limit propagation to a sub-net of processes, JCSP used poison
levels and special channel types that could filter poison at different
levels. A programmer could then define borders where local level
poison would not propagate, protecting the rest of the application
from the termination of sub-groups.

Application of poison is instant. Once a channel is poisoned, any new
operation on it will trigger a poison exception. Any operation waiting
for a condition on the channel is also woken up and poisoned.

This differs from how channels in Go are treated: when a channel is
closed, no more writes can be attempted. Reads will succeed until all
buffered messages are drained from the channel. After the channel is
drained, reads will also fail. The general advice in Go is that only
the writer should close the channel, not the reader (partly due to the
way writes vs reads fail).

The [sputh2005] paper focused on unbuffered one-to-one channels (only
one process at each end).

Some issues that occur with poisoning are:

### PI-1 - multiple writers - early poisoning

Assume a network with 2 producers and 1 consumer using the same
channel.

```
producer --\
            ---> consumer
producer --/
```

When a producer finishes and cannot produce more messages, it could
poison the channel to terminate the reader. This works fine with one
producer and one consumer, but fails to work when producers are added.
If one producer finishes early, it would poison the channel,
terminating both the consumer and the other producer(s).

Another use is similar to generator patterns: the consumer is the one
that knows when it is fulfilled and when the producers can stop
sending messages. In JCSP and PyCSP, it can close the channel. This is
not recommended in Go as it would cause a panic which would have to be
recovered from.

One solution is to use out-of-band communication to signal
termination. This is often recommended in Go communities.

Later versions of PyCSP introduced a retire mechanism [vinter2009]
that would use reference counting on channels to determine when all
processes attached to an end of the channel stopped using that channel
end.

We will bring this up again further down.

### PI-2 - buffered channels

```
producer ---> consumer
```

If one producer writes N messages to a channel and then terminates
after poisoning the channel, the consumer may not be able to read all
of the messages until it catches the poison as the next read from the
consumer will trigger the exception.

The Go solution with closing channels lets the reader drain the channel
before terminating. The recommendation is still, however, that the
channel is drained before it is dropped. This means that producers and
consumers will still need to communicate out-of-band to terminate
early (if the consumer wants to stop). The producer end will also need to
make sure the channel is closed to signal termination to the consumer end.

If poison is not immediate, some part of the system will need to know
to unblock processes waiting on channels and how and when to
communicate termination intention to them.


### PI-3 - dealing with poison at the wrong level

In JCSP, poison handling was done in every process using a try-catch
block. This had to be done correctly for every process that could be
used with potentially poisoned channels.

To automate some of the poison handling, PyCSP added automatic poison
propagation through channels passed to the process when it was
created. The PyCSP library would catch poison exceptions when the
process terminated and take care of propagation.

This was probably a mistake as the automatic propagation code did not
have information about the intention of the programmer (which of the
channels should be poisoned, and in which order?). It also didn't
handle channel ends passed to the processes over channels, or passed
to the processes inside other objects. As an example: a user could
define a channel bundle object that was provided on the parameter list
to the process.

It was easy to make a mistake and get channels poisoned too early or
get the wrong channels poisoned. Adding a monitor channel would, for
instance, suddenly add a poison pathway out from a previously
correctly terminating system.


Dealing with poison at a higher level
------------------------------------

Revisiting the multiple producers example, let us first deal with the
writers terminating and poisoning the channel:

```
producer --\
            ---> consumer
producer --/
```

In go, one of the recommended solutions is to use a WaitGroup to wait
for the producers to complete. When a producer finishes it just
terminates and does not worry about closing the channel. A separate
goroutine will instead close the channel when all of the producers
have terminated.

We could use a similar mechanism in PyCSP, but there is a simple
solution already provided: use composable Sequence and Parallel
statements and a separate process that poisons any channel given to it:

```python
Parallel(
   Sequence(
      Parallel(
         producer(ch.write),
         ...
         producer(ch.write)),
      poison_channels(ch)),
   reader(ch.read))
```

The Sequence with a Parallel and `poison_channels` inside would be an
implementation of the WaitGroup concept: `poison_channels` will only
start executing after all of the producers in the Parallel have
terminated.

The advantage of dealing with poison propagation at this level
(outside the processes) is that the processes do not have to know (or
assume) how they will be used, how the processes are plugged in a
network and who should be terminated when.

Poison propagation could still be done inside a process as long as the
process is clearly documented.


### PI-4 turning all channel communication into an alt or try-except

Out-of-band communication can be used to communicate termination,
either through communication on a separate channel or by poisoning a
separate channel.

Exactly how this is done could vary: A concept similar to Go Contexts
could be implemented using channels and processes. WaitGroups could be
implemented as shown above, or other methods could be used to safely
poison channels or send termination intention on other channels.

The main consideration here is how to deal with it inside processes.

Two observations:

1. If the processes need to clean up properly instead of abruptly
   terminating (with poison), any communication over channels has to
   use a try-except to catch the poison exception and clean up (possibly
   using additional communication over one or more channels).

2. If additional channels are used to communicate termination, the
   processes will have to be (re-)written using Alternative / select.

2) is necessary, even if poison is used, as the process will need to be
able to sleep on a read or write while being poisoned on a separate
channel.

This means that for a simple process like this aPyCSP process:

```python
@process
async def add_one(ch_in, ch_out):
    async for msg in ch_in:
         await ch_out(msg + 1)
```

The process would need to be rewritten to take an extra parameter (or
more) for the out-of-band communication, and two alts. Both the
read-side (ch-in) and write site (ch-out) would need their own alts to
implement the same behaviour with termination support. Additionally,
it might need to use try-catch to cleanly terminate.

It is not hard to do for such a simple process, but it adds
complexity.  It also adds overhead as submitting two tentative
operations with an alt for every read or write is more expensive
than submitting a single read.


Poison propagation in aPyCSP and PyCSP-locksharing
------------

Based on the above, automatic poison propagation has been removed from
version 0.9.0 of both implementations. The fact that I wrote it and
that it tripped me up several times means that it broke the Principle
of Least Surprise.

Whether poisoning (that now works more like in the JCSP paper) should
be removed in favour of something more similar to channel closing in
Go or the retire mechanism from earlier PyCSP implementations is
another question. It has some advantages, but appears likely to turn
more communication into alt/selects.

The retire mechanism has not been implemented yet. One of the main
reasons was to reduce complexity while getting some of the other
concepts in the implementation correct first.

The above will have to be considered more before the implementations
get tagged with version 1.


References
-----------
- [sputh2005] JCSP-Poison: Safe Termination of CSP Process Networks, Bernhard H.C. Sputh, Alastair R. Allen, CPA 2005, IOS Press 2005
- [vinter2009] PyCSP Revisited, Brian Vinter, John Markus Bjørndalen, Rune Møllegaard Friborg, CPA 2009, IOS Press 2009
