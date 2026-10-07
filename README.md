# 🪝 AI Pipeline + Hook

> Hook 排程系統 — 管理觸發層（Hook）與管線（Pipeline）之間的關係。

---

## 🏗️ Architecture · 架構

```
  觸發層 Hook              編排層 Pipeline Runner        技能層 Skills           輸出層
  ┌─────────────┐         ┌──────────────────┐         ┌─────────────┐       ┌──────────┐
  │ Cron        │───┐     │ 讀取 Pipeline    │         │ web-scraping│       │ Obsidian │
  │ Claude.ai   │───┼────▶│ 依序執行 Steps   │────────▶│ source-eval │──────▶│ 報告檔案 │
  │ Webhook     │───┘     │ Claude Code      │         │ summarizing │       │ 通知     │
  └─────────────┘         │ Hook：防呆檢查    │         │ obsidian    │       └──────────┘
                          └──────────────────┘         └─────────────┘
```

---

## 📁 Project Structure · 專案結構

```
AI-Pipeline-Hook/
├── pipelines/                    # Pipeline 定義（YAML 設定）
│   ├── daily-job-schedule.yaml  # 1: 個人行程/任務彙整
│   ├── daily-news-report.yaml   # 2: 五大領域新聞知識彙整
│   ├── daily-media-management/  # 3: 社群媒體管理
│   │   ├── engagement.yaml     #   3a: 互動管理
│   │   ├── publish-image-text.yaml   # 3b 車道一：圖文
│   │   ├── publish-video-audio.yaml  # 3b 車道二：影音
│   │   └── performance-review.yaml   # 3c: 週期性成效回顧
│   ├── daily-ego-learning/      # 4: 個人學習（西語/舞蹈/程式/易經道學/複習排程）
│   └── daily-self-awareness/    # 5: 每日命理（八字/紫微/人類圖/占星）
├── runner/
│   ├── pipeline_runner.py       # 共用 Pipeline Runner
│   └── cron_schedule.py         # cron 解析與到期判斷（--due）
├── scripts/
│   └── fetch_sources.py         # Pipeline 1 機械抓取層（Calendar/Notion/GitHub）
├── hooks/
│   ├── pre_run.sh              # 執行前防呆檢查（exit 10 = skip pipeline）
│   └── post_run.sh             # 執行後 write-back
├── workers/
│   └── media-processor/        # FFmpeg 媒體處理 worker（未實作）
├── tests/                       # pytest 測試
├── config/
│   ├── .env.template           # 環境變數模板
│   └── birth-profile.template.yaml  # 出生資料模板（真實檔不進 Git）
├── CLAUDE.md                    # Claude Code 專案慣例
└── README.md
```

---

## 🔄 Pipelines · 管線總覽

| # | Name | Trigger | Has State? | Output |
|---|------|---------|------------|--------|
| 1 | `daily-job-schedule` | cron 07:30 | ✅ write-back | `Daily/YYYY-MM-DD.md` |
| 2 | `daily-news-report` | Claude.ai 06:30 | ❌ | 獨立報告 |
| 3 | `daily-media-management` | webhook + cron | ✅ 發佈狀態 | 外部平台 + log |
| 4 | `daily-ego-learning` | cron 07:30 | ✅ progress store | Daily note + 主題筆記 |
| 5 | `daily-self-awareness` | Claude.ai | ❌ | Daily note 區塊 |

---

## 🚀 Quick Start · 快速開始

```bash
# 1. Clone and set up
git clone https://github.com/Galen-Chu/AI-Pipeline-Hook.git
cd AI-Pipeline-Hook
pip install -r requirements.txt
cp config/.env.template .env  # 填入憑證；未設定時以降級模式執行（來源標記 not_configured）

# 2. Run a pipeline
python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml

# 3. Scheduling — 單一排程進入點，自動執行所有到期的 cron pipeline
python runner/pipeline_runner.py --due
python runner/pipeline_runner.py --list   # 檢視清單與到期狀態
```

排程設定範例（`--due` 每 10 分鐘檢查一次即可，到期判斷由 runner 负责）：

```bash
# Linux/macOS — crontab -e
*/10 * * * * cd /path/to/AI-Pipeline-Hook && python runner/pipeline_runner.py --due

# Windows — 工作排程器（管理者 cmd；hooks 需要 Git Bash 在 PATH 上）
schtasks /Create /TN "AI-Pipeline-Hook" /SC MINUTE /MO 10 ^
  /TR "cmd /c cd /d D:\AI-Pipeline-Hook && python runner\pipeline_runner.py --due"
```

---

## 📐 Design Principles · 設計原則

1. **程式碼與資料分開**：`pipelines/` 與 `runner/` 進 Git；vault、媒體、progress store 不進
2. **Write-back**：每次執行完把狀態寫回 frontmatter / progress store，不另建資料庫
3. **機械抓取交給程式碼，判斷/寫作交給 Claude**
4. **輕量骨架優先**：等模式重複出現再抽共用模組

---

## ⚙️ 啟用前環境設定 · Activation Checklist

骨架已完成，未設定時可整條跑通（降級模式：來源標記 `not_configured`、輸出留在
`data/runs/` 內不進 vault）。要正式啟用各 pipeline，先完成對應設定：

- [ ] **Obsidian vault 路徑** — `.env` 的 `OBSIDIAN_VAULT_PATH`（Pipeline 1/4/5 寫入 vault 的前提）
- [ ] **Notion Tasks 欄位命名** — status/due date 欄位名（Pipeline 1，見架構文件第九節）
- [ ] **Google Calendar / Notion / GitHub 憑證** — `.env`（Pipeline 1）
- [ ] **出生資料** — 複製 `config/birth-profile.template.yaml` 為 `config/birth-profile.yaml` 並填寫（Pipeline 5；該檔已被 .gitignore 排除）
- [ ] **各學習主題 v1 教材/來源** — Pipeline 4
- [ ] **社群平台 API 申請** — Pipeline 3（TikTok Creator's Draft、Instagram Graph API 等）
- [ ] **Skills 部署** — Pipeline 2 引用的 skills（`web-scraping-patterns` 等）需先安裝於 Claude Code 環境（`.claude/skills/` 或 plugin）
- [ ] **通知機制**（可選）— Slack/ntfy，或先以「打開 Obsidian 才看到」為 v1 預設

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Galen Chu**

- GitHub: [@Galen-Chu](https://github.com/Galen-Chu)
- LinkedIn: [Galen Chu](https://www.linkedin.com/in/galen-chu-203590b5/)
