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

- A client wanting to read or write on a channel access a proxy object.
- The operation is transformed into a dict / json like encoding of the operation,
  and that object is queued on an output queue.
  Each operation is given a unique ID to let us match calls with return values.
- A message writer picks up the object, encodes it as a json string and sends it to the server.
  Newlines separates messages.
- The server reads the line with the message, converts it to a dict and spawns a handler that will
  find the right channel and run the operation on it.
- when the handler completes the operation, it will check for poison and encode the
  results (+ poison/exceptions) in a result dict and queue it on the server output queue (for the
  respective client connection).
- the client receives the message on the channel and spawns a message handler that will look up
  the call ID to find the waiting client coroutine.

At the moment, the mechanism for waking up a waiting client is to write the result on a
per-call queue. We could in principle do the same with a channel, but we have to
sort out the poison semantics and potential overheads etc for this first.

Channel naming service is very simple at the moment: if we don't have an entry
for a given channel name, we query all servers for their list of current
channels. Then, the channel name is looked up again.

Two-way channel hosting over a single connection
------------------------------------------------

If clients want to offer up channels to a server, they can set the can_serve
parameter when connecting to the server, or set it up at a later point in
time. The server will then, additionally, act as a client on the same
connection.

This provides a simple method for writing CSP processes that offer channels to
each other across namespaces.  See the net_commstime_*.py examples to see how
this is done.

TODO/WARNING: Problems with dropped connections
-----------------------------------------------

The two-way connections immediately expose a potential problem!
The problem can be observed in the net_commstime example.

A channel write waits for an ack from the end hosting the channel. The
net_commstime_client.py program should send the ack, but frequently manages to
terminate before the ack is sent across the network connection. The end result
is that net_commstime_server will hang after writing the reply to 'cleanup'. A
cleaner client termination would make sure that acks are transferred before
closing the connection, but this would hide (or ignore) other problems:

- There might be other messages in various states, including reads and writes
  to other channels that have not finished (and may never finish).
- A client might crash, which would not let it terminate cleanly.

At the moment, the workaround is to garbage collect operations by inspecting
any ops waiting for replies over a dropped connection and raise a
ConnectionError for each of them.

Further rambling:
This should expose the problem instead of silently hanging a program, but
raises a deeper issue: how do we transparently handle lost connections?  It is
no longer safe for a process to assume that a channel is a channel.  Receiving
a ProxyChannel requires dealing with connection issues.

One possibility could be to require som ALT-able read/writes on channels, as
well as defining what it means to actually send a full write # with contents
and disappearing before getting the result.  This is something we need to worry
about in the DAO project where the other end might disappear permanently or
temporarily in the middle of operations.  For a temporary disconnect, it's
possible to handle some issues by having an ID of the client and reconnect
the result queue with the client when it reconnects.


Other things to consider
------------------------

NB: From Python 3.7, the recommended way to run asyncio programs is to use
asyncio.run. That function creates a new loop, runs the provided coroutines and
then destroys the loop upon exit.

