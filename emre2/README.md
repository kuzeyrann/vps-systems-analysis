EMRE-2 (Regime-Aware Bot) - FULL (paper trades)
==============================================

- Runs alongside existing /opt/emre
- Opens/closes simulated positions (state.json) and sends Telegram updates
- Fetches market data from Binance Futures public API

Install
-------
1) Extract to / (creates /opt/emre2 and /etc/systemd/system/emre2.service)
2) Create /opt/emre2/.env (copy from .env.example)
3) Install deps:
   apt update && apt install -y python3-requests
4) Start:
   systemctl daemon-reload
   systemctl enable emre2
   systemctl restart emre2
5) Logs:
   tail -f /var/log/emre2.log

Safety
------
- This build does NOT place real exchange orders.
- "Trade opens" are internal (logs + Telegram). Suitable for observation.
