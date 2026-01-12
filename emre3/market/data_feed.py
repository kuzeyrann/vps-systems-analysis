"""Simple Data Feed"""
import random

class DataFeed:
    def __init__(self, config):
        self.config = config
    
    async def initialize(self):
        pass
    
    async def get_latest(self):
        return {'close': 90000 + random.randint(-1000, 1000)}
    
    def get_current_price(self):
        return 90000 + random.randint(-1000, 1000)
    
    async def shutdown(self):
        pass
