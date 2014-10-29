# CeRPCerus

## What is CeRPCerus?

It's a Remote Call Procedure library written in and for Python.

## Why is it better than similar RPC libraries?

* emphasis on security: all communication is encrypted and authenticated
* based on p2p: it doesn't need central servers
* symmetric: there is no difference between servers and clients
* low overhead: fast serialization and small messages
* completely asychronous: no time is wasted on waiting for an reply
* it supports remote functions and objects
* simple api: it's almost as easy to use as local calls

## Technical details

* uses TLS and X.509 certificates for encryption and authentication (using *pyOpenSSL*)
* asynchronous networking via *Twisted*, async replies are given as Twisted deferreds
* uses *MessagePack* as serializer
* compact code and no unneccessary features make it easier to understand and to check for errors
