import os
import decky
import asyncio

class Plugin:
    async def _main(self):
        self.loop = asyncio.get_event_loop()

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass

    async def _migration(self):
        pass