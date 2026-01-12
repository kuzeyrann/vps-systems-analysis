"""EMRE3 Configuration"""
import os

class Config:
    async def load(self):
        pass
    
    async def get(self, key, default=None):
        return os.getenv(key, default)
