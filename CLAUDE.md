# CLAUDE.md

## 專案概述

Hook 排程系統：`pipelines/`（YAML 定義）+ `runner/`（共用執行器）+ `hooks/`（防呆/write-back）。
機械抓取交給程式碼（`scripts/`），判斷/寫作交給 Claude CLI。狀態一律 write-back
（frontmatter / progress store），不另建資料庫。完整規格見
`AI-Pipeline-Hook-ArchitectureDesign.md`。

## 常用指令

```bash
# 執行單一 pipeline
python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml

# 預演（不執行、不寫檔）
python runner/pipeline_runner.py --pipeline pipelines/daily-job-schedule.yaml --dry-run

# 排程進入點：掃描 pipelines/，執行所有到期的 cron pipeline
python runner/pipeline_runner.py --due

# 檢視 pipeline 清單與到期狀態
python runner/pipeline_runner.py --list

# 測試與 lint（commit 前）
python -m pytest
python -m ruff check .
```

## 結構慣例

- `pipelines/**/*.yaml` — 設定進 Git；`data/`（runs、last_runs、execution_logs）不進 Git
- 每次 執行一個 run dir：`data/runs/<pipeline>/<timestamp>/`，含 `summary.json` 與
  `steps/<id>.json` / `<id>.stdout.txt`（完整輸出，不截斷）
- Step 間傳遞：`{{steps.<id>.output}}`（內嵌，上限 4000 字）、
  `{{steps.<id>.output_file}}`、`{{run_dir}}`、`{{date}}`、`{{timestamp}}`
- Script step 額外收到環境變數：`PIPELINE_NAME` / `PIPELINE_STEP_ID` /
  `PIPELINE_RUN_DIR` / `PIPELINE_DATE`
- Step 條件：`condition: env:VAR`（未設則 skip；其他格式僅警告照跑）
- Timeout：script 預設 600s、claude 預設 300s，step 可用 `timeout:` 覆寫

## Hooks 契約

- `hooks/pre_run.sh <pipeline> <step_id>` — 每個 step 前執行；
  exit 10 = 跳過整條 pipeline（例如當日筆記已產生）
- `hooks/post_run.sh <pipeline> <status> <output_path>` — pipeline 結束後執行，
  負責 frontmatter write-back（status: generated/failed/skipped）

## Windows 注意事項

- Hooks 為 bash 腳本，runner 透過 PATH 上的 `bash`（Git Bash）呼叫；無 bash 時 hook 以警告跳過
- 排程使用工作排程器（schtasks / Task Scheduler），範例見 README；Linux/macOS 用 cron
- 憑證放在 repo 根目錄 `.env`（runner 自動載入；模板 `config/.env.template`）

## 啟用前環境設定（各 pipeline 上線前需完成）

見 README「啟用前環境設定」一節：Obsidian vault 路徑、Google/Notion/GitHub 憑證、
出生資料（`config/birth-profile.yaml`，由模板複製）、Notion Tasks 欄位命名。
未設定時系統以降級模式執行，方便先驗證骨架。
