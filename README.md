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
│   ├── daily-ego-learning/      # 4: 個人學習
│   │   ├── spanish.yaml        #   西班牙文
│   │   ├── dance.yaml          #   身體舞蹈訓練
│   │   ├── coding.yaml         #   程式作業練習
│   │   ├── iching-daoism.yaml  #   易經＋道學
│   │   └── review-scheduler.yaml #  複習排程（SM-2）
│   └── daily-self-awareness/    # 5: 每日命理
│       ├── bazi.yaml           #   八字
│       ├── ziwei.yaml          #   紫微斗數
│       ├── human-design.yaml   #   人類圖
│       ├── astrology.yaml      #   占星
│       └── birth-profile.yaml  #   出生資料（共用輸入）
├── runner/
│   └── pipeline_runner.py       # 共用 Pipeline Runner
├── hooks/
│   ├── pre_run.sh              # 執行前防呆檢查
│   └── post_run.sh             # 執行後 write-back
├── workers/
│   └── media-processor/        # FFmpeg 媒體處理 worker
├── config/
│   └── .env.template           # 環境變數模板
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
cp config/.env.template .env  # Fill in credentials

# 2. Run a pipeline
python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml

# 3. Set up cron (example)
# crontab -e
# 30 7 * * 1-5 cd /path/to/AI-Pipeline-Hook && python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml
```

---

## 📐 Design Principles · 設計原則

1. **程式碼與資料分開**：`pipelines/` 與 `runner/` 進 Git；vault、媒體、progress store 不進
2. **Write-back**：每次執行完把狀態寫回 frontmatter / progress store，不另建資料庫
3. **機械抓取交給程式碼，判斷/寫作交給 Claude**
4. **輕量骨架優先**：等模式重複出現再抽共用模組

---

## 🛠️ Setup Checklist
- [ ] Obsidian vault 路徑
- [ ] Notion Tasks 欄位命名
- [ ] Google Calendar / Notion / GitHub 認證憑證
- [ ] 出生資料（`birth-profile.yaml`）
- [ ] 各學習主題 v1 教材/來源
- [ ] 社群平台 API 申請
- [ ] 通知機制（Slack/ntfy 或先以 Obsidian 為主）

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Galen Chu**

- GitHub: [@Galen-Chu](https://github.com/Galen-Chu)
- LinkedIn: [Galen Chu](https://www.linkedin.com/in/galen-chu-203590b5/)
