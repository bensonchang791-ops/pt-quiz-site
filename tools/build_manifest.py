#!/usr/bin/env python3
"""Build the source manifest used by the quiz website.

This pass scans the subject folders and the answer folder, then writes a
pairing report. Full per-question PDF parsing is intentionally separate so the
site can be built and tested before OCR/text-extraction quality is known.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_DATA = ROOT / "quiz-site" / "data"
ANSWER_DIR = ROOT / "解答"

SUBJECTS = {
    "國考基礎學": ["國考基礎學", "基礎學"],
    "概論": ["概論"],
    "技術學": ["技術學"],
    "神經": ["神經"],
    "骨科": ["骨科"],
    "心肺加小兒": ["心肺加小兒", "心兒"],
}


def normalized_name(path: Path) -> str:
    return path.name.replace("ㄧ", "一")


def parse_year_session(path: Path) -> tuple[int | None, str | None]:
    name = normalized_name(path)
    year_match = re.search(r"(10[5-9]|11[0-9])", name)
    year = int(year_match.group(1)) if year_match else None

    if "第二次" in name:
        session = "第二次"
    elif "第一次" in name:
        session = "第一次"
    else:
        session = None

    return year, session


def subject_from_answer(path: Path) -> str | None:
    name = normalized_name(path)
    for subject, aliases in SUBJECTS.items():
        if any(alias in name for alias in aliases):
            return subject
    return None


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def scan_answer_files() -> tuple[dict[tuple[int, str, str], list[Path]], list[dict]]:
    index: dict[tuple[int, str, str], list[Path]] = defaultdict(list)
    issues = []

    for path in sorted(ANSWER_DIR.glob("*/*.pdf")):
      year, session = parse_year_session(path)
      subject = subject_from_answer(path)
      if year is None or session is None or subject is None:
          issues.append({
              "type": "answer-parse-failed",
              "title": "解答檔名無法辨識",
              "detail": rel(path),
          })
          continue
      index[(year, session, subject)].append(path)

    for key, paths in index.items():
        if len(paths) > 1:
            issues.append({
                "type": "duplicate-answer",
                "title": "同一科目年度次別有多份解答",
                "detail": "、".join(rel(path) for path in paths),
            })

    return index, issues


def build_manifest() -> dict:
    answer_index, issues = scan_answer_files()
    documents = []
    used_answer_keys = set()
    subject_rows = []

    for subject in SUBJECTS:
        folder = ROOT / subject
        question_files = sorted(folder.glob("*.pdf"))
        paired_count = 0
        answer_count = sum(1 for (year, session, answer_subject) in answer_index if answer_subject == subject)

        for question_path in question_files:
            year, session = parse_year_session(question_path)
            answer_paths = answer_index.get((year, session, subject), []) if year and session else []
            answer_path = answer_paths[0] if answer_paths else None
            paired = answer_path is not None
            if paired:
                paired_count += 1
                used_answer_keys.add((year, session, subject))
            else:
                issues.append({
                    "type": "missing-answer",
                    "title": "找不到對應解答",
                    "detail": rel(question_path),
                })

            documents.append({
                "subject": subject,
                "year": year,
                "session": session,
                "questionPdf": rel(question_path),
                "answerPdf": rel(answer_path) if answer_path else None,
                "paired": paired,
                "textStatus": "pending",
            })

        subject_rows.append({
            "name": subject,
            "questionPdfs": len(question_files),
            "pairedQuestionPdfs": paired_count,
            "answerPdfs": answer_count,
        })

    for key, paths in answer_index.items():
        if key not in used_answer_keys:
            issues.append({
                "type": "orphan-answer",
                "title": "解答沒有對應試題",
                "detail": "、".join(rel(path) for path in paths),
            })

    totals = {
        "subjects": len(SUBJECTS),
        "questionPdfs": sum(row["questionPdfs"] for row in subject_rows),
        "pairedQuestionPdfs": sum(row["pairedQuestionPdfs"] for row in subject_rows),
        "answerPdfs": sum(row["answerPdfs"] for row in subject_rows),
        "issues": len(issues),
    }

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "pdfTextExtractor": shutil.which("pdftotext") or None,
        "totals": totals,
        "subjects": subject_rows,
        "documents": documents,
        "issues": issues,
    }


def main() -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    output = SITE_DATA / "source-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(json.dumps(manifest["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
