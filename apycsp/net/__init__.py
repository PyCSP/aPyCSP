#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Network library. 

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


Channel naming service is very simple at the moment: if we don't have an entry for a given channel name,
we query all servers for their list of current channels. Then, the channel name is looked up again.

TODO:
- We should consider a more sophisticated naming service.
- We should replace the queues with buffered channels.
"""

import asyncio
import json
import functools
from apycsp import ChannelPoisonException, Channel, ChannelReadEnd, ChannelWriteEnd, Parallel

# registry of channels to expose to the net. Keys are the names.
_chan_registry = {}


def register_channel(chan, name):
    # TODO: should check if already existing
    _chan_registry[name] = chan


# ############################################################
#
# Common handlers. We might consider creating PyCSP procs or channels
# here instead, but we have to watch for poison (we need to capture
# and forward it to the client instead of the default behaviour of
# killing the process).
#
async def _stream_writer(writer, queue):
    """Drains a queue for a given connection and writes the json strings to the 'writer' stream"""
    while True:
        msg = await queue.get()
        if msg == 'kill':
            print("Got kill token in _stream_writer. Exiting")
            break
        msg_s = json.dumps(msg) + "\n"
        if writer.transport.is_closing():
            print("Lost connection on writer before we could send message")
            break
        writer.write(msg_s.encode())
        await writer.drain()
    writer.close()
    print("_stream_writer done")


async def _stream_reader(reader, handler, wqueue=None):
    """Reads lines from the reader stream, converts from json strings to objects and runs a handler
    for incoming messages.
    """
    loop = asyncio.get_event_loop()
    while True:
        data = await reader.readline()
        message = data.decode().strip()
        if message is None or message == '':
            print("Probably lost client")
            break
        loop.create_task(handler(json.loads(message)))
    print("_stream_reader done")
    if wqueue:
        await wqueue.put("kill")    # put token on output queue to wake up and kill writer


# ############################################################
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

async def _handle_cmd(cmd, oqueue=None):
    """Interprets and runs the command, waits for and queues the result (including exceptions) on oqueue"""

    op = cmd.get('op', None)
    msgno = cmd['msgno']
    if op in ['read', 'write', 'poison']:
        name = cmd.get('name', None)
        chan = _chan_registry.get(name, None)
        # print("  -- ops is ", op)
        exc = None
        res = None
        try:
            # attempt to read or write to a poisoned channel should throw poison
            if op == 'read':
                # print(" -- trying to read")
                res = await chan.read()
            elif op == 'write':
                res = await chan.write(cmd['msg'])
            else:
                res = await chan.poison()
        except ChannelPoisonException:
            exc = 'ChannelPoisonException'
            print("Tried to run op on poisoned channel", op, chan.name)
        await oqueue.put({'ack' : msgno, 'ret' : res, 'exc' : exc})
        return

    if op == 'ping':
        await oqueue.put({'ack' : msgno, 'ret' : 'ack'})
        return

    if op == 'print':
        print("Server asked to print {}".format(cmd['args']))
        await oqueue.put({'ack' : msgno, 'ret' : 'ack'})
        return

    if op == "chanlist":
        # List of channel names registered in this server
        chlist = list(_chan_registry.keys())
        print("Returning channel list", chlist)
        await oqueue.put({'ack' : msgno, 'ret' : chlist})
        return

    await oqueue.put({'ack' : msgno, 'ret': None, 'err': f'command {op} not recognized'})
    print("handle done")


async def _client_handler(reader, writer):
    """Handler for a client connection. Spawns coroutines to handle incoming and outgoing messages."""
    # loop = asyncio.get_event_loop()
    oqueue = asyncio.Queue()

    print("_client_handler creating in/out handler for ", writer.get_extra_info('peername'))
    await Parallel(_stream_writer(writer, oqueue),
                   _stream_reader(reader, functools.partial(_handle_cmd, oqueue=oqueue), oqueue))

    print("_client handler finished\n")
    # TODO: clean method for noticing a closed connection and notifying the handlers.
    # see local notes.


def start_server(host_port="8890"):
    """Start the remote channel/op server"""
    if ":" in host_port:
        host, port = host_port.split(":")
        port = int(port)
    else:
        host = None
        port = int(host_port)
    loop = asyncio.get_event_loop()
    serv = asyncio.start_server(_client_handler, host=host, port=port, loop=loop)
    loop.create_task(serv)
    print("Running server")
    return serv


#############################################################
#
# Client side code (for accessing remote channels)
#

_clconn = {}
_opqueue = {}   # waiting for inputs.
_msgno = 0


def _get_msgno():
    """Returns a unique message number, for pairing messages with acks"""
    global _msgno
    _msgno += 1
    return _msgno


class _ClientConn():
    def __init__(self, reader, writer, host_port, host, port, loop=None):
        self.reader = reader
        self.writer = writer
        self.host_port = host_port
        self.host = host
        self.port = port
        self.wqueue = asyncio.Queue()
        self.rqueue = asyncio.Queue()
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

    async def handler(self, cmd):
        """Puts the incoming command on the receive queue for that message id"""
        msgno = cmd['ack']
        try:
            rq = _opqueue[msgno]
        except KeyError as e:
            print("Got keyerror for received message", cmd)
            print("  - keys ", _opqueue.keys())
            print("  -", e)
            raise
        rq.set_result(cmd)

    async def send_recv_cmd(self, cmd, msgno=-1, throw_exception=True):
        """Sends a command to the remote end, and waits for and returns the result."""
        if msgno < 0:
            msgno = _get_msgno()
            cmd['msgno'] = msgno
        # first, get a input "queue" for that message. We only need a future for this as only one message will be delivered.
        rq = self.loop.create_future()
        _opqueue[msgno] = rq
        await self.wqueue.put(cmd)
        res = await rq
        del _opqueue[msgno]  # delete queue after command is finished
        if res.get('exc', None) == 'ChannelPoisonException':
            # print("propagating poison, ", cmd, res)
            raise ChannelPoisonException()
        return res['ret']


async def _setup_client(host_port='127.0.0.1:8890', loop=None):
    host, port = host_port.split(":")
    port = int(port)
    reader, writer = await asyncio.open_connection(host, port, loop=loop)
    conn = _ClientConn(reader, writer, host_port, host, port)
    _clconn[host_port] = conn

    loop.create_task(_stream_writer(writer, conn.wqueue))
    loop.create_task(_stream_reader(reader, conn.handler, conn.wqueue))


def setup_client(host_port='127.0.0.1:8890'):
    """Connect to a server. Currently only supports one connection"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_setup_client(host_port, loop))


