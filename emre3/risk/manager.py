"""Risk Manager"""
class RiskManager:
    def __init__(self, config):
        self.config = config
    
    async def initialize(self):
        pass
    
    async def assess(self, signals, market_data):
        return True
    
    async def shutdown(self):
        pass
