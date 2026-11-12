"""Deny Python socket network access during inference, including downloader calls."""
from contextlib import contextmanager
import socket

@contextmanager
def deny_network():
    def denied(*args,**kwargs): raise RuntimeError('Network is disabled during model inference; stage all assets first')
    names=('connect','connect_ex','sendto')
    old={name:getattr(socket.socket,name) for name in names}
    old_create=socket.create_connection
    try:
        for name in names:setattr(socket.socket,name,denied)
        socket.create_connection=denied
        yield
    finally:
        for name,method in old.items():setattr(socket.socket,name,method)
        socket.create_connection=old_create
