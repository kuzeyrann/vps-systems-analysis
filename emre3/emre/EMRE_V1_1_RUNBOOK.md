cat > /opt/emre/EMRE_V1_1_RUNBOOK.md <<'EOF'
# EMRE v1.1 Runbook (Modüler Core + Adapter Bağımlılıkları)

Tarih: $(date -Is)
Konum: /opt/emre

## Amaç
Bu paket, EMRE’nin sahada çalışan v1.1 sürümüdür. Bu sürümün hedefi:
- Entry üretimi + TP1 mikro momentum doğrulaması
- Reverse Authority (ters işlem) ile çıkış zekâsı
- Stop/TP üretiminin modüler hale getirilmesi
- Sistemin tek bir tar.gz ile anlaşılabilir ve yeniden kurulabilir olması

## Çalışan Dizilim (Gerçek)
### Modüler çekirdek (asıl mimari)
- app.py: giriş noktası, core’u çalıştırır
- core/: state + router
- market/: market/memory normalize (MarketAdapter)
- signals/: entry sinyali üretimi
- tp1/: TP1 modülü (dokunulmadı / korunuyor)
- risk/: stop + tp2/3/4 üretimi ve risk güncelleme mekanizması
- notifier/: bildirim/telemetri
- exit/: reverse authority ve leg-local mikro TP1 gibi yardımcılar

### Adapter/Legacy ama hala kullanılan bağımlılıklar (SİLİNEMEZ)
Bu dosyalar “legacy gibi görünse de” fiilen import edildiği için bu sürümde zorunludur:
- emre_market.py
  - market/market.py içinde `from emre_market import EmreMarket` bağımlılığı vardı/var.
- telegram_sender.py
  - notifier/notifier.py içinde `from telegram_sender import send_message` bağımlılığı vardı/var.
- emre_tp_micro.py
  - TP1 mikro momentum mantığında (bazı senaryolarda) kullanılır.
- emre_trader.py, emre_levels.py
  - yardımcı/hesap bileşenleri. Bazı akışlarda çağrılabilir.

Not: Bu adapter bağımlılıkları ileri refactor ile paket içi modüllere taşınabilir; ancak v1.1’de amaç stabilite olduğu için korunur.

## Reverse Authority Model (Kilitli Kural)
- Long açıkken Short entry gelirse: Short pozisyon AÇILIR, Long açık kalır.
- Short TP1 geldiği anda: Long TAM KAPATILIR (PnL bakılmaz).
- Simetri: Short açıkken Long entry -> Long aç; Long TP1 -> Short kapat.
- Aynı anda en fazla iki leg (1 long + 1 short).

## Stop / TP üretimi (v1.1 durumu)
- TP1: güçlü, mikro momentum doğrulayıcı (korunuyor)
- Stop: phase-aware denendi; RANGE rejiminde agresif tighten stop-out yaratabildi.
- Risk update (15dk): bazı testlerde stop’u fazla erken sıkılaştırdı ve TP setlerini anlamsızlaştırabildi.
  Bu nedenle v1.1 saha testinde risk-update ya kapatılmalı ya da koşullu hale getirilmeli:
  - RANGE’de update yok / çok sınırlı
  - TREND’de şartlı update (blend, monotonic)

## Bilinen Sorunlar / Yapılan Yanlışlar (Öğrenimler)
1) Temizlik sırasında adapter bağımlılıklarının “legacy sanılıp taşınması/silinmesi”
   - Sonuç: ModuleNotFoundError (emre_market / telegram_sender)
   - Ders: “mantıksal mimari” ile “fiili import bağımlılıkları” ayrımı yapılmadan temizlik yapılmaz.
2) Risk update’in RANGE rejiminde stop’u agresif sıkılaştırması
   - Sonuç: küçük salınımlarda stop-out ve katma değer üretmeyen güncellemeler
   - Ders: update = “yeniden hesap” değil, rejime göre “kontrollü/monoton” ilerletme olmalı.
3) TP3/TP4’ün bazen stop/R-multiple türevi olması
   - Sonuç: hedeflerin güncellemelerde geri kayması/karışması
   - Ders: TP2 “executable”, TP3/TP4 “structure/liquidity map” olarak stop’tan bağımsız tasarlanmalı.

## Kurulum Notları
- systemd unit: /etc/systemd/system/emre.service
- env dosyası: /opt/emre/.env
- log: /var/log/emre.log (append)

## Test Checklist
- Servis başlıyor mu? `systemctl status emre.service`
- Log akıyor mu? `tail -f /var/log/emre.log`
- OPEN -> TP1_EVENT görülüyor mu?
- Long açıkken short entry gelince short açılıyor mu?
- Karşı TP1 gelince diğer leg kapanıyor mu?

EOF
