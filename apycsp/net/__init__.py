#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""PyCSP Barrier based on the JCSP barrier. 

Copyright (c) 2018 John Markus Bjørndalen, jmb@cs.uit.no.
See LICENSE.txt for licensing details (MIT License). 

A simple json based protocol and net implementation for early exeperimentation with a network protocol
that can be used between processes/event queues. Using a JSON based protocol also lets us 
interface with Go and Javascript in the future. 

There is no attempt at making ALT-capable channels so far.

A rough sketch of how this works is as follows: 

- a client wanting to read or write on a channel access a proxy object. 
- the operation is transformed into a dict / json like encoding of the operation, 
  and that object is queued on an output queue. 
  Each operation is given a unique ID to let us match calls with return values. 
- a message writer picks up the object, encodes it as a json string and sends it to the server. 
  Newlines separates messages.
- the server reads the line with the message, converts it to a dict and spawns a handler that will 
  find the right channel and run the operation on it. 
- when the handler completes the operation, it will check for poison and encode the 
  results (+ poison/exceptions) in a result dict and queue it on the server output queue (for the 
  respective client connection). 
- the client receives the message on the channel and spawns a message handler that will look up 
  the call ID to find the waiting client coroutine. 

At the moment, the mechanism for waking up a waiting client is to write the result on a 
per-call queue. We could in principle do the same with a channel, but we have to 
sort out the poison semantics and potential overheads etc for this first. 


Channel naming service is very simple at the moment: there is
nothing. You have to know which server has a given channel you want to
talk to. We should consider a naming service, or a protocol extension 
that allows us to query a server for: 
a) a list of channels on on that server
b) if a channel exists on that server
c) other servers it knows about, channels on other servers, etc...???? (TODO)


