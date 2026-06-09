"""Lightweight EN/TR translations for the admin panel."""

from __future__ import annotations

from flask import request, session

SUPPORTED_LOCALES = frozenset({"en", "tr"})
DEFAULT_LOCALE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    # Header / actions
    "app.title": {"en": "AutoTube Admin", "tr": "AutoTube Yönetim"},
    "action.sync": {"en": "Sync", "tr": "Senkron"},
    "action.schedule": {"en": "Schedule", "tr": "Planla"},
    "action.upload": {"en": "Upload", "tr": "Yükle"},
    "action.produce": {"en": "Produce", "tr": "Üret"},
    "action.run": {"en": "Run", "tr": "Çalıştır"},
    "action.retry": {"en": "Retry", "tr": "Yeniden dene"},
    "action.retry_selected": {"en": "Retry selected", "tr": "Seçilenleri yeniden dene"},
    "action.retry_all_failed": {"en": "Retry failed", "tr": "Hatalıları yeniden dene"},
    "action.delete": {"en": "Delete", "tr": "Sil"},
    "action.delete_selected": {"en": "Delete selected", "tr": "Seçilenleri sil"},
    "action.select_all": {"en": "Select all", "tr": "Tümünü seç"},
    "action.clear_selection": {"en": "Clear", "tr": "Temizle"},
    "action.select": {"en": "Select", "tr": "Seç"},
    "action.connect": {"en": "Connect", "tr": "Bağla"},
    "action.create": {"en": "Create", "tr": "Oluştur"},
    "action.open": {"en": "Open →", "tr": "Aç →"},
    "action.reset_stuck": {"en": "Reset stuck", "tr": "Takılı sıfırla"},
    "action.trim_seo": {"en": "Trim SEO", "tr": "Kısalt"},
    "action.save": {"en": "Save", "tr": "Kaydet"},
    "action.save_seo": {"en": "Save SEO", "tr": "SEO kaydet"},
    "action.switch_account": {"en": "Switch account", "tr": "Hesap değiştir"},
    "action.remove_channel": {"en": "Remove", "tr": "Kaldır"},
    "label.active": {"en": "active", "tr": "aktif"},
    "label.connected": {"en": "connected", "tr": "bağlı"},
    "label.not_connected": {"en": "not connected", "tr": "bağlı değil"},
    "label.queued": {"en": "Queued", "tr": "Sırada"},
    "label.job_active": {"en": "Active", "tr": "Üretimde"},
    "label.voice": {"en": "Voice", "tr": "Ses"},
    "label.niche": {"en": "Niche", "tr": "Niche"},
    # Stats
    "stat.pending": {"en": "Pending", "tr": "Bekleyen"},
    "stat.processing": {"en": "Processing", "tr": "Üretimde"},
    "stat.ready": {"en": "Ready", "tr": "Hazır"},
    "stat.youtube": {"en": "YouTube", "tr": "YouTube"},
    "stat.failed": {"en": "Failed", "tr": "Hata"},
    # Banners
    "banner.producing": {"en": "Producing", "tr": "Üretiliyor"},
    "banner.production_progress": {
        "en": "Production in progress",
        "tr": "Üretim devam ediyor",
    },
    "banner.uploading": {"en": "Uploading to YouTube", "tr": "YouTube'a yükleniyor"},
    "banner.job": {"en": "job", "tr": "iş"},
    "banner.queued": {"en": "queued", "tr": "sırada"},
    "banner.more_in_queue": {"en": "more in queue", "tr": "kuyrukta daha"},
    # Sections
    "section.production": {"en": "Production — add topics", "tr": "Üretim — konu ekle"},
    "section.single_topic": {"en": "Single topic", "tr": "Tek konu"},
    "section.ai_topics": {"en": "AI weekly topics", "tr": "AI haftalık konu"},
    "section.bulk_topics": {"en": "Bulk topics (one per line)", "tr": "Toplu konu (satır başına bir)"},
    "section.queue": {"en": "Production queue", "tr": "Üretim kuyruğu"},
    "label.schedule_auto": {"en": "Auto schedule", "tr": "Otomatik planlama"},
    "help.schedule_mode": {
        "en": "Active rule: {summary}. One ready video per calendar day per channel (occupied days skipped).",
        "tr": "Aktif kural: {summary}. Kanal başına takvim gününde bir hazır video (dolu günler atlanır).",
    },
    "help.schedule_change": {
        "en": "Change default in .env (SCHEDULE_*), restart app. Per video: Ready → Edit & schedule.",
        "tr": "Varsayılan: .env (SCHEDULE_*), uygulamayı yeniden başlat. Tek video: Hazır → Düzenle & planla.",
    },
    "help.queue_retry": {
        "en": "Produce runs pending jobs only. Failed jobs need Retry (row) or Retry failed (header). Nothing runs automatically unless you click Produce or Retry.",
        "tr": "Üret yalnızca bekleyen işleri çalıştırır. Hatalı işler için satırdaki Yeniden dene veya üstteki Hatalıları yeniden dene kullanın. Otomatik tetikleme yoktur.",
    },
    "section.ready": {"en": "Ready videos", "tr": "Hazır videolar"},
    "section.ready_flow": {"en": "SEO → schedule → upload", "tr": "SEO → planla → yükle"},
    "section.on_youtube": {"en": "On YouTube", "tr": "YouTube'da"},
    "section.on_youtube_hint": {
        "en": "Newest first · click to expand",
        "tr": "En yeni üstte · açmak için tıkla",
    },
    "section.settings": {"en": "Channels & settings", "tr": "Kanal & ayarlar"},
    "section.settings_hint": {
        "en": "YouTube OAuth · backgrounds · new channel",
        "tr": "YouTube bağlantısı · arka plan · yeni kanal",
    },
    "section.youtube_accounts": {"en": "YouTube accounts", "tr": "YouTube hesapları"},
    "help.youtube_accounts": {
        "en": "Each panel channel = one YouTube account. To add a 3rd account, create a new channel below, then sign in with another Google account.",
        "tr": "Her panel kanalı = bir YouTube hesabı. 3. hesap için aşağıdan yeni kanal oluşturun, sonra farklı Google hesabıyla bağlayın.",
    },
    "section.add_channel": {
        "en": "Add another channel",
        "tr": "Yeni kanal ekle",
    },
    "section.background": {"en": "Background video", "tr": "Arka plan videosu"},
    "section.new_channel": {"en": "New channel", "tr": "Yeni kanal"},
    "section.oauth_info": {"en": "OAuth / technical info", "tr": "OAuth / teknik bilgi"},
    # Placeholders / forms
    "placeholder.topic": {"en": "Video topic…", "tr": "Video konusu…"},
    "placeholder.bulk": {"en": "Topic 1\nTopic 2\n…", "tr": "Konu 1\nKonu 2\n…"},
    "placeholder.panel_name": {"en": "Panel name", "tr": "Panel adı"},
    "placeholder.niche": {"en": "niche (e.g. motivation)", "tr": "niche (ör. motivation)"},
    "placeholder.pick_niche": {"en": "Choose a niche…", "tr": "Niche seçin…"},
    "placeholder.tone": {"en": "Tone rules for the AI", "tr": "AI ton kuralları"},
    "help.niche_voice": {
        "en": "Voice for {niche} niche: {voice} (set in config/niches.json)",
        "tr": "{niche} niche sesi: {voice} (config/niches.json)",
    },
    "help.new_channel_niche": {
        "en": "Voice and AI rules come from the niche profile — edit config/niches.json to customize.",
        "tr": "Ses ve AI kuralları niche profilinden gelir — config/niches.json dosyasını düzenleyin.",
    },
    "section.channel_voice": {"en": "Channel voice", "tr": "Kanal sesi"},
    "form.use_niche_voice": {
        "en": "Use niche default ({voice})",
        "tr": "Niche varsayılanı ({voice})",
    },
    "help.channel_voice": {
        "en": "Default comes from config/niches.json for this niche. Pick another voice to override only this channel.",
        "tr": "Varsayılan bu niche için config/niches.json'dan gelir. Sadece bu kanal için başka ses seçebilirsiniz.",
    },
    "form.add_queue": {"en": "Add to queue", "tr": "Kuyruğa ekle"},
    "form.generate_topics": {"en": "Generate topics", "tr": "Konuları üret"},
    "form.add_all": {"en": "Add all", "tr": "Toplu ekle"},
    "form.run_after": {"en": "Start production after adding", "tr": "Ekleyince üret"},
    "form.connect_after": {"en": "Connect YouTube after create", "tr": "Oluşturunca YouTube bağla"},
    "form.edit_schedule": {"en": "Edit & schedule", "tr": "Düzenle & planla"},
    "form.awaiting_schedule": {"en": "awaiting schedule", "tr": "plan bekliyor"},
    "form.on_youtube_label": {"en": "On YouTube", "tr": "YouTube'da"},
    # Empty states
    "empty.queue": {"en": "Queue is empty — add topics above.", "tr": "Kuyruk boş — üstten konu ekle."},
    "empty.ready": {"en": "No ready videos yet.", "tr": "Hazır video yok."},
    "empty.youtube": {"en": "No published videos yet.", "tr": "Henüz yayınlanmış video yok."},
    "empty.no_channel": {"en": "No channel", "tr": "Kanal yok"},
    # Confirm
    "confirm.delete_job": {"en": "Delete this job?", "tr": "Bu iş silinsin mi?"},
    "confirm.delete_jobs_bulk": {
        "en": "Delete {n} selected video(s)? Local files will be removed. This cannot be undone.",
        "tr": "Seçili {n} video silinsin mi? Yerel dosyalar kaldırılır. Geri alınamaz.",
    },
    "confirm.delete_channel": {
        "en": "Remove channel \"{name}\" and all its videos from the panel? YouTube uploads stay on YouTube. This cannot be undone.",
        "tr": "\"{name}\" kanalı ve tüm kuyruk videoları panelden silinsin mi? YouTube'daki yüklemeler kalır. Geri alınamaz.",
    },
    # OAuth page
    "oauth.redirect_uri": {
        "en": "Redirect URI (must match Google Cloud Console):",
        "tr": "Redirect URI (Google Console ile aynı olmalı):",
    },
    "oauth.panel_url": {"en": "Panel URL:", "tr": "Panel URL:"},
    # Job status
    "status.PENDING": {"en": "Pending", "tr": "Bekliyor"},
    "status.GENERATING_TEXT": {"en": "Writing script", "tr": "Metin üretiliyor"},
    "status.GENERATING_AUDIO": {"en": "Generating audio", "tr": "Ses üretiliyor"},
    "status.RENDERING": {"en": "Rendering", "tr": "Render"},
    "status.READY_TO_UPLOAD": {"en": "Ready", "tr": "Hazır"},
    "status.COMPLETED": {"en": "On YouTube", "tr": "YouTube'da"},
    "status.FAILED": {"en": "Failed", "tr": "Hata"},
    "badge.scheduled_upload": {"en": "Scheduled — upload", "tr": "Planlandı — yükle"},
    "badge.awaiting_schedule": {"en": "Awaiting schedule", "tr": "Plan bekliyor"},
    # Flash messages
    "flash.stuck_reset": {
        "en": "{n} stuck job(s) reset — run Produce again.",
        "tr": "{n} takılı iş sıfırlandı — tekrar Üret.",
    },
    "flash.no_stuck": {"en": "No stuck jobs to reset.", "tr": "Sıfırlanacak takılı iş yok."},
    "flash.channel_topic_required": {
        "en": "Channel and topic are required.",
        "tr": "Kanal ve konu zorunludur.",
    },
    "flash.added_queue": {
        "en": "Video added to queue. Schedule after production completes.",
        "tr": "Video kuyruğa eklendi. Üretimden sonra planlayın.",
    },
    "flash.select_channel": {"en": "Select a channel.", "tr": "Kanal seçin."},
    "flash.topics_failed": {
        "en": "Could not generate topics: {err}",
        "tr": "Konu üretilemedi: {err}",
    },
    "flash.topics_added": {
        "en": "{label}: {n} topic(s) generated and queued. {hint}",
        "tr": "{label}: {n} konu üretildi ve kuyruğa eklendi. {hint}",
    },
    "flash.hint_starting": {"en": "Starting production…", "tr": "Üretim başlatılıyor…"},
    "flash.hint_produce": {"en": "Click Produce to render.", "tr": "Üret ile başlatın."},
    "flash.bulk_added": {
        "en": "{n} video(s) added to queue. Use Schedule when videos are ready.",
        "tr": "{n} video kuyruğa eklendi. Hazır olunca Planla kullanın.",
    },
    "flash.job_not_found": {"en": "Job not found.", "tr": "İş bulunamadı."},
    "flash.job_deleted": {"en": "Video #{id} deleted.", "tr": "Video #{id} silindi."},
    "flash.jobs_deleted_bulk": {
        "en": "{n} video(s) deleted.",
        "tr": "{n} video silindi.",
    },
    "flash.jobs_delete_skipped": {
        "en": "{n} job(s) skipped (still producing or not found).",
        "tr": "{n} iş atlandı (üretimde veya bulunamadı).",
    },
    "flash.no_jobs_selected": {
        "en": "No videos selected.",
        "tr": "Seçili video yok.",
    },
    "flash.job_delete_active": {
        "en": "Job #{id} is producing — wait or reset stuck jobs first.",
        "tr": "İş #{id} üretimde — bekleyin veya takılı işleri sıfırlayın.",
    },
    "flash.delete_failed": {"en": "Delete failed.", "tr": "Silme başarısız."},
    "flash.sync_ok": {
        "en": "{label}: YouTube sync — {n} record(s) updated.",
        "tr": "{label}: YouTube senkron — {n} kayıt güncellendi.",
    },
    "flash.sync_error": {
        "en": "YouTube sync error: {err}",
        "tr": "YouTube senkron hatası: {err}",
    },
    "flash.schedule_ok_peak": {
        "en": "{label}: sync {synced} · {count} video(s) scheduled — {summary}",
        "tr": "{label}: sync {synced} · {count} video planlandı — {summary}",
    },
    "flash.schedule_ok": {
        "en": "{label}: sync {synced} · {count} ready video(s) scheduled ({summary}).",
        "tr": "{label}: sync {synced} · {count} hazır video planlandı ({summary}).",
    },
    "flash.no_ready_schedule": {
        "en": "{label}: no ready videos to schedule.",
        "tr": "{label}: planlanacak hazır video yok.",
    },
    "flash.seo_trimmed": {
        "en": "Trimmed descriptions for {n} ready video(s).",
        "tr": "{n} hazır video açıklaması kısaltıldı.",
    },
    "flash.only_ready_edit": {
        "en": "Only ready videos can be edited.",
        "tr": "Sadece hazır videolar düzenlenebilir.",
    },
    "flash.title_empty": {"en": "Title cannot be empty.", "tr": "Başlık boş olamaz."},
    "flash.desc_empty": {"en": "Description cannot be empty.", "tr": "Açıklama boş olamaz."},
    "flash.desc_long": {
        "en": "Description too long ({n}/{max} chars). Text and hashtags must fit within the limit.",
        "tr": "Açıklama çok uzun ({n}/{max} karakter). Metin ve hashtagler sınıra uymalı.",
    },
    "flash.seo_updated": {
        "en": "Video #{id} SEO updated ({n}/{max} chars).",
        "tr": "Video #{id} SEO güncellendi ({n}/{max} karakter).",
    },
    "flash.only_ready_schedule": {
        "en": "Only ready videos can be scheduled.",
        "tr": "Sadece hazır videolar planlanabilir.",
    },
    "flash.manual_schedule": {
        "en": "Publish time set (your selected slot).",
        "tr": "Yayın saati atandı.",
    },
    "flash.auto_schedule": {
        "en": "Scheduled for the next available daily slot.",
        "tr": "Sonraki boş güne planlandı.",
    },
    "flash.schedule_error": {
        "en": "Scheduling error: {err}",
        "tr": "Planlama hatası: {err}",
    },
    "flash.nothing_upload": {
        "en": "Nothing to upload — produce videos, schedule them, then upload.",
        "tr": "Yüklenecek video yok — üret, planla, sonra yükle.",
    },
    "flash.upload_started": {
        "en": "Uploading {n} scheduled video(s) → {label}",
        "tr": "{n} planlı video yükleniyor → {label}",
    },
    "flash.upload_running": {
        "en": "Upload already running — wait for it to finish.",
        "tr": "Yükleme zaten çalışıyor — bitmesini bekleyin.",
    },
    "flash.production_running": {
        "en": "Production already running — wait or refresh the page.",
        "tr": "Üretim zaten çalışıyor — bekleyin veya sayfayı yenileyin.",
    },
    "flash.job_started": {
        "en": "Job #{id} started in the background.",
        "tr": "İş #{id} arka planda başladı.",
    },
    "flash.job_retry_started": {
        "en": "Job #{id} queued for retry.",
        "tr": "İş #{id} yeniden deneme kuyruğuna alındı.",
    },
    "flash.jobs_retry_bulk": {
        "en": "{label}: retrying {n} job(s) in sequence.",
        "tr": "{label}: {n} iş sırayla yeniden deneniyor.",
    },
    "flash.job_not_retryable": {
        "en": "Job #{id} cannot be retried (not pending or failed).",
        "tr": "İş #{id} yeniden denenemez (bekleyen veya hatalı değil).",
    },
    "flash.no_failed_jobs": {
        "en": "No failed jobs on this channel.",
        "tr": "Bu kanalda hatalı iş yok.",
    },
    "flash.production_started": {
        "en": "{label}: production started ({n} job(s)).",
        "tr": "{label}: üretim başladı ({n} iş).",
    },
    "flash.channel_fields": {
        "en": "Panel name and niche are required.",
        "tr": "Panel adı ve niche zorunludur.",
    },
    "flash.unknown_niche": {
        "en": "Unknown niche '{niche}'. Add it to config/niches.json first.",
        "tr": "Bilinmeyen niche '{niche}'. Önce config/niches.json'a ekleyin.",
    },
    "flash.voice_updated": {
        "en": "Voice updated for {name}.",
        "tr": "{name} için ses güncellendi.",
    },
    "flash.channel_deleted": {
        "en": "Channel \"{name}\" removed from the panel.",
        "tr": "\"{name}\" panelden kaldırıldı.",
    },
    "flash.channel_delete_blocked": {
        "en": "Cannot remove channel while production is running. Wait or reset stuck jobs.",
        "tr": "Üretim devam ederken kanal kaldırılamaz. Bekleyin veya takılı işleri sıfırlayın.",
    },
    "flash.channel_created_connect": {
        "en": "Channel '{name}' created. Choose a YouTube account…",
        "tr": "Kanal '{name}' oluşturuldu. YouTube hesabını seçin…",
    },
    "flash.channel_created": {
        "en": "Channel '{name}' created. Use Connect in settings to link YouTube.",
        "tr": "Kanal '{name}' oluşturuldu. Ayarlardan Bağla'ya tıklayın.",
    },
    "flash.channel_not_found": {"en": "Channel not found.", "tr": "Kanal bulunamadı."},
    "flash.oauth_mismatch": {
        "en": "OAuth redirect URI mismatch. Add this in Google Cloud Console: {uri}",
        "tr": "OAuth redirect URI uyumsuz. Google Console'a ekleyin: {uri}",
    },
    "flash.youtube_disconnected": {
        "en": "YouTube disconnected. Choose an account to reconnect.",
        "tr": "YouTube bağlantısı kesildi. Yeniden bağlanmak için hesap seçin.",
    },
    "flash.youtube_denied": {
        "en": "YouTube permission denied: {err}",
        "tr": "YouTube izni reddedildi: {err}",
    },
    "flash.oauth_missing": {
        "en": "OAuth state or code missing.",
        "tr": "OAuth state veya code eksik.",
    },
    "flash.youtube_connected": {
        "en": "YouTube connected: {title}",
        "tr": "YouTube bağlandı: {title}",
    },
    "flash.youtube_token_saved": {
        "en": "YouTube token saved.",
        "tr": "YouTube token kaydedildi.",
    },
    "flash.youtube_connect_error": {
        "en": "YouTube connection error: {err}",
        "tr": "YouTube bağlantı hatası: {err}",
    },
    "flash.bg_required": {
        "en": "Niche and video file are required.",
        "tr": "Niche ve video dosyası zorunludur.",
    },
    "flash.bg_format": {
        "en": "Unsupported format. Allowed: {formats}",
        "tr": "Desteklenmeyen format. İzin verilen: {formats}",
    },
    "flash.bg_uploaded": {
        "en": "Background uploaded: {path}",
        "tr": "Arka plan yüklendi: {path}",
    },
    "flash.label_channel": {"en": "channel", "tr": "kanal"},
    "flash.label_all_channels": {"en": "all channels", "tr": "tüm kanallar"},
    # OAuth callback HTML
    "oauth.page_title": {"en": "YouTube connection", "tr": "YouTube bağlantısı"},
    "oauth.complete": {"en": "Connection complete", "tr": "Bağlantı tamamlandı"},
    "oauth.error": {"en": "Error", "tr": "Hata"},
    "oauth.redirecting": {
        "en": "Redirecting to dashboard…",
        "tr": "Panele yönlendiriliyorsunuz…",
    },
    "oauth.click_here": {
        "en": "Click here if you are not redirected",
        "tr": "Yönlendirilmezseniz buraya tıklayın",
    },
    # Queue summary
    "queue.summary": {
        "en": "Pending {pending} · Processing {processing}",
        "tr": "Bekleyen {pending} · Üretimde {processing}",
    },
    "queue.failed": {"en": "{n} failed", "tr": "{n} hata"},
}

JS_KEYS = (
    "banner.producing",
    "banner.production_progress",
    "banner.uploading",
    "banner.job",
    "banner.queued",
    "banner.more_in_queue",
    "label.job_active",
    "label.queued",
    "action.upload",
    "action.delete_selected",
    "confirm.delete_jobs_bulk",
)


def get_locale() -> str:
    code = (
        session.get("lang")
        or request.cookies.get("lang")
        or request.args.get("lang")
        or DEFAULT_LOCALE
    ).lower()
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


def translate(key: str, locale: str | None = None, **kwargs: object) -> str:
    loc = locale or get_locale()
    if loc not in SUPPORTED_LOCALES:
        loc = DEFAULT_LOCALE
    entry = MESSAGES.get(key, {})
    text = entry.get(loc) or entry.get(DEFAULT_LOCALE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def status_label(status_value: str, locale: str | None = None) -> str:
    return translate(f"status.{status_value}", locale)


def js_messages(locale: str | None = None) -> dict[str, str]:
    loc = locale or get_locale()
    return {k: translate(k, loc) for k in JS_KEYS}
