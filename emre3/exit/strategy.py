"""Exit Strategy"""
class ExitStrategy:
    def __init__(self, config):
        self.config = config
    async def initialize(self): pass
    async def monitor(self, trades): pass
    async def shutdown(self): pass
