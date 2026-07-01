const DATA_PATH = "data/question-bank.json";
const MANIFEST_PATH = "data/source-manifest.json";
const WRONG_KEY = "examWrongItems.v1";
const HISTORY_KEY = "examHistory.v1";

const state = {
  bank: { subjects: [], questions: [] },
  manifest: null,
  mode: "exam",
  exam: [],
  current: 0,
  answers: {},
  marked: new Set(),
  submitted: false,
  elapsedSeconds: 0,
  timerId: null,
  timerRunning: true
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const dom = {
  pageTitle: $("#pageTitle"),
  pageSubtitle: $("#pageSubtitle"),
  subjectSelect: $("#subjectSelect"),
  yearSelect: $("#yearSelect"),
  countInput: $("#countInput"),
  availableCount: $("#availableCount"),
  buildStatus: $("#buildStatus"),
  questionNumber: $("#questionNumber"),
  questionProgress: $("#questionProgress"),
  questionMeta: $("#questionMeta"),
  questionText: $("#questionText"),
  options: $("#options"),
  answerPanel: $("#answerPanel"),
  answerTitle: $("#answerTitle"),
  answerText: $("#answerText"),
  questionMap: $("#questionMap"),
  doneCount: $("#doneCount"),
  markedCount: $("#markedCount"),
  examCount: $("#examCount"),
  timerText: $("#timerText"),
  timerBtn: $("#timerBtn"),
  scoreText: $("#scoreText"),
  wrongCountText: $("#wrongCountText"),
  reviewText: $("#reviewText"),
  mapStatus: $("#mapStatus"),
  markBtn: $("#markBtn"),
  searchSubject: $("#searchSubject"),
  searchInput: $("#searchInput"),
  searchResults: $("#searchResults"),
  searchCount: $("#searchCount"),
  wrongList: $("#wrongList"),
  wrongSubtitle: $("#wrongSubtitle"),
  importGrid: $("#importGrid"),
  issueList: $("#issueList"),
  issueCount: $("#issueCount"),
  importSubtitle: $("#importSubtitle")
};

async function readJson(path, fallback) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    return fallback;
  }
}

function loadStore(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (error) {
    return fallback;
  }
}

