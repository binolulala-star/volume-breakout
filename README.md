# Volume Breakout 量化交易分析（V1）

依 Volume Breakout Agent Instructions V1 規則，使用**臺灣證券交易所（TWSE）官方盤後資料**：

- **全市場掃描**（`scan.html`）：每個交易日收盤後由 GitHub Actions 自動抓取全部上市股票行情，找出 BUY 與 WATCH。
- **單一股票分析與回測**（`index.html`）：輸入代號即時向 TWSE 讀取資料，顯示 PASS/FAIL、持倉管理（HOLD/EXIT）與回測。

**網站：** `https://binolulala-star.github.io/volume-breakout/`（掃描清單：`…/scan.html`）

## 運作方式

| 時間（台北） | 動作 |
|---|---|
| 週一至週五 15:17、18:47 | GitHub Actions 執行 `scanner/scan.py`：抓當日「每日收盤行情（全部）」→ 存入 `store/` → 依 V1 規則掃描 → 結果寫入 `site/data/` → 發布網站 |
| 第一次執行 | 自動往回補約 230 個交易日資料（約 15–25 分鐘），之後每天只抓 1 次 |

- 規則與單一股票分析頁相同（同一份 `strategy.py`），測試已比對兩者訊號一致。
- 窗口內任何一天抓取失敗，當天**不發布訊號**（No Reliable Data → No Reliable Signal），下次執行自動重試補齊。
- 休市日（含颱風假）自動辨識；停牌或當日無成交的股票不列入。
- 頁面上的「日均量」「只看普通股」只是顯示篩選，不改變策略訊號。

## 第一次設定（只需做一次）

1. **上傳檔案**：把本資料夾全部內容（含 `.github`、`scanner`、`site` 資料夾）上傳到 repo 根目錄。
   - 網頁上傳：repo 頁面「Add file → Upload files」，把資料夾整個拖進去。
   - Mac 看不到 `.github` 隱藏資料夾時：改用「Add file → Create new file」，檔名輸入 `.github/workflows/daily-scan.yml`，把該檔內容貼上後 Commit。
   - 先前放在根目錄的 `index.html` 可刪除（網站改由 `site/` 發布）。
2. **Settings → Pages**：Source 改成 **GitHub Actions**。
3. **Settings → Actions → General**：最下方 Workflow permissions 選 **Read and write permissions**，Save。
4. **Actions** 分頁 → 左側「Daily TWSE scan」→ 右側「Run workflow」→ 執行第一次（回補資料）。
5. 完成後打開 `https://binolulala-star.github.io/volume-breakout/scan.html`。

之後每天會自動更新，不需要任何操作。

## 若 GitHub 上抓不到 TWSE

GitHub Actions 主機在海外，若 TWSE 拒絕連線（Actions 紀錄會顯示「抓取失敗」），可改在自己電腦執行（需 Python 3.9+，免安裝套件）：

```
python scanner/scan.py
```

執行後把 `store/` 與 `site/data/` 的變更 commit 並 push 到 GitHub，網站即更新；可用 Windows「工作排程器」或 macOS `launchd` 每天收盤後自動執行。

## 檔案

```
.github/workflows/daily-scan.yml   每日排程與發布
scanner/scan.py                     收集 + 掃描主程式
scanner/twse_daily.py               TWSE 每日收盤行情抓取、休市/缺口紀錄
scanner/strategy.py                 V1 規則（與單一股票分析相同）
site/index.html                     單一股票分析與回測
site/scan.html                      全市場掃描清單
site/data/                          掃描結果（自動產生）
store/                              每日原始行情（自動產生，保留最近 300 個交易日）
tests/                              測試
```

## 免責聲明

本工具僅依固定規則計算策略條件是否成立，不代表股價必然上漲或下跌，亦不構成任何投資建議。資料為 TWSE 未還原價格，除權息缺口可能影響判斷。
