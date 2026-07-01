# 國考題庫網站

## 目前完成

- 本機小網站介面
- 科目分類：國考基礎學、概論、技術學、神經、骨科、心肺加小兒
- 隨機出題
- 測驗時間正向計時
- 作答、標記、看解析、交卷計分
- 本機錯題本
- 題庫搜尋
- 試題 PDF 與解答 PDF 配對清單

## 資料檔

- `data/question-bank.json`：網站讀取的題庫資料格式，目前先放示範題。
- `data/source-manifest.json`：由 `tools/build_manifest.py` 掃描 PDF 後產生的來源清單。

## 啟動

在專案根目錄執行：

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory quiz-site
```

然後開啟：

```text
http://127.0.0.1:8765/
```

## 下一段工作

- 解析 PDF 內文
- 將題目切成單題
- 將解答配回題目
- 產生完整 `question-bank.json`
- 抽樣校正解析結果
