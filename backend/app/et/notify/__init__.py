"""ET 通知接線（US8 / #273）。

發信一律經平台唯一發信服務 SRVDP002（`app.services.NotifyService`），ET 端不自持範本、
不自建佇列、不直連 SMTP。比照 `app/dm/notify/`。
"""
