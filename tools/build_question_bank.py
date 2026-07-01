#!/usr/bin/env python3
"""Extract the PDF exam papers into the website question-bank JSON."""

from __future__ import annotations

import json
import logging
import re
import sys
import base64
import gzip
import shutil
import subprocess
import tempfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_manifest import ROOT, SITE_DATA, build_manifest

try:
    import pdfplumber
except ImportError as error:  # pragma: no cover - runtime environment check
    raise SystemExit(
        "pdfplumber is required. Run this with the bundled Codex Python runtime."
    ) from error

try:
    from PIL import Image
except ImportError as error:  # pragma: no cover - runtime environment check
    raise SystemExit(
        "Pillow is required to crop PDF question images. Run this with the bundled Codex Python runtime."
    ) from error


logging.getLogger("pdfminer").setLevel(logging.ERROR)

QUESTION_IMAGE_DIR = SITE_DATA / "question-images"
PDFTOPPM = shutil.which("pdftoppm")
IMAGE_DPI = "144"

SUBJECT_SLUGS = {
    "國考基礎學": "basic",
    "概論": "intro",
    "技術學": "tech",
    "神經": "neuro",
    "骨科": "ortho",
    "心肺加小兒": "cardio-peds",
}

FULLWIDTH_TRANSLATION = str.maketrans({
    "Ａ": "A",
    "Ｂ": "B",
    "Ｃ": "C",
    "Ｄ": "D",
    "ａ": "A",
    "ｂ": "B",
    "ｃ": "C",
    "ｄ": "D",
    "＃": "#",
    "０": "0",
    "１": "1",
    "２": "2",
    "３": "3",
    "４": "4",
    "５": "5",
    "６": "6",
    "７": "7",
    "８": "8",
    "９": "9",
    "　": " ",
})