function saveStore(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function normalizeQuestions(questions) {
  return questions.map((question) => ({
    ...question,
    tags: Array.isArray(question.tags) ? question.tags : [],
    options: Array.isArray(question.options) ? question.options : []
  }));
}

function allSubjects() {
  const fromBank = state.bank.subjects || [];
  const fromQuestions = state.bank.questions.map((question) => question.subject);
  return [...new Set([...fromBank, ...fromQuestions])].filter(Boolean);
}

function yearSessionValue(question) {
  return `${question.year}|${question.session}`;
}

function yearSessionLabel(value) {
  if (value === "all") return "混合年度";
  const [year, session] = value.split("|");
  return `${year} 年${session}`;
}

function populateControls() {
  const subjects = allSubjects();
  dom.subjectSelect.innerHTML = subjects
    .map((subject) => `<option value="${escapeAttr(subject)}">${escapeHtml(subject)}</option>`)
    .join("");

  dom.searchSubject.innerHTML = [
    "<option value=\"all\">全部科目</option>",
    ...subjects.map((subject) => `<option value="${escapeAttr(subject)}">${escapeHtml(subject)}</option>`)
  ].join("");

  const yearValues = [...new Set(state.bank.questions.map(yearSessionValue))]
    .sort((a, b) => {
      const [yearA, sessionA] = a.split("|");
      const [yearB, sessionB] = b.split("|");
      if (Number(yearB) !== Number(yearA)) return Number(yearB) - Number(yearA);
      return sessionB.localeCompare(sessionA, "zh-Hant");
    });

  dom.yearSelect.innerHTML = [
    "<option value=\"all\">混合年度</option>",
    ...yearValues.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(yearSessionLabel(value))}</option>`)
  ].join("");
}

function updateSideStats() {
  const manifest = state.manifest;
  const history = loadStore(HISTORY_KEY, []);
  const wrongItems = Object.values(loadStore(WRONG_KEY, {}));
  const scores = history.map((item) => item.score).filter((score) => Number.isFinite(score));
  const avg = scores.length ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length) : "--";

  $("#subjectTotal").textContent = String(allSubjects().length);
  $("#paperTotal").textContent = String(manifest?.totals?.questionPdfs ?? "--");
  $("#answerTotal").textContent = String(manifest?.totals?.answerPdfs ?? "--");
  $("#historyTotal").textContent = String(history.length);
  $("#wrongTotal").textContent = String(wrongItems.length);
  $("#avgScore").textContent = avg === "--" ? "--" : `${avg}`;

  const total = manifest?.totals?.questionPdfs || 0;
  const paired = manifest?.totals?.pairedQuestionPdfs || 0;
  const width = total ? Math.round((paired / total) * 100) : 0;
  $("#pairProgress").style.width = `${width}%`;
}

function updateAvailability() {
  const questions = filterQuestions();
  dom.availableCount.textContent = `${questions.length} 題可用`;
}

function filterQuestions(options = {}) {
  const subject = options.subject ?? dom.subjectSelect.value;
  const year = options.year ?? dom.yearSelect.value;
  const mode = options.mode ?? state.mode;
  let questions = state.bank.questions;

  if (mode === "wrong") {
    const wrongIds = new Set(Object.keys(loadStore(WRONG_KEY, {})));
    questions = questions.filter((question) => wrongIds.has(question.id));
  }

  if (subject && subject !== "all") {
    questions = questions.filter((question) => question.subject === subject);
  }

  if (year && year !== "all") {
    questions = questions.filter((question) => yearSessionValue(question) === year);
  }

  return questions;
}

function shuffle(items) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

function buildExam() {
  let pool = filterQuestions();
  const requestedCount = Math.max(1, Math.min(80, Number(dom.countInput.value) || 10));

  if (pool.length === 0 && state.mode === "wrong") {
    state.mode = "exam";
    setModeButton("exam");
    pool = filterQuestions({ mode: "exam" });
    dom.buildStatus.textContent = "目前沒有錯題，已改用一般題庫";
  }

  if (pool.length === 0) {
    pool = state.bank.questions;
  }

  const shuffled = shuffle(pool);
  const exam = [];
  while (exam.length < requestedCount && shuffled.length > 0) {
    exam.push(shuffled[exam.length % shuffled.length]);
    if (exam.length >= shuffled.length && shuffled.length < requestedCount) {
      break;
    }
  }

  state.exam = exam.slice(0, requestedCount);
  state.current = 0;
  state.answers = {};
  state.marked = new Set();
  state.submitted = false;
  resetTimer();
  dom.buildStatus.textContent = `已產生 ${state.exam.length} 題`;
  renderExam();
}

function setModeButton(mode) {
  state.mode = mode;
  $$(".segmented button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  updateAvailability();
}

function renderExam() {
  if (!state.exam.length) {
    dom.questionText.textContent = "尚未產生試卷";
    dom.options.innerHTML = "";
    dom.questionMap.innerHTML = "";
    return;
  }

  const question = state.exam[state.current];
  const selected = state.answers[question.id];
  const answeredCount = Object.keys(state.answers).length;
  const total = state.exam.length;

  dom.questionNumber.textContent = `第 ${state.current + 1} 題`;
  dom.questionProgress.textContent = `${state.current + 1} / ${total}`;
  dom.questionText.textContent = question.stem;
  dom.doneCount.textContent = String(answeredCount);
  dom.markedCount.textContent = String(state.marked.size);
  dom.examCount.textContent = String(total);
  dom.mapStatus.textContent = answeredCount ? `已答 ${answeredCount} 題` : "尚未作答";
  dom.markBtn.textContent = state.marked.has(question.id) ? "取消標記" : "標記";

  dom.questionMeta.innerHTML = [
    pill(question.subject, "green"),
    pill(`${question.year} 年${question.session}`, "blue"),
    pill(question.sourceQuestionNumber || "原始題號待校正", ""),
    pill(question.difficulty || "未標難度", "amber")
  ].join("");

  dom.options.innerHTML = question.options.map((option) => {
    const classes = ["option"];
    if (selected === option.key) classes.push("selected");
    if (state.submitted && option.key === question.answer) classes.push("correct");
    if (state.submitted && selected === option.key && option.key !== question.answer) classes.push("wrong");
    return `
      <button class="${classes.join(" ")}" type="button" data-answer="${escapeAttr(option.key)}">
        <span class="letter">${escapeHtml(option.key)}</span>
        <span>${escapeHtml(option.text)}</span>
      </button>
    `;
  }).join("");

  dom.options.querySelectorAll(".option").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.submitted) return;
      state.answers[question.id] = button.dataset.answer;
      if (state.mode === "practice") {
        showAnswer(true);
      }
      renderExam();
    });
  });

  showAnswer(dom.answerPanel.classList.contains("visible"));
  renderMap();
  renderScore();
}

function renderMap() {
  dom.questionMap.innerHTML = state.exam.map((question, index) => {
    const classes = [];
    if (index === state.current) classes.push("current");
    if (state.answers[question.id]) classes.push("done");
    if (state.marked.has(question.id)) classes.push("marked");
    return `<button class="${classes.join(" ")}" type="button" data-index="${index}">${index + 1}</button>`;
  }).join("");

  dom.questionMap.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.current = Number(button.dataset.index);
      dom.answerPanel.classList.remove("visible");
      renderExam();
    });
  });
}

function showAnswer(forceVisible) {
  const question = state.exam[state.current];
  if (!question) return;
  dom.answerTitle.textContent = `答案：${question.answer}`;
  dom.answerText.textContent = question.explanation || "尚未匯入解析。";
  dom.answerPanel.classList.toggle("visible", Boolean(forceVisible));
}

function renderScore() {
  if (!state.submitted) {
    dom.scoreText.textContent = "--";
    dom.wrongCountText.textContent = "--";
    dom.reviewText.textContent = "尚未交卷";
    return;
  }

  const result = calculateResult();
  dom.scoreText.textContent = `${result.score} 分`;
  dom.wrongCountText.textContent = `${result.wrong.length} 題`;
  dom.reviewText.textContent = result.wrong.length ? result.wrong[0].subject : "完成";
}

function calculateResult() {
  const wrong = [];
  let correct = 0;

  state.exam.forEach((question) => {
    if (state.answers[question.id] === question.answer) {
      correct += 1;
    } else {
      wrong.push(question);
    }
  });

  const score = state.exam.length ? Math.round((correct / state.exam.length) * 100) : 0;
  return { correct, wrong, score };
}

function submitExam() {
  if (!state.exam.length || state.submitted) return;
  state.submitted = true;
  stopTimer();

  const result = calculateResult();
  const wrongStore = loadStore(WRONG_KEY, {});

  state.exam.forEach((question) => {
    const selected = state.answers[question.id] || "";
    if (selected !== question.answer) {
      wrongStore[question.id] = {
        questionId: question.id,
        selected,
        savedAt: new Date().toISOString()
      };
    } else if (wrongStore[question.id]) {
      delete wrongStore[question.id];
    }
  });

  const history = loadStore(HISTORY_KEY, []);
  history.unshift({
    score: result.score,
    total: state.exam.length,
    correct: result.correct,
    subject: dom.subjectSelect.value,
    year: dom.yearSelect.value,
    elapsedSeconds: state.elapsedSeconds,
    finishedAt: new Date().toISOString()
  });

  saveStore(WRONG_KEY, wrongStore);
  saveStore(HISTORY_KEY, history.slice(0, 100));
  showAnswer(true);
  renderExam();
  renderWrongBook();
  updateSideStats();
}

function renderWrongBook() {
  const wrongStore = loadStore(WRONG_KEY, {});
  const wrongItems = Object.values(wrongStore)
    .map((item) => {
      const question = state.bank.questions.find((candidate) => candidate.id === item.questionId);
      return question ? { ...item, question } : null;
    })
    .filter(Boolean);

  dom.wrongSubtitle.textContent = `${wrongItems.length} 題`;

  if (!wrongItems.length) {
    dom.wrongList.innerHTML = "<div class=\"empty\">目前沒有錯題。</div>";
    return;
  }

  dom.wrongList.innerHTML = wrongItems.map(({ question, selected }) => `
    <article class="item">
      <h4>${escapeHtml(question.stem)}</h4>
      <p>${escapeHtml(question.subject)} · ${question.year} 年${escapeHtml(question.session)} · 你的答案 ${escapeHtml(selected || "未作答")} · 正解 ${escapeHtml(question.answer)}</p>
      <p>${escapeHtml(question.explanation || "尚未匯入解析。")}</p>
      <div class="item-actions">
        <button class="ghost-btn" type="button" data-practice="${escapeAttr(question.id)}">重新練習</button>
        <button class="ghost-btn" type="button" data-remove="${escapeAttr(question.id)}">移除</button>
      </div>
    </article>
  `).join("");

  dom.wrongList.querySelectorAll("[data-practice]").forEach((button) => {
    button.addEventListener("click", () => {
      const question = state.bank.questions.find((candidate) => candidate.id === button.dataset.practice);
      if (!question) return;
      state.exam = [question];
      state.current = 0;
      state.answers = {};
      state.marked = new Set();
      state.submitted = false;
      setView("exam");
      resetTimer();
      renderExam();
    });
  });

  dom.wrongList.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const store = loadStore(WRONG_KEY, {});
      delete store[button.dataset.remove];
      saveStore(WRONG_KEY, store);
      renderWrongBook();
      updateSideStats();
    });
  });
}

function renderSearch() {
  const subject = dom.searchSubject.value;
  const query = dom.searchInput.value.trim().toLowerCase();
  let results = state.bank.questions;

  if (subject !== "all") {
    results = results.filter((question) => question.subject === subject);
  }

  if (query) {
    results = results.filter((question) => {
      const haystack = [
        question.stem,
        question.subject,
        question.sourceFile,
        question.answerFile,
        ...(question.tags || [])
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }

  dom.searchCount.textContent = `${results.length} 筆`;

  if (!results.length) {
    dom.searchResults.innerHTML = "<div class=\"empty\">找不到符合條件的題目。</div>";
    return;
  }

  dom.searchResults.innerHTML = results.slice(0, 80).map((question) => `
    <article class="item">
      <h4>${escapeHtml(question.stem)}</h4>
      <p>${escapeHtml(question.subject)} · ${question.year} 年${escapeHtml(question.session)} · ${escapeHtml(question.sourceFile || "")}</p>
      <p>答案 ${escapeHtml(question.answer)} · ${escapeHtml((question.tags || []).join("、"))}</p>
    </article>
  `).join("");
}

function renderImport() {
  const manifest = state.manifest;
  if (!manifest) {
    dom.importSubtitle.textContent = "尚未產生來源清單";
    dom.importGrid.innerHTML = "<div class=\"empty\">請先執行匯入工具產生來源清單。</div>";
    dom.issueList.innerHTML = "<div class=\"empty\">尚無資料。</div>";
    dom.issueCount.textContent = "--";
    return;
  }

  const subjects = manifest.subjects || [];
  const issues = manifest.issues || [];
  dom.importSubtitle.textContent = `${manifest.totals.questionPdfs} 份試題 · ${manifest.totals.answerPdfs} 份解答`;
  dom.issueCount.textContent = `${issues.length} 筆`;

  dom.importGrid.innerHTML = subjects.map((subject) => `
    <article class="import-card">
      <h4>${escapeHtml(subject.name)}</h4>
      <div class="side-stat"><span>試題</span><strong>${subject.questionPdfs}</strong></div>
      <div class="side-stat"><span>已配對</span><strong>${subject.pairedQuestionPdfs}</strong></div>
      <div class="side-stat"><span>解答</span><strong>${subject.answerPdfs}</strong></div>
    </article>
  `).join("");

  if (!issues.length) {
    dom.issueList.innerHTML = "<div class=\"empty\">目前沒有配對問題。</div>";
    return;
  }

  dom.issueList.innerHTML = issues.map((issue) => `
    <article class="item">
      <h4>${escapeHtml(issue.title)}</h4>
      <p>${escapeHtml(issue.detail)}</p>
    </article>
  `).join("");
}

function setView(viewName) {
  $$(".view").forEach((view) => view.classList.remove("active"));
  $(`#${viewName}View`).classList.add("active");

  $$(".nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewName);
  });

  const titles = {
    exam: ["模擬考產生器", "依科目、年度與題數抽題，完成後保留錯題紀錄。"],
    wrong: ["錯題本", "保留本機作答紀錄，重新練習答錯題目。"],
    search: ["題庫搜尋", "依科目、關鍵字與來源查找題目。"],
    import: ["匯入狀態", "檢查試題檔案與解答檔案配對狀態。"]
  };

  dom.pageTitle.textContent = titles[viewName][0];
  dom.pageSubtitle.textContent = titles[viewName][1];
  if (viewName === "wrong") renderWrongBook();
  if (viewName === "search") renderSearch();
  if (viewName === "import") renderImport();
}

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function renderTimer() {
  dom.timerText.textContent = formatDuration(state.elapsedSeconds);
  dom.timerBtn.textContent = state.timerRunning ? "Ⅱ" : "▶";
  dom.timerBtn.title = state.timerRunning ? "暫停計時" : "繼續計時";
  dom.timerBtn.setAttribute("aria-label", state.timerRunning ? "暫停計時" : "繼續計時");
}

