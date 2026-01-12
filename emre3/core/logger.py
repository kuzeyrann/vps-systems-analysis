"""EMRE3 Logger"""
import logging

def setup_logging(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger
