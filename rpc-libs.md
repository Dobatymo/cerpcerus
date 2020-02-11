-- rpc implementations --

-- dynamically typed --

most json-rpc variants are pretty basic

# CeRPCerus
- eventloop: 'twisted'
- transport layer: 'tcp', 'websocket'
- rpc features: 'bidirectional/symmetric', 'encryption', 'async', 'flow-controlled streams'
- serialization format: 'msgpack'
- language: python

# ticosax/pseud
- rpc features: 'bidirectional/symmetric', 'encryption', 'async', 'sync'
- transport layer: 'ZeroMQ'
- serialization format: 'msgpack'
- eventloop: 'asyncio'
- language: python

# mprpc
- https://github.com/studio-ousia/mprpc
- serialization format: 'msgpack'
- eventloop: 'gevent'
- language: python
- faster than 'zerorpc', 'msgpack-rpc-python'
- rpc features: 'sync'

# zerorpc
- https://www.zerorpc.io/
- https://github.com/0rpc/zerorpc-python
- rpc features: 'streams', 'first-class exceptions', 'heartbeats'
- language: python
- serialization format: 'msgpack'
- transport layer: 'ZeroMQ'

# msgpack-rpc-python
- https://github.com/msgpack-rpc/msgpack-rpc-python
- eventloop: 'tornado'
- serialization format: 'msgpack'
- language: python
- rpc features: 'async', 'pseudo sync'
- can be pseudo async and sync by stopping and starting the reactor repeatedly

# jsonrpc-bidirectional
- https://github.com/bigstepinc/jsonrpc-bidirectional
- language: typescript
- transport layer: 'websocket','webrtc', 'http/1' and more
- rpc features: 'bidirectional/symmetric', 'async'

# python-symmetric-jsonrpc
- async using threads and select.poll. lock'd requests
- language: python
- OLD

# spyne
- language: python
- transport and architecture agnostic

# RPyC
- rpc features: 'bidirectional/symmetric', 'async', 'sync'
- transport layer: 'tls'
- language: python

# circuits
- https://pythonhosted.org/circuits/index.html
- async, more like a framework than a rpc library
- language: python

-- statically typed --

# zeroc-ice/ice
- transport layer: 'tls', 'tcp', 'udp', 'websockets'
- serialization format: 'efficient binary protocol'
- rpc features: 'remote objects', 'async', 'sync', 'batched calls', 'count based flow control'
- licence: 'GPL'
- language: 'C++'
- bindings: many 

# Cap’n Proto
- https://capnproto.org/
- language: C++
- bindings: 'python'
- serialization features: 'Incremental reads', 'Random access', 'mmap', 'Time-traveling RPC'
- https://github.com/capnproto/pycapnp

# smf-rpc
- https://github.com/smfrpc/smf
- language: C++

# gRPC
- https://grpc.io/
- serialization format: 'Protocol Buffers'
- rpc features: 'async calls', 'sync calls', 'sync streams', 'bidirectional streaming'
- transport layer: 'HTTP/2'

# Apache Thrift, ThriftPy2
- https://thrift.apache.org/