QUESTION_START = re.compile(r"(?m)^\s*(\d{1,3})[\.．、]\s*")
OPTION_START = re.compile(r"(?m)^\s*([A-D])\s*[\.．、]\s*")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def extract_pdf_text(path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
    return "\n".join(parts)


def normalize_raw_text(text: str) -> str:
    text = text.translate(FULLWIDTH_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def clean_display_text(text: str) -> str:
    text = normalize_raw_text(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def option_sequence(chunk: str) -> list[re.Match[str]]:
    matches = list(OPTION_START.finditer(chunk))
    sequence: list[re.Match[str]] = []
    search_from = 0
    for expected in "ABCD":
        candidate = next(
            (
                match
                for match in matches
                if match.group(1) == expected and match.start() >= search_from
            ),
            None,
        )
        if candidate is None:
            return []
        sequence.append(candidate)
        search_from = candidate.end()
    return sequence


def parse_questions(text: str) -> tuple[list[dict], list[dict]]:
    normalized = normalize_raw_text(text)
    starts: list[re.Match[str]] = []
    expected_number = 1
    for match in QUESTION_START.finditer(normalized):
        number = int(match.group(1))
        if number == expected_number:
            starts.append(match)
            expected_number += 1
            if expected_number > 80:
                break

    questions: list[dict] = []
    issues: list[dict] = []

    for index, match in enumerate(starts):
        number = int(match.group(1))
        chunk_start = match.end()
        chunk_end = starts[index + 1].start() if index + 1 < len(starts) else len(normalized)
        chunk = normalized[chunk_start:chunk_end]
        options = option_sequence(chunk)
        if len(options) != 4:
            issues.append({
                "type": "question-options-parse-failed",
                "title": "題目選項無法辨識",
                "detail": f"第 {number} 題只找到 {len(options)} 個選項",
            })
            continue

        stem = clean_display_text(chunk[:options[0].start()])
        option_rows = []
        for option_index, option_match in enumerate(options):
            option_end = (
                options[option_index + 1].start()
                if option_index + 1 < len(options)
                else len(chunk)
            )
            option_rows.append({
                "key": option_match.group(1),
                "text": clean_display_text(chunk[option_match.end():option_end]),
            })

        empty_options = [option["key"] for option in option_rows if not option["text"]]
        if empty_options:
            issues.append({
                "type": "question-option-text-missing",
                "title": "選項文字需要圖片補入",
                "detail": f"第 {number} 題：{', '.join(empty_options)} 選項沒有文字，可能是圖片或表格題",
            })

        questions.append({
            "sourceQuestionNumber": str(number),
            "stem": stem,
            "options": option_rows,
            "emptyOptions": empty_options,
        })

    return questions, issues


def unique_letters(text: str) -> list[str]:
    seen: list[str] = []
    for letter in re.findall(r"[A-D]", text.translate(FULLWIDTH_TRANSLATION)):
        if letter not in seen:
            seen.append(letter)
    return seen


def parse_answer_notes(normalized_text: str) -> dict[int, dict]:
    notes: dict[int, dict] = {}
    for match in re.finditer(r"第\s*(\d{1,3})\s*題(.*?)(?=第\s*\d{1,3}\s*題|$)", normalized_text, re.S):
        number = int(match.group(1))
        clause = re.sub(r"\s+", "", match.group(2))
        accepted: list[str] = []
        if "一律給分" in clause or "其餘均給分" in clause:
            accepted = ["A", "B", "C", "D"]
        elif "答" in clause:
            after_answer = clause.split("答", 1)[1]
            accepted = unique_letters(after_answer.split("給分", 1)[0])

        if accepted:
            notes[number] = {
                "acceptedAnswers": accepted,
                "note": f"更正答案：{clause}",
            }
    return notes


def parse_answers(text: str) -> tuple[dict[int, dict], list[dict]]:
    normalized = normalize_raw_text(text)
    lines = normalized.splitlines()
    notes = parse_answer_notes(normalized)
    answers: dict[int, dict] = {}
    issues: list[dict] = []

    for index, line in enumerate(lines):
        if not re.match(r"^題[號序]\s+", line):
            continue

        numbers = [int(value) for value in re.findall(r"\d{1,3}", line)]
        if not numbers:
            continue

        answer_line = ""
        for candidate in lines[index + 1:index + 4]:
            if candidate.startswith("答案"):
                answer_line = candidate
                break

        tokens = re.findall(r"[A-D#]", answer_line)
        if len(tokens) != len(numbers):
            issues.append({
                "type": "answer-row-parse-failed",
                "title": "答案列無法辨識",
                "detail": f"題號 {numbers[0]}-{numbers[-1]}：題號 {len(numbers)} 個，答案 {len(tokens)} 個",
            })
            continue

        for number, token in zip(numbers, tokens):
            note = notes.get(number)
            if token == "#":
                if note:
                    accepted = note["acceptedAnswers"]
                else:
                    accepted = []
                    issues.append({
                        "type": "corrected-answer-note-missing",
                        "title": "更正答案缺少備註",
                        "detail": f"第 {number} 題",
                    })
            else:
                accepted = [token]

            if accepted:
                answers[number] = {
                    "answer": accepted[0],
                    "acceptedAnswers": accepted,
                    "answerNote": note["note"] if note else "",
                }

    return answers, issues


def question_id(subject: str, year: int, session: str, number: int) -> str:
    session_slug = "1" if session == "第一次" else "2"
    return f"{SUBJECT_SLUGS[subject]}-{year}-{session_slug}-{number:03d}"


def wrap_base64(text: str, width: int = 120) -> str:
    return "\n".join(text[index:index + width] for index in range(0, len(text), width))


def pdf_question_starts(path: Path) -> list[dict]:
    starts: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=1, y_tolerance=3)
            for word in words:
                text = word["text"].translate(FULLWIDTH_TRANSLATION)
                match = re.match(r"^(\d{1,3})[\.．、]", text)
                if not match:
                    continue
                starts.append({
                    "number": int(match.group(1)),
                    "pageIndex": page_index,
                    "top": float(word["top"]),
                })
    return sorted(starts, key=lambda start: (start["pageIndex"], start["top"]))


def in_question_region(word: dict, page_index: int, start: dict, end: dict | None) -> bool:
    if page_index < start["pageIndex"]:
        return False
    if page_index == start["pageIndex"] and word["top"] < start["top"]:
        return False
    if end is None:
        return True
    if page_index > end["pageIndex"]:
        return False
    if page_index == end["pageIndex"] and word["top"] >= end["top"]:
        return False
    return True


def option_label_positions(pdf, start: dict, end: dict | None) -> list[dict]:
    last_page = end["pageIndex"] if end else len(pdf.pages) - 1
    labels: list[dict] = []
    for page_index in range(start["pageIndex"], last_page + 1):
        page = pdf.pages[page_index]
        for word in page.extract_words(x_tolerance=1, y_tolerance=3):
            text = word["text"].translate(FULLWIDTH_TRANSLATION).strip()
            match = re.fullmatch(r"([A-D])[\.．、]?", text)
            if not match or not in_question_region(word, page_index, start, end):
                continue
            labels.append({
                "letter": match.group(1),
                "pageIndex": page_index,
                "top": float(word["top"]),
            })
    return labels


def render_pdf_page(pdf_path: Path, page_index: int, temp_dir: Path) -> Path:
    if not PDFTOPPM:
        raise RuntimeError("pdftoppm was not found; cannot render PDF question images.")

    prefix = temp_dir / "page"
    subprocess.run(
        [
            PDFTOPPM,
            "-f",
            str(page_index + 1),
            "-l",
            str(page_index + 1),
            "-r",
            IMAGE_DPI,
            "-png",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    rendered = sorted(temp_dir.glob("page-*.png")) or sorted(temp_dir.glob("page.png"))
    if not rendered:
        raise RuntimeError(f"pdftoppm did not create an image for {pdf_path} page {page_index + 1}.")
    return rendered[0]


def crop_question_images(pdf_path: Path, number: int, empty_options: list[str], qid: str) -> list[str]:
    starts = pdf_question_starts(pdf_path)
    start_by_number = {start["number"]: start for start in starts}
    start = start_by_number.get(number)
    if not start:
        return []

    end = start_by_number.get(number + 1)
    first_empty = empty_options[0] if empty_options else "A"
    image_paths: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        labels = option_label_positions(pdf, start, end)
        crop_start = next((label for label in labels if label["letter"] == first_empty), None)
        if crop_start is None:
            crop_start = labels[0] if labels else start

        first_page = crop_start["pageIndex"]
        last_page = end["pageIndex"] if end else len(pdf.pages) - 1

        for page_index in range(first_page, last_page + 1):
            page = pdf.pages[page_index]
            y0 = crop_start["top"] - 2 if page_index == first_page else 28
            y1 = end["top"] - 8 if end and page_index == end["pageIndex"] else page.height - 24
            y0 = max(18, y0)
            y1 = min(page.height - 18, max(y0 + 36, y1))
            x0 = 20
            x1 = page.width - 20

            with tempfile.TemporaryDirectory() as temp_name:
                rendered = render_pdf_page(pdf_path, page_index, Path(temp_name))
                with Image.open(rendered) as image:
                    scale_x = image.width / page.width
                    scale_y = image.height / page.height
                    crop_box = (
                        round(x0 * scale_x),
                        round(y0 * scale_y),
                        round(x1 * scale_x),
                        round(y1 * scale_y),
                    )
                    cropped = image.crop(crop_box)
                    buffer = BytesIO()
                    cropped.save(buffer, format="PNG", optimize=True)
                    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                    file_name = f"{qid}-{len(image_paths) + 1:02d}.svg"
                    output_path = QUESTION_IMAGE_DIR / file_name
                    output_path.write_text(
                        (
                            f'<svg xmlns="http://www.w3.org/2000/svg" width="{cropped.width}" '
                            f'height="{cropped.height}" viewBox="0 0 {cropped.width} {cropped.height}">'
                            f'<image href="data:image/png;base64,{encoded}" width="{cropped.width}" '
                            f'height="{cropped.height}"/></svg>\n'
                        ),
                        encoding="utf-8",
                    )
                    image_paths.append(f"data/question-images/{file_name}")

    return image_paths


def build_question_bank() -> tuple[dict, dict]:
    manifest = build_manifest()
    questions: list[dict] = []
    extraction_issues: list[dict] = []
    image_question_count = 0

    if QUESTION_IMAGE_DIR.exists():
        shutil.rmtree(QUESTION_IMAGE_DIR)
    QUESTION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    for document in manifest["documents"]:
        if not document["paired"]:
            continue

        question_path = ROOT / document["questionPdf"]
        answer_path = ROOT / document["answerPdf"]
        parsed_questions, question_issues = parse_questions(extract_pdf_text(question_path))
        parsed_answers, answer_issues = parse_answers(extract_pdf_text(answer_path))
        document_issues = [
            issue for issue in question_issues
            if issue["type"] != "question-option-text-missing"
        ] + answer_issues

        document["questionCount"] = len(parsed_questions)
        document["answerCount"] = len(parsed_answers)
        document["usableQuestionCount"] = 0
        document["imageQuestionCount"] = 0

        if len(parsed_questions) != 80:
            document_issues.append({
                "type": "question-count-mismatch",
                "title": "題數不是 80 題",
                "detail": f"{len(parsed_questions)} 題",
            })

        if len(parsed_answers) != 80:
            document_issues.append({
                "type": "answer-count-mismatch",
                "title": "答案數不是 80 題",
                "detail": f"{len(parsed_answers)} 題",
            })

        for parsed_question in parsed_questions:
            number = int(parsed_question["sourceQuestionNumber"])
            answer_data = parsed_answers.get(number)
            if not answer_data:
                continue

            empty_options = parsed_question.get("emptyOptions", [])
            media = []
            options = []
            for option in parsed_question["options"]:
                options.append({
                    "key": option["key"],
                    "text": option["text"] or "見上方圖片",
                })

            answer_label = "/".join(answer_data["acceptedAnswers"])
            explanation = f"標準答案：{answer_label}。"
            if answer_data["answerNote"]:
                explanation = f"{explanation} {answer_data['answerNote']}"
            explanation = f"{explanation} 原始解答檔未提供詳解。"

            qid = question_id(document["subject"], document["year"], document["session"], number)
            if empty_options:
                try:
                    image_paths = crop_question_images(question_path, number, empty_options, qid)
                except Exception as error:  # pragma: no cover - extraction diagnostics
                    image_paths = []
                    document_issues.append({
                        "type": "question-image-crop-failed",
                        "title": "圖片選項裁切失敗",
                        "detail": f"第 {number} 題：{error}",
                    })

                if image_paths:
                    document["imageQuestionCount"] += 1
                    image_question_count += 1
                    media = [
                        {
                            "type": "image",
                            "src": path,
                            "alt": f"{document['subject']} {document['year']}年{document['session']}第 {number} 題選項圖 {index + 1}",
                        }
                        for index, path in enumerate(image_paths)
                    ]
                else:
                    document_issues.append({
                        "type": "question-image-missing",
                        "title": "圖片選項尚未補入",
                        "detail": f"第 {number} 題：{', '.join(empty_options)} 選項沒有文字",
                    })

            question = {
                "id": qid,
                "subject": document["subject"],
                "year": document["year"],
                "session": document["session"],
                "sourceFile": document["questionPdf"],
                "answerFile": document["answerPdf"],
                "sourceQuestionNumber": str(number),
                "difficulty": "未分級",
                "stem": parsed_question["stem"],
                "options": options,
                "answer": answer_data["answer"],
                "acceptedAnswers": answer_data["acceptedAnswers"],
                "explanation": explanation,
                "tags": [
                    document["subject"],
                    f"{document['year']}年{document['session']}",
                    "歷屆試題",
                ],
            }
            if media:
                question["media"] = media
                question["hasImageOptions"] = True
            questions.append(question)
            document["usableQuestionCount"] += 1

        document["textStatus"] = (
            "complete"
            if len(parsed_questions) == 80 and len(parsed_answers) == 80 and not document_issues
            else "needs-review"
        )

        for issue in document_issues:
            issue["detail"] = f"{document['questionPdf']} / {document['answerPdf']}：{issue['detail']}"
            extraction_issues.append(issue)

    manifest["generatedAt"] = datetime.now(timezone.utc).isoformat()
    for subject in manifest["subjects"]:
        subject["imageQuestionCount"] = sum(
            document.get("imageQuestionCount", 0)
            for document in manifest["documents"]
            if document["subject"] == subject["name"]
        )
    manifest["issues"].extend(extraction_issues)
    manifest["totals"]["questions"] = len(questions)
    manifest["totals"]["imageQuestions"] = image_question_count
    manifest["totals"]["documentsExtracted"] = sum(
        1 for document in manifest["documents"] if document.get("textStatus") == "complete"
    )
    manifest["totals"]["issues"] = len(manifest["issues"])

    bank = {
        "schemaVersion": 2,
        "name": "國考題庫",
        "generatedAt": manifest["generatedAt"],
        "subjects": [subject["name"] for subject in manifest["subjects"]],
        "questions": questions,
    }
    return bank, manifest


def main() -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    bank, manifest = build_question_bank()

    question_output = SITE_DATA / "question-bank.json"
    manifest_output = SITE_DATA / "source-manifest.json"
    question_output.write_text(
        json.dumps(bank, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    compressed = base64.b64encode(gzip.compress(question_output.read_bytes(), compresslevel=9)).decode("ascii")
    part_size = 300_000
    parts = []
    for index in range(0, len(compressed), part_size):
        part_name = f"question-bank.part{len(parts) + 1:02d}.b64"
        parts.append(part_name)
        (SITE_DATA / part_name).write_text(
            wrap_base64(compressed[index:index + part_size]) + "\n",
            encoding="ascii",
        )

    compressed_index = {
        "schemaVersion": 1,
        "encoding": "gzip+base64",
        "source": "question-bank.json",
        "parts": parts,
        "uncompressedBytes": question_output.stat().st_size,
        "compressedBase64Bytes": len(compressed),
    }
    (SITE_DATA / "question-bank.parts.json").write_text(
        json.dumps(compressed_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {question_output}")
    print(f"Wrote {manifest_output}")
    print(f"Wrote compressed question bank in {len(parts)} parts")
    print(json.dumps(manifest["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
