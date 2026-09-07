# Supnex Mod Bot

Gelişmiş moderasyon + ticket + guard botu. Tamamı Türkçe, yüksek özelleştirilebilir.

## Kurulum

```bash
pip install -r requirements.txt
```

`.env` dosyası oluştur (veya verileni kullan):

```
DISCORD_TOKEN=bot_token
OWNER_ID=1416454556165869568
```

Sonra:

```bash
python main.py
```

## Komutlar

### Ticket sistemi
- `/talep-kur [yetkili:rol]` — Tek komut: kategori (TALEPLER) + panel kanalı (talep-panel) + log kanalı (talep-log) + panel mesajı otomatik kurulur
- `/talep-panel` — Panel mesajının düzenini modal ile değiştir: **başlık, açıklama, görsel URL (fotoğraf), alt bilgi, renk**. Kaydedince panel anında yenilenir
- `/talep-kategori <kategori>` — Taleplerin açılacağı kategoriyi değiştir
- `/talep-yetkili <rol>` — Yetkili/destek rolünü değiştir
- `/talep-konular <a,b,c>` — Talep konu listesini değiştir (20'ye kadar)
- `/talep-kapat [kanal]` — Talebi kapat (transkript log kanalına kaydedilir, kanal silinir)
- `/taleplerikapat` — Tüm açık talepleri kapatar
- `/talep-transkript [kanal]` — Kanalın transkriptini log kanalına atar
- `/talep-gor` — Yapılandırma ve istatistik

Panel kalıcıdır (persistent view): bot yeniden başlasa bile konu seçici ve butonlar çalışır.
İş akışı: panelden konu seç → özel talep kanalı açılır → "Talebi Kapat" / "Transkript" butonları → kapatınca HTML transkript log kanalına düşer.

### Guard sistemi (`/guard ...`)
- `/guard durum` — Durum
- `/guard ac` / `/guard kapat` — Aç-kapa
- `/guard koruma <ban|kanal|rol|raid> <acik|kapali>` — Tek koruma
- `/guard yetkili <uye> [ekle|cikar]` — Beyaz liste

Anti-raid: 10 saniyede 5+ katılım görürse banlar. Ban/kanal/rol koruması denetim günlüğüyle yetkisiz işlemleri geri alır.

### Loglama
- `/log-kanal <kanal>` — Log kanalı belirle
- `/log-gecmis [adet]` — Log geçmişi (sayfalı)

Olaylar: katılma/ayrılma, mesaj silme/düzenleme, isim değişimi, rol değişimi, kanal/rol oluşturma ve silme.

### Moderasyon (`/mod-rol` ile yetki ver, veya ban/manage yeterli)
- `/at`, `/ban`, `/ban-kaldir`
- `/sustur <uye> <sure>` (10dk, 2sa, 30sn), `/sustur-kaldir`
- `/uyar`, `/uyarilar`, `/uyartemizle`
- `/temizle <adet>` (max 100)
- `/kilit`, `/kilit-ac`, `/yavasmod <saniye>`
- `/rol-ver`, `/rol-al`

### Sahip komutları
- `/sunucular` — Sunucu listesi
- `/kapat` — Botu kapat

## Notlar

- Slash komut adları ASCII olmak zorunda, bu yüzden Türkçe karakter yok (ör. `kilit-ac`, `uyartemizle`).
- Veriler `data/modbot.db` (SQLite). Transkript geçmişi DB'de, geçici dosyalar `transcripts/` altındadır (gitignore'lu).