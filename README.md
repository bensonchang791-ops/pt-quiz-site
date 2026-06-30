# 國考題庫網站

這個專案是本機國考題庫小網站，網站檔案放在 `quiz-site/`。

## GitHub Pages 部署流程

1. 將這個專案推到 GitHub repo 的 `main` 分支。
2. 到 GitHub repo 的 `Settings` → `Pages`。
3. Source 選擇 `GitHub Actions`。
4. 等待 `Deploy quiz site to GitHub Pages` workflow 完成。
5. GitHub 會顯示網站網址。

## 本機預覽

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory quiz-site
```

打開：

```text
http://127.0.0.1:8765/
```

## 已完成

- 靜態網站介面
- 科目篩選
- 隨機出題
- 測驗時間正向計時
- 作答、標記、看解析、交卷計分
- 本機錯題本
- 題庫搜尋
- PDF 來源清單與解答配對狀態
- GitHub Pages 自動部署設定

## 注意

`.gitignore` 目前會排除原始 PDF 資料夾，避免把完整考題 PDF 直接公開到 GitHub。

網站目前讀取：

- `quiz-site/data/question-bank.json`
- `quiz-site/data/source-manifest.json`

後續 PDF 解析完成後，只需要更新 `question-bank.json`，網站就會讀到完整題庫。
