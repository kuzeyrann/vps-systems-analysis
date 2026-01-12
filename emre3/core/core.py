from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Config
from core.position import Leg, Position
from core.logger import setup_logging
from market.data_feed import DataFeed
from signals.generator import SignalGenerator
from risk.manager import RiskManager
from exit.strategy import ExitStrategy
from tp1.executor import TP1Executor
from notifier.telegram import TelegramNotifier


class EmreCore:
    """EMRE Core Trading System - Version 1.2"""
    
    def __init__(self, symbol: str = "BTCUSDT"):
        self._last_stop_long = 0
        self._last_stop_short = 0
        self.symbol = symbol
        self.config = Config()
        self.logger = setup_logging("EMRE3-Core")
        
        # State management
        self.state_file = os.path.join(os.path.dirname(__file__), "position_state.json")
        self.position = Position()
        self.active_trades: List[Dict] = []
        
        # === SPAM DÜZELTMESİ 1/3 ===
        # Cooldown değişkenleri eklendi
        self._last_stop_warn_long = 0
        self._last_stop_warn_short = 0
        self._last_heartbeat = 0
        
        # Trading components
        self.data_feed: Optional[DataFeed] = None
        self.signal_generator: Optional[SignalGenerator] = None
        self.risk_manager: Optional[RiskManager] = None
        self.exit_strategy: Optional[ExitStrategy] = None
        self.tp1_executor: Optional[TP1Executor] = None
        self.notifier: Optional[TelegramNotifier] = None
        
        # Trading parameters
        self.loop_sleep = int(os.getenv("EMRE3_LOOP_SLEEP", "10"))
        self.heartbeat_interval = int(os.getenv("EMRE3_HEARTBEAT_INT", "60"))
        
        # Load existing state
        self.load_state()
    
    def load_state(self) -> None:
        """Load position state from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                
                # Load position
                if 'position' in state:
                    pos_data = state['position']
                    
                    # Load long leg
                    if 'long' in pos_data and pos_data['long']['is_open']:
                        long_data = pos_data['long']
                        self.position.long = Leg(
                            is_open=long_data['is_open'],
                            side=long_data.get('side', 'LONG'),
                            entry=long_data['entry'],
                            stop=long_data['stop'],
                            opened_ts=long_data.get('opened_ts', 0),
                            risk_set_id=long_data.get('risk_set_id', ''),
                            last_risk_update_ts=long_data.get('last_risk_update_ts', 0),
                            tp_hits=long_data.get('tp_hits', {"TP1": False, "TP2": False, "TP3": False, "TP4": False}),
                            stop_touched=long_data.get('stop_touched', False),
                            stop_touch_ts=long_data.get('stop_touch_ts', 0),
                            stop_touch_price=long_data.get('stop_touch_price', 0.0)
                        )
                    
                    # Load short leg
                    if 'short' in pos_data and pos_data['short']['is_open']:
                        short_data = pos_data['short']
                        self.position.short = Leg(
                            is_open=short_data['is_open'],
                            side=short_data.get('side', 'SHORT'),
                            entry=short_data['entry'],
                            stop=short_data['stop'],
                            opened_ts=short_data.get('opened_ts', 0),
                            risk_set_id=short_data.get('risk_set_id', ''),
                            last_risk_update_ts=short_data.get('last_risk_update_ts', 0),
                            tp_hits=short_data.get('tp_hits', {"TP1": False, "TP2": False, "TP3": False, "TP4": False}),
                            stop_touched=short_data.get('stop_touched', False),
                            stop_touch_ts=short_data.get('stop_touch_ts', 0),
                            stop_touch_price=short_data.get('stop_touch_price', 0.0)
                        )
                
                # Load active trades
                if 'active_trades' in state:
                    self.active_trades = state['active_trades']
                
                self.logger.info(f"State loaded: LONG={self.position.has_long}, SHORT={self.position.has_short}")
                
        except Exception as e:
            self.logger.error(f"Error loading state: {e}")
            # Reset to clean state
            self.position = Position()
            self.active_trades = []
    
    def save_state(self) -> None:
        """Save current position state to file"""
        try:
            state = {
                'position': {
                    'long': asdict(self.position.long),
                    'short': asdict(self.position.short)
                },
                'active_trades': self.active_trades,
                'last_saved': time.time()
            }
            
            # Create backup of old state
            if os.path.exists(self.state_file):
                backup_file = self.state_file + '.backup'
                with open(backup_file, 'w') as f:
                    json.dump(state, f, indent=2)
            
            # Save new state
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
                
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")
    
    def is_near_stop(self, current_price: float, side: str) -> bool:
        """Check if price is near stop level (within 0.1%)"""
        if side == "LONG" and self.position.has_long:
            stop_price = self.position.long.stop
            if stop_price > 0:
                distance_pct = abs(current_price - stop_price) / stop_price
                return distance_pct <= 0.001  # Within 0.1%
        
        elif side == "SHORT" and self.position.has_short:
            stop_price = self.position.short.stop
            if stop_price > 0:
                distance_pct = abs(current_price - stop_price) / stop_price
                return distance_pct <= 0.001  # Within 0.1%
        
        return False
    
    def send_stop_warning(self, side: str) -> None:
        # Spam önleme
        import time
        current_time = time.time()
        if side == "LONG":
            if hasattr(self, "_last_stop_long") and current_time - self._last_stop_long < 60:
                return
            self._last_stop_long = current_time
        else:
            if hasattr(self, "_last_stop_short") and current_time - self._last_stop_short < 60:
                return
            self._last_stop_short = current_time
        """Send stop warning notification"""
        # === SPAM DÜZELTMESİ 2/3 ===
        # 60 saniye cooldown kontrolü
        current_time = time.time()
        if side == "LONG":
            if current_time - self._last_stop_warn_long < 60:
                return
        else:  # SHORT
            if current_time - self._last_stop_warn_short < 60:
                return
        
        # Orjinal kod (aşağıdaki kısım DEĞİŞMEDİ)
        if side == "LONG" and self.position.has_long:
            leg = self.position.long
            current_price = self.data_feed.get_current_price() if self.data_feed else 0
            message = (
                f"[EMRE3-TEST] 🔴 STOP TOUCH LONG\n"
                f"Price: {current_price:.2f}\n"
                f"Entry: {leg.entry:.2f} → Stop: {leg.stop:.6f}"
            )
            
            if self.notifier:
                asyncio.create_task(self.notifier.send_message(message))
            
            # === SPAM DÜZELTMESİ 3/3 ===
            self._last_stop_warn_long = current_time
            self.logger.warning(f"Stop warning sent for LONG position (cooldown active)")
        
        elif side == "SHORT" and self.position.has_short:
            leg = self.position.short
            current_price = self.data_feed.get_current_price() if self.data_feed else 0
            message = (
                f"[EMRE3-TEST] 🔴 STOP TOUCH SHORT\n"
                f"Price: {current_price:.2f}\n"
                f"Entry: {leg.entry:.2f} → Stop: {leg.stop:.6f}"
            )
            
            if self.notifier:
                asyncio.create_task(self.notifier.send_message(message))
            
            # === SPAM DÜZELTMESİ 3/3 ===
            self._last_stop_warn_short = current_time
            self.logger.warning(f"Stop warning sent for SHORT position (cooldown active)")
    
    def send_heartbeat(self) -> None:
        """Send heartbeat notification"""
        current_time = time.time()
        
        # Cooldown kontrolü
        if current_time - self._last_heartbeat < self.heartbeat_interval:
            return
        
        price = self.data_feed.get_current_price() if self.data_feed else 0
        message = (
            f"🔧 [EMRE3-TEST] [HEARTBEAT] price={price:.2f} "
            f"has_long={self.position.has_long} has_short={self.position.has_short}"
        )
        
        if self.notifier:
            asyncio.create_task(self.notifier.send_message(message))
        
        self._last_heartbeat = current_time
        self.logger.debug(f"Heartbeat sent: price={price}")
    
    async def initialize(self) -> bool:
        """Initialize all system components"""
        try:
            self.logger.info(f"Initializing EMRE Core for {self.symbol}")
            
            # Load configuration
            await self.config.load()
            
            # Initialize components
            self.data_feed = DataFeed(self.config)
            self.signal_generator = SignalGenerator(self.config)
            self.risk_manager = RiskManager(self.config)
            self.exit_strategy = ExitStrategy(self.config)
            self.tp1_executor = TP1Executor(self.config)
            self.notifier = TelegramNotifier(self.config)
            
            # Initialize each component
            await self.data_feed.initialize()
            await self.signal_generator.initialize()
            await self.risk_manager.initialize()
            await self.exit_strategy.initialize()
            await self.tp1_executor.initialize()
            await self.notifier.initialize()
            
            self.logger.info("All components initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False
    
    async def trading_cycle(self) -> None:
        """Execute one trading cycle"""
        try:
            # Get market data
            if not self.data_feed:
                self.logger.error("Data feed not initialized")
                return
            
            market_data = await self.data_feed.get_latest()
            if not market_data:
                self.logger.warning("No market data received")
                return
            
            current_price = market_data.get('close', 0)
            
            # Check stop warnings
            if self.position.has_long and self.is_near_stop(current_price, "LONG"):
                self.send_stop_warning("LONG")
            
            if self.position.has_short and self.is_near_stop(current_price, "SHORT"):
                self.send_stop_warning("SHORT")
            
            # Send heartbeat
            self.send_heartbeat()
            
            # Generate signals
            if self.signal_generator:
                signals = await self.signal_generator.generate(market_data)
                
                # Risk assessment
                if self.risk_manager:
                    risk_approved = await self.risk_manager.assess(signals, market_data)
                    
                    if risk_approved and self.tp1_executor:
                        # Execute trades
                        trades = await self.tp1_executor.execute(signals, market_data)
                        
                        # Monitor and exit
                        if trades and self.exit_strategy:
                            await self.exit_strategy.monitor(trades)
            
            # Update system state
            self.save_state()
            
        except Exception as e:
            self.logger.error(f"Trading cycle error: {e}")
    
    async def run(self) -> None:
        """Main trading loop"""
        self.logger.info(f"Starting EMRE Core trading loop for {self.symbol}")
        
        # Initialize components
        if not await self.initialize():
            self.logger.error("Failed to initialize system")
            return
        
        self.logger.info("EMRE Core started successfully")
        
        try:
            while True:
                await self.trading_cycle()
                await asyncio.sleep(self.loop_sleep)
                
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received")
        except Exception as e:
            self.logger.error(f"System error: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self) -> None:
        """Graceful shutdown"""
        self.logger.info("Shutting down EMRE Core...")
        
        # Save final state
        self.save_state()
        
        # Shutdown components
        components = [
            self.notifier,
            self.tp1_executor,
            self.exit_strategy,
            self.risk_manager,
            self.signal_generator,
            self.data_feed
        ]
        
        for component in components:
            if component:
                try:
                    await component.shutdown()
                except Exception as e:
                    self.logger.error(f"Error shutting down component: {e}")
        
        self.logger.info("EMRE Core shutdown complete")


def run() -> None:
    """Main entry point for EMRE Core"""
    # Load environment
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[CORE] .env yüklendi. TOKEN: {'VAR' if os.getenv('TELEGRAM_BOT_TOKEN') else 'YOK'}")
    else:
        print("[CORE] .env bulunamadı")
    
    print("=== EMRE3 TEST (BB Sendromu Fix) başlatılıyor ===")
    print("=== Daralan piyasa filtresi AKTİF ===")
    print("=== Bollinger band farkındalığı AKTİF ===")
    print("=== SPAM DÜZELTMESİ AKTİF (60sn cooldown) ===")
    print("=== EMRE Core (v1 modular) started ===")
    
    # Create and run EMRE Core
    core = EmreCore(symbol=os.getenv("EMRE_SYMBOL", "BTCUSDT"))
    
    # Run in async context
    asyncio.run(core.run())


if __name__ == "__main__":
    run()