TODO: - Consider a more sophisticated naming service.
TODO: - Replace the queues with buffered channels?
"""

import asyncio
import json
from apycsp import PoisonException, Channel, ChannelReadEnd, ChannelWriteEnd, Parallel, Spawn


# registry of channels to expose to the net. Keys are the names.
_chan_registry = {}

# Connections to use to reach a remote channel. Indexed by channel name.
_rchan_reg = {}


def register_channel(chan, name):
    # TODO: should check if already existing
    _chan_registry[name] = chan


def unregister_channel(name):
    del _chan_registry[name]


def create_registered_channel(name):
    """Creates a named channel and registers it under the same name"""
    ch = Channel(name)
    register_channel(ch, ch.name)
    return ch


# Inherit from Channel and ChannelEnd to make sure poison propagation works locally as well.
class _RemoteChan(Channel):
    """Proxy object for using a remote channel.
    Only supports simple read/write mechanics at the moment.
    Don't allocate this one directly. Use the get_channel_proxy* functions instead.
    """
    def __init__(self, name, conn):
        super().__init__(name)
        self.conn = conn

    async def _write(self, msg):
        # TODO: check for poison
        return await self.conn.send_recv_cmd(Connection.OP_WRITE, name=self.name, msg=msg)

    async def _read(self):
        # TODO: check for poison
        return await self.conn.send_recv_cmd(Connection.OP_READ, name=self.name)

    async def poison(self):
        # Make sure we poison both the local proxy and the remote channel
        await super().poison()
        return await self.conn.send_recv_cmd(Connection.OP_POISON, name=self.name)


class _RemoteChanProxy(_RemoteChan):
    def __init__(self, name=None, conn=None):
        super().__init__(name, conn)
        self.read  = ChannelReadEnd(self)
        self.write = ChannelWriteEnd(self)


# ############################################################
#
# Connection handling code.
# This handles both the client and server side of connections.
#

class Connection():
    _clconn = {}    # Connections that can act as clients (send commands to the other side)
    _opqueue = {}   # Ops waiting for return values.
    _msgno = 0

    OP_WRITE = 'write'
    OP_READ = 'read'
    OP_POISON = 'poison'
    OP_PING = 'ping'
    OP_PRINT = 'print'
    OP_CHANLIST = 'chanlist'
    OP_REGSERV = 'regserv'

    MSG_KILL = 'kill'   # inserted into a msg queue to kill the stream_writer

    def __init__(self, reader, writer, host_port, host, port, loop=None, will_serve=False):
        self.reader = reader
        self.writer = writer
        self.host_port = host_port
        self.host = host
        self.port = port
        self.wqueue = asyncio.Queue()    # messages to send over the connection
        self.rqueue = asyncio.Queue()    # messages recevied over the connection
        if loop is None:
            loop = asyncio.get_running_loop()
        self.loop = loop
        self.will_serve = will_serve
        self.alive = True

    def _get_msgno(self):
        """Returns a unique message number, for pairing messages with acks"""
        Connection._msgno += 1
        return Connection._msgno

    def set_client(self):
        self._clconn[self.host_port] = self

    def remove_client(self):
        self.alive = False
        print("Removing connection and proxies associated with the connection", self)
        if self.host_port in self._clconn:
            print(" - deleting from _clconn")
            del self._clconn[self.host_port]
        remove_rchans_using_conn(self)
        print("Removing ops waiting for replies on this connection.", self)
        print(self._opqueue)
        todel = {mno : fut for mno, fut in self._opqueue.items() if fut.conn == self}
        print('TODDEL', todel)
        for mno, fut in todel.items():
            del self._opqueue[mno]
            fut.set_result({'connlost': True})

    # Common handlers. We might consider creating PyCSP procs or channels
    # here instead, but we would have to watch for poison (we need to capture
    # and forward it to the client instead of the default behaviour of
    # killing the process).
    async def _stream_writer(self):
        """Drains a queue for a given connection and writes the json strings to the 'writer' stream"""
        while True:
            msg = await self.wqueue.get()
            if msg == self.MSG_KILL:
                print("Got kill token in _stream_writer. Exiting.")
                break
            msg_s = json.dumps(msg) + "\n"
            if self.writer.transport.is_closing():
                print("Lost connection on writer before we could send message.")
                break
            self.writer.write(msg_s.encode())
            await self.writer.drain()
        self.writer.close()
        self.alive = False
        print("_stream_writer done")

    async def _stream_reader(self):
        """Reads lines from the reader stream, converts from json strings to objects and runs a handler
        for incoming messages.
        """
        while True:
            data = await self.reader.readline()
            message = data.decode().strip()
            if message is None or message == '':
                print(f"Probably lost connection - {self.reader.at_eof()=}")
                break
            Spawn(self._msg_handler(json.loads(message)))
        print(f"_stream_reader done {self.reader.at_eof()=}")
        if self.wqueue:
            await self.wqueue.put(self.MSG_KILL)    # put token on output queue to wake up and kill writer
        self.alive = False

    async def run_stream_handlers(self):
        """Typicaly used by server connection handler. Waits for the stream reader and writer to complete"""
        await Parallel(
            self._stream_writer(),
            self._stream_reader())

        # Remove any proxies that use this connection
        self.remove_client()

    async def start_stream_handlers(self):
        """Typicaly used when setting up client connections."""
        Spawn(self.run_stream_handlers())

    async def _op_handler(self, cmd):
        """Interprets and runs the command, waits for and queues the result (including exceptions) on oqueue"""
        op = cmd.get('op', None)
        msgno = cmd['msgno']

        def reply(ack, ret='ack', **kwargs):
            return self.wqueue.put(dict(ack=ack, ret=ret, **kwargs))

        if op in [self.OP_READ, self.OP_WRITE, self.OP_POISON]:
            name = cmd.get('name', None)
            chan = _chan_registry.get(name, None)
            exc = None
            res = None
            try:
                # attempt to read or write to a poisoned channel should throw poison
                if op == 'read':
                    res = await chan.read()
                elif op == 'write':
                    res = await chan.write(cmd['msg'])
                else:
                    res = await chan.poison()
            except PoisonException:
                exc = 'PoisonException'
                print("Tried to run op on poisoned channel", op, chan.name)
            await reply(msgno, res, exc=exc)
            return

        elif op == self.OP_PING:
            await reply(msgno)
            return

        elif op == self.OP_PRINT:
            print("Server was asked to print {}".format(cmd['args']))
            await reply(msgno)
            return

        elif op == self.OP_CHANLIST:
            # List of channel names registered in this server
            chlist = list(_chan_registry.keys())
            # print("Returning channel list", chlist)
            # for ch in _chan_registry.values():
            #    print(ch)
            await reply(msgno, ret=chlist)
            return

        elif op == self.OP_REGSERV:
            # print("Client connection tries to register as server", self.host_port, cmd)
            self.set_client()
            await reply(msgno)
            return

        await reply(msgno, ret=None, err=f'command {op} not recognized')
        print("server handle done for non-req", cmd)

    async def _reply_handler(self, cmd):
        """Pairs the incoming reply with the outgoing request and sets the request's future with the
        incoming msg."""
        msgno = cmd['ack']
        try:
            rq = self._opqueue[msgno]
        except KeyError as e:
            print("Got keyerror for received message", cmd)
            print("  - keys ", self._opqueue.keys())
            print("  -", e)
            raise
        rq.set_result(cmd)

    async def _msg_handler(self, msg):
        if 'op' in msg:
            if not self.will_serve:
                print("WARNING: received op without being set up as server", self, msg)
                return
            return await self._op_handler(msg)
        return await self._reply_handler(msg)

    async def send_recv_cmd(self, op, **cmd):
        """Sends a command to the remote end, and waits for and returns the result."""
        msgno = self._get_msgno()
        cmd['msgno'] = msgno
        cmd['op'] = op

        # First, get a input "queue" for that message.
        # We only need a future for this as only one message will be delivered.
        rq = self.loop.create_future()
        rq.conn = self
        self._opqueue[msgno] = rq
        await self.wqueue.put(cmd)
        res = await rq
        if msgno in self._opqueue:
            del self._opqueue[msgno]  # Delete queue after command is finished. It may have already been removed in case of lost conn.
        if res.get('exc', None) == 'PoisonException':
            raise PoisonException()
        if res.get('connlost', None):
            msg = f"Lost connection while waiting for {cmd} on {self}"
            raise ConnectionError(msg)
        return res['ret']

    async def register_client_as_can_serve(self):
        """For client side connections: send a message to the remote end signifying that this end is
        willing to look up and serve registered channels."""
        print("Setting up client as willing to serve")
        self.will_serve = True
        ret = await self.send_recv_cmd(self.OP_REGSERV)
        return ret

    def __repr__(self):
        return f"<Connection with {self.host_port} alive={self.alive}>"


# ############################################################
#
# Serving clients
#

async def _client_handler(reader, writer):
    """Handler for a incoming connections.
    Spawns coroutines to handle incoming and outgoing messages."""

    host, port = writer.get_extra_info('peername')
    host_port = f"{host}:{port}"
    print("_client_handler creating in/out handler for ", host_port)
    conn = Connection(reader, writer, host_port, host, port, will_serve=True)
    await conn.run_stream_handlers()
    print(f"_client handler finished for conn {conn}\n")


async def start_server(host_port="8890"):
    """Start the remote channel/op server that listens for incoming connections."""
    if ":" in host_port:
        host, port = host_port.split(":")
        port = int(port)
    else:
        host = None
        port = int(host_port)
    serv = await asyncio.start_server(_client_handler, host=host, port=port)
    print("Running server")
    return serv


# ############################################################
#
# Setting up connections from client side.
#

async def setup_client(host_port='127.0.0.1:8890', can_serve=False):
    """Connect to a server. Currently only supports one connection"""
    host, port = host_port.split(":")
    port = int(port)
    reader, writer = await asyncio.open_connection(host, port)
    conn = Connection(reader, writer, host_port, host, port)
    conn.set_client()
    await conn.start_stream_handlers()
    if can_serve:
        await conn.register_client_as_can_serve()
    return conn


async def _find_remote(name):    # noqa E302
    """Find connection for a remote channel."""
    # TODO: this fails if we allow remote channels to move, or if we reconnect to the remote server
    if name in _rchan_reg:
        return _rchan_reg[name]
    for clname, conn in Connection._clconn.items():
        ret = await conn.send_recv_cmd(Connection.OP_CHANLIST)
        print("Registering", ret, "as owned by", clname)
        for rname in ret:
            _rchan_reg[rname] = conn
    return _rchan_reg[name]


def remove_rchans_using_conn(conn):
    global _rchan_reg
    print("Removing remote channels owned by connection", conn)
    tmp = _rchan_reg
    _rchan_reg = {rname: rconn for rname, rconn in _rchan_reg.items() if rconn != conn}

    removed = [(rname, rconn) for rname, rconn in tmp.items() if rname not in _rchan_reg]
    kept = list(_rchan_reg.items())
    print(f"Removed {len(removed)} kept {len(kept)}: ")
    for v in removed:
        print("  - REM  ", v)
    for v in kept:
        print("  - KEPT ", v)


async def get_channel_proxy(name):
    """Returns a remote channel. Use this from within a coroutine or aPyCSP process."""
    conn = await _find_remote(name)
    return _RemoteChanProxy(name, conn=conn)
