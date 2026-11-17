"""Run the app's own async code (lib.* functions that use the shared Motor client) from an ordinary, non-async test.

Motor's client keeps the first event loop that used it (motor/core.py, `io_loop`), and every later call must run on that same loop. So this helper always runs on the loop the
client already belongs to, and makes a new one only when the client has none yet or its loop was closed (the old owner is gone, so nothing else can be using it). Every in-process
test in this suite goes through here; a test keeping a loop of its own would break whichever of them ran second in the same process."""

import asyncio


def _client_loop() -> asyncio.AbstractEventLoop:
    from lib import db as dbmod

    loop = dbmod.client._io_loop
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        dbmod.client._io_loop = loop
    return loop


async def _await(awaitable):
    return await awaitable


def run(awaitable, timeout: float = 120):
    """Run a coroutine or any awaitable (Motor returns futures for some calls) on the client's loop and return its result."""
    return _client_loop().run_until_complete(asyncio.wait_for(_await(awaitable), timeout))
