# CeRPCerus

## What is CeRPCerus?

It's a Remote Call Procedure library written in and for Python. It is intented to be generic yet convenient enough to make development of all kinds of network applications easier.

## Why the name?

Because it's hopefully better than Fluffy at protecting secrets... Also it's easy to google.

## Why is it better than similar RPC libraries?

* emphasis on security: all communication is encrypted and authenticated
* based on p2p: it doesn't need central servers
* symmetric: there is no difference between servers and clients
* low overhead: fast serialization and small messages
* it supports remote functions _and objects_
* completely asychronous:
	* no time is wasted on waiting for a reply
	* methods can even be called on objects which are not fully instantiated yet (pending)
* flow controlled: data can be streamed without using up too much memory and adapting to network bandwidth (currently sending only)
* simple api: it's almost as easy to use as local calls

## Technical details

* uses TLS and X.509 certificates for encryption and authentication (using *pyOpenSSL*)
* asynchronous networking via *Twisted*, async replies are given as Twisted *deferreds*
* uses *MessagePack* as serializer
* supports *WebSockets* as optional custom transport layer
* compact code and no unneccessary features make it easier to understand and to check for errors