# NB: send_message_sync doesn't work when called from a coroutine already executed by the event loop.
# The event loop is not "reentrant", so you can't provide something that has a "synchronous"
# external interface and use it from an async function using loop.run_until_complete(co)
# We have a similar problem with initializing the RemoteChan object. The solution for now is to provide
# both a synchronous and an asynchronous/couroutine version of get_channel_proxy instead of
# allocating a RemoteChan object directly.
def send_message_sync(cmd):
    """Synchronous send/recv of a message for debug purposes.
    NB: a unique msgno will be inserted into the cmd."""
    loop = asyncio.get_event_loop()
    conn = _clconn[list(_clconn.keys())[0]]   # TODO: naughty hack
    return loop.run_until_complete(conn.send_recv_cmd(cmd))


# Inherit from Channel and ChannelEnd to make sure poison propagation works locally as well.
class _RemoteChan(Channel):
    """Proxy object for using a remote channel.
    Only supports simple read/write mechanics at the moment.
    Don't allocate this one directly. Use the get_channel_proxy* functions instead.
    """
    def __init__(self, name, loop, conn):
        super().__init__(name)
        self.loop = loop
        self.conn = conn

    async def _write(self, msg):
        cmd = {
            'op' : 'write',
            'name'  : self.name,
            'msg'  : msg
        }
        # TODO: check for poison
        return await self.conn.send_recv_cmd(cmd)

    async def _read(self):
        cmd = {
            'op' : 'read',
            'name'  : self.name,
        }
        # TODO: check for poison
        return await self.conn.send_recv_cmd(cmd)

    async def poison(self):
        # Make sure we poison both the local proxy and the remote channel
        await super().poison()
        cmd = {
            'op' : 'poison',
            'name'  : self.name,
        }
        return await self.conn.send_recv_cmd(cmd)


class _RemoteChanProxy(_RemoteChan):
    def __init__(self, name=None, loop=None, conn=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        super().__init__(name, loop, conn)
        self.read  = ChannelReadEnd(self)
        self.write = ChannelWriteEnd(self)


_rchan_reg = {}  # connections to use to reach a remote channel. Indexed by channel name.
async def _find_remote(name):    # noqa E302
    """Find connection for a remote channel. """
    # TODO: this fails if we allow remote channels to move, or if we reconnect to the remote server
    if name in _rchan_reg:
        return _rchan_reg[name]
    for clname, conn in _clconn.items():
        ret = await conn.send_recv_cmd({'op' : 'chanlist'})
        print("Registering", ret, "as owned by", clname)
        for rname in ret:
            _rchan_reg[rname] = conn
    return _rchan_reg[name]


async def get_channel_proxy(name):
    """Returns a remote channel. Use this from within a coroutine or aPyCSP process."""
    conn = await _find_remote(name)
    return _RemoteChanProxy(name, conn=conn)


def get_channel_proxy_s(name):
    """Synchronous version when we want to create a proxy from outside a coroutine
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(get_channel_proxy(name))