"""


# Protocol so far:
# {op : 'write', name: 'channame', 'msgno': msgno, 'msg' : msg}
# => {'ack' : msgno, 'ret' : retval, 'exc' : exception info}
#    the ack will only be sent when the operation has completed in the remote end and
#    will contain info about return values and exceptions as l
# {op : 'read', name: 'channame', 'msgno' : msgno}
# => {'ack' : msgno, 'ret' : retval, 'exc' : exception info}
#    returns the results of a read operation
# 
# It's the sender's responsibility to use unique message numbers for
# each channel (and to decied if they need to be unique per channel or
# across channels)
#
# Potential commands: 
# {'op' : 'chanlist'} => {'ack' : [list of channel names]}
# {'op' : 'has_chan'} => {'ack' : true or false}
# 
# TOSORT / TODO: 
# use ordinary channels, but 'expose' them to the net system via an api (similar to old pycsp)
# remtoe calls are just ordinary coroutines that call and put the return values/msgs on a queue
#
# on an incoming message:
# - look up channel
# - register call (for debug)
# - create coroutines for call
# - ensure_future (or something similar)
#   - coroutine does the ordinary operation and queues the results (including exceptiont to enable poison propagation etc)
# local end:
# - ask net for a channel (end) proxy and use it as a normal channel. Buffered channels could be ALT-able with a snag.
#
# alt across the net _should_ be doable, but the performance would probably be bad, but how bad?


import apycsp
import asyncio
import json
import functools

# registry of channels to expose to the net. Keys are the names. 
_chan_registry = {} 

def register_channel(chan, name):
    # TODO: should check if already existing
    _chan_registry[name] = chan


#############################################################
# 
# Common handlers. We might consider creating PyCSP procs or channels here instead, but we have to
# a) watch for poison (don't kill this channel because we were told to write on a poisoned channel), and
# b) consider buffered channels (on the other hand, procs are cheap, so
# procs waiting on a chan write effectively becomes a queue as well. 
#
async def _queue_sender(queue, writer):
    """Drains a queue for a given connection and writes the json strings to the 'writer'"""
    while True:
        msg = await queue.get()
        if msg == 'kill':
            print("Got kill token in _queue_sender. Exiting")
            break
        print(f"Sending: {msg}")
        msg_s = json.dumps(msg) + "\n"
        if writer.transport.is_closing():
            print("Lost connection on writer before we could send message")
            break
        res = writer.write(msg_s.encode())
        res2 = await writer.drain()
    writer.close()
    print("_queue_sender done")
    
async def _stream_reader(reader, handler, oqueue = None):
    """Reads lines from reader, converts from json strings to objects and runs a handler 
    for incoming messages. 
    """
    loop = asyncio.get_event_loop()
    while True:
        print("_stream_reader, waiting")
        data = await reader.readline()
        message = data.decode().strip()
        print(f"Got {message}")
        if message is None or message is '':
            print("Probably lost client")
            break
        loop.create_task(handler(json.loads(message)))
    print("_stream_reader done")
    if oqueue:
        await oqueue.put("kill") # put token on output queue to wake up and kill writer
    
#############################################################
# 
# Serving clients
#

# TODO: we don't have a clean way of cancelling operations on closed connections.
# As of now, they will complete their operations and queue the results.
# When the last _handle_msg finishes, the results should be garbage collected.
# A qlean method might require some ALT-able read/writes on channels,
# as well as defining what it means to actually send a full write with contents
# and disappearing before getting the result.
# This is something we need to worry about in the DAO project where the other
# end might disappear permanently or temporarily in the middle of operations.
# For a temporary disconnect, it's possible to handle some issues by having an ID of the client
# and reconnect the result queue with the client when it reconnects. 

async def _handle_cmd(cmd, oqueue = None):
    """Interprets and runs the command, waits for and queues the result (including exceptions) on oqueue"""

    op = cmd.get('op', None)
    msgno = cmd['msgno']
    if op in ['read', 'write']:
        name = cmd.get('name', None)
        chan = _chan_registry.get(name, None)
        print("  -- ops is ", op)
        if op == 'read':
            print(" -- trying to read")
            res = await chan.read()
        else:
            res = await chan.write(cmd['msg'])
        await oqueue.put({'ack' : msgno, 'ret' : res, 'exc' : None})
        return 
    
    await oqueue.put({'ack' : msgno, 'err': f'command {op} not recognized'})
    print("handle done")
    
async def _client_handler(reader, writer):
    """Handler for a client connection. Reads messages and spawns coroutines to handle each message."""
    loop = asyncio.get_event_loop()
    oqueue = asyncio.Queue()

    print("_client_handler creating in/out handler for ", writer.get_extra_info('peername'))
    res_writer   = _queue_sender(oqueue, writer)
    input_reader = _stream_reader(reader, functools.partial(_handle_cmd, oqueue=oqueue), oqueue)

    print("_client_handler now waiting for the handlers to complete")
    await asyncio.wait([res_writer, input_reader])
    print("_client handler finished\n")
    # should probably try to cancel any remaining tasks
    # add a close message on oqueue, or just let _res_writer notice that we're gone?
    # how do we handle handle_cmd? they're already running, so cancel wouldn't work... 


def start_server():
    loop = asyncio.get_event_loop()
    serv = asyncio.start_server(_client_handler, '127.0.0.1', 8890, loop=loop)
    task = loop.create_task(serv)
    print("Running server")
    return serv


#############################################################
# 
# Being a client
#

# TODO: need a queue similar to the other end, and then we need to pair results (with chname+msg#)
# with the caller and perhaps complete a future for them so they can continue running.
# The alternative is either a condition variable or a small queue per client operation.

_clconn = {}
_msgno = 0 # TODO: this should be replaced
_opqueue = {} # waiting for inputs

def _get_msgno():
    """Returns a unique message number, for pairing messages with acks"""
    global _msgno
    _msgno += 1
    return _msgno

async def _setup_client(host = '127.0.0.1', port=8890, loop=None):
    reader, writer = await asyncio.open_connection(host, port, loop=loop)
    oqueue = asyncio.Queue()
    rqueue = asyncio.Queue()
    _clconn['def'] = (reader, writer, oqueue, rqueue)

    async def _handler(cmd, oqueue=rqueue):
        """Puts the incoming command on the receive queue for that message id"""
        msgno = cmd['ack']
        rq = _opqueue[msgno]
        await rq.put(cmd)
        #await rqueue.put(cmd) # global receive queue
    loop.create_task(_queue_sender(oqueue, writer))
    loop.create_task(_stream_reader(reader, _handler, oqueue))

def setup_client(host = '127.0.0.1', port=8890):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_setup_client(host, port, loop))

async def _send_recv_cmd(cmd, msgno):
    reader, writer, oqueue, rqueue = _clconn['def']  # TODO: should support multiple remotes.
    # first, get a input queue for that message
    _opqueue[msgno] = asyncio.Queue()
    print("cl sending", cmd)
    await oqueue.put(cmd)
    print("cl sent, now waiting")
    res = await _opqueue[msgno].get()
    print("cl got", res)
    del _opqueue[msgno]  # delete queue after command is finished
    return res

def send_message_sync(cmd):
    """NB: a unique msgno will be inserted into the cmd"""
    msgno = _get_msgno()
    cmd['msgno'] = msgno
    loop = asyncio.get_event_loop()
    sender = _send_recv_cmd(cmd, msgno)
    res = loop.run_until_complete(sender)
    return res
    
class RemoteChan:
    def __init__(self, name, host='127.0.0.1', port=8890):
        self.name = name
        self.host = host
        self.port = port

    async def write(self, msg):
        msgno = _get_msgno()
        cmd = {
            'op' : 'write',
            'msgno' : msgno, 
            'name'  : self.name,
            'msg'  : msg
        }
        # TODO: check for poison
        return await _send_recv_cmd(cmd, msgno)
    
    async def read(self):
        msgno = _get_msgno()
        cmd = {
            'op' : 'read',
            'msgno' : msgno, 
            'name'  : self.name,
        }
        # TODO: check for poison
        return await _send_recv_cmd(cmd, msgno)
        
# todo: need to pick the reply from the server up from the queue and re-queue it in the _opqueue[msgid]  

    