function startTimer() {
  window.clearInterval(state.timerId);
  state.timerRunning = true;
  state.timerId = window.setInterval(() => {
    if (!state.timerRunning || state.submitted) return;
    state.elapsedSeconds += 1;
    renderTimer();
  }, 1000);
  renderTimer();
}

function stopTimer() {
  state.timerRunning = false;
  window.clearInterval(state.timerId);
  renderTimer();
}

function resetTimer() {
  state.elapsedSeconds = 0;
  startTimer();
}

function pill(text, tone) {
  const className = tone ? `pill ${tone}` : "pill";
  return `<span class="${className}">${escapeHtml(text)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function bindEvents() {
  $$(".nav button").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });

  $$(".segmented button").forEach((button) => {
    button.addEventListener("click", () => setModeButton(button.dataset.mode));
  });

  $("#newExamBtn").addEventListener("click", buildExam);
  $("#submitBtn").addEventListener("click", submitExam);
  $("#printBtn").addEventListener("click", () => window.print());
  $("#reloadBtn").addEventListener("click", () => window.location.reload());
  $("#clearWrongBtn").addEventListener("click", () => {
    saveStore(WRONG_KEY, {});
    renderWrongBook();
    updateSideStats();
  });

  $("#wrongPracticeBtn").addEventListener("click", () => {
    setModeButton("wrong");
    setView("exam");
    buildExam();
  });

  $("#prevBtn").addEventListener("click", () => {
    state.current = Math.max(0, state.current - 1);
    dom.answerPanel.classList.remove("visible");
    renderExam();
  });

  $("#nextBtn").addEventListener("click", () => {
    state.current = Math.min(state.exam.length - 1, state.current + 1);
    dom.answerPanel.classList.remove("visible");
    renderExam();
  });

  $("#answerBtn").addEventListener("click", () => {
    showAnswer(!dom.answerPanel.classList.contains("visible"));
  });

  $("#markBtn").addEventListener("click", () => {
    const question = state.exam[state.current];
    if (!question) return;
    if (state.marked.has(question.id)) {
      state.marked.delete(question.id);
    } else {
      state.marked.add(question.id);
    }
    renderExam();
  });

  dom.timerBtn.addEventListener("click", () => {
    if (state.submitted) return;
    state.timerRunning = !state.timerRunning;
    renderTimer();
  });

  [dom.subjectSelect, dom.yearSelect, dom.countInput].forEach((control) => {
    control.addEventListener("change", updateAvailability);
    control.addEventListener("input", updateAvailability);
  });

  [dom.searchSubject, dom.searchInput].forEach((control) => {
    control.addEventListener("input", renderSearch);
    control.addEventListener("change", renderSearch);
  });
}

async function init() {
  const [bank, manifest] = await Promise.all([
    readJson(DATA_PATH, { subjects: [], questions: [] }),
    readJson(MANIFEST_PATH, null)
  ]);

  state.bank = {
    ...bank,
    questions: normalizeQuestions(bank.questions || [])
  };
  state.manifest = manifest;

  populateControls();
  bindEvents();
  updateSideStats();
  updateAvailability();
  buildExam();
  renderWrongBook();
  renderSearch();
  renderImport();
}

init();
