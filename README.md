# Volume Breakout 量化交易分析（V1）

依 Volume Breakout Agent Instructions V1 的規則，使用**臺灣證券交易所（TWSE）官方盤後資料**判定 BUY / WATCH / HOLD / EXIT / WAIT，並提供持倉管理與歷史回測。

**線上使用：** `https://<你的帳號>.github.io/<repo 名稱>/`（發布後請把這行換成實際網址）

## 使用方式

1. 用 Chrome、Edge 或 Safari 開啟網址（請勿在 LINE 等 App 的內建預覽中開啟；若出現提示，請點「以瀏覽器開啟」）。
2. 輸入 TWSE **上市**股票代號（例如 2409），按「分析訊號」。
3. 首次查詢會向 TWSE 抓取約 14 個月資料，約需 30 秒；之後會存在你的瀏覽器，下次幾乎立即完成。
4. 已持有部位：勾選「我已持有部位」，填入 Entry Date、Entry Price、Breakout Level，判定 HOLD / EXIT。
5. 回測：切到「回測」分頁，設定起訖日與成本後執行。

資料由每位使用者的瀏覽器直接向 TWSE 讀取，本網站不經手、不儲存任何資料。若 TWSE 暫時無法連線，可到 TWSE「個股日成交資訊」下載每月 CSV，用左側「匯入」載入。

## 限制

- 僅涵蓋 TWSE 上市股票；上櫃（TPEx）股票不在資料範圍內。
- 使用未還原（原始）價格，除權息缺口可能影響突破與 ATR 判斷。
- TWSE 對短時間大量請求會暫時封鎖，程式已自動間隔約 2 秒。

## 免責聲明

本工具僅依固定規則計算策略條件是否成立，不代表股價必然上漲或下跌，亦不構成任何投資建議。使用者應自行判斷並承擔投資風險。

---

## 發布到 GitHub Pages（給維護者）

1. 登入 GitHub，按右上角「+」→「New repository」，名稱例如 `volume-breakout`，選 **Public**，建立。
2. 在 repo 頁面點「Add file」→「Upload files」，把本資料夾的 `index.html`、`README.md`、`.nojekyll` 拖進去，按「Commit changes」。
   - `.nojekyll` 是隱藏檔，若電腦上看不到可略過，不影響使用。
3. 到 **Settings → Pages**：Source 選「Deploy from a branch」，Branch 選 `main`、資料夾 `/ (root)`，按 Save。
4. 約 1–2 分鐘後，頁面上方會出現網址 `https://<帳號>.github.io/volume-breakout/`，把它分享給朋友即可。

**更新版本：** 之後拿到新的 `index.html`，在 repo 中點該檔案 →「⋯」→ 上傳覆蓋（或「Upload files」同名覆蓋），網址不變，朋友重新整理即可看到新版。
