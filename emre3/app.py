#!/usr/bin/env python3
import sys
import os

# Python yolunu ayarla
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.core import run
    print("✅ Import başarılı")
    run()
except Exception as e:
    print(f"❌ Hata: {e}")
    import traceback
    traceback.print_exc()
