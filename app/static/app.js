/* 六点盲文排版台 — 前端逻辑（原生 JS，无外部依赖，可离线） */
"use strict";

const $ = (sel) => document.querySelector(sel);

const els = {
  input: $("#srcInput"),
  width: $("#widthInput"),
  count: $("#charCount"),
  btn: $("#btnTypeset"),
  btnSample: $("#btnSample"),
  btnClear: $("#btnClear"),
  errors: $("#errorBox"),
  panel: $("#resultPanel"),
  lines: $("#linesContainer"),
  stats: $("#statsBar"),
  download: $("#btnDownload"),
  copy: $("#btnCopy"),
};

let lastResult = null;

/* ---------------- 计数与校验 ---------------- */

function updateCount() {
  const n = els.input.value.length;
  els.count.textContent = String(n);
  els.count.parentElement.classList.toggle("over", n > 500);
}

els.input.addEventListener("input", updateCount);

/* ---------------- 发起排版 ---------------- */

async function doTypeset() {
  const text = els.input.value;
  const width = Number(els.width.value);

  // 前端即时校验（最终以服务端为准）
  const local = [];
  if (!/^[\x20\nA-Za-z0-9]*$/.test(text)) {
    local.push("含非法字符：仅允许 ASCII 字母、数字、空格与换行。");
  }
  if (text.length > 500) local.push("输入超过 500 个字符。");
  if (!/[A-Za-z0-9]/.test(text)) local.push("至少需要包含一个字母或数字。");
  if (!Number.isInteger(width) || width < 10 || width > 40) {
    local.push("每行格数须为 10～40 的整数。");
  }
  if (local.length) {
    showErrors([{ message: local.join("\n") }]);
    return;
  }

  els.btn.disabled = true;
  try {
    const resp = await fetch("/api/typeset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, width }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showErrors(data.errors || [{ message: "排版失败。" }]);
      return;
    }
    els.errors.hidden = true;
    renderResult(data);
  } catch (e) {
    showErrors([{ message: "请求失败：" + e }]);
  } finally {
    els.btn.disabled = false;
  }
}

function showErrors(errors) {
  els.panel.hidden = true;
  els.errors.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = `发现 ${errors.length} 处问题，请修正后重试：`;
  els.errors.appendChild(h);
  const ul = document.createElement("ul");
  for (const err of errors) {
    const li = document.createElement("li");
    li.textContent = err.message;
    if (typeof err.pos === "number") {
      li.title = "点击定位到输入位置";
      li.addEventListener("click", () => {
        els.input.focus();
        els.input.setSelectionRange(err.pos, err.pos + (err.length || 1));
      });
    }
    ul.appendChild(li);
  }
  els.errors.appendChild(ul);
  els.errors.hidden = false;
}

/* ---------------- 渲染盲文格 ---------------- */

// 点号 1..6 对应网格位置（左列 1/2/3，右列 4/5/6）
const DOT_ORDER = [1, 4, 2, 5, 3, 6];

function makeCell(cell) {
  const d = document.createElement("div");
  d.className = "cell " + cell.kind;

  const grid = document.createElement("div");
  grid.className = "dotgrid";
  const on = new Set(cell.dots);
  for (const dot of DOT_ORDER) {
    const s = document.createElement("span");
    s.className = "dot" + (on.has(dot) ? " on" : "");
    grid.appendChild(s);
  }
  d.appendChild(grid);

  if (cell.kind !== "space") {
    const u = document.createElement("span");
    u.className = "uni";
    u.textContent = cell.text;
    d.appendChild(u);
  }

  d.title = cell.note;
  return d;
}

function renderSourceLine(source) {
  // 原文行：空格淡化，行尾断词连字符高亮
  const div = document.createElement("div");
  div.className = "src-line";
  for (const ch of source) {
    const span = document.createElement("span");
    if (ch === " ") {
      span.className = "src-gap";
      span.textContent = "·";
    } else if (ch === "-") {
      span.className = "src-hyphen";
      span.textContent = "-";
    } else {
      span.textContent = ch;
    }
    div.appendChild(span);
  }
  return div;
}

function renderResult(r) {
  lastResult = r;
  els.panel.hidden = false;
  els.lines.innerHTML = "";
  els.stats.innerHTML = "";

  // 统计
  const stats = [
    `行宽：<b>${r.width}</b> 格`,
    `硬分段：<b>${r.paragraphs}</b> 段`,
    `共 <b>${r.total_lines}</b> 行`,
    `超宽词断词：<b>${r.breaks}</b> 次`,
    `数字续行重加标记：<b>${r.number_reopened}</b> 次`,
  ];
  els.stats.innerHTML = stats.map((s) => `<span>${s}</span>`).join("");

  for (const line of r.lines) {
    const row = document.createElement("div");
    row.className = "line-row";

    const no = document.createElement("div");
    no.className = "line-no";
    no.textContent = line.blank ? "" : String(line.index);

    const body = document.createElement("div");
    body.className = "line-body" + (line.blank ? " blank" : "");

    if (line.blank) {
      body.appendChild(document.createTextNode("（空段）"));
    } else {
      body.appendChild(renderSourceLine(line.source));

      const cells = document.createElement("div");
      cells.className = "cells";
      for (const c of line.cells) cells.appendChild(makeCell(c));
      body.appendChild(cells);

      const rem = document.createElement("div");
      rem.className = "remain";
      const pct = Math.round((line.used / r.width) * 100);
      rem.innerHTML =
        `用 ${line.used} 格 · 余 ${line.remain} 格` +
        `<span class="rail"><span class="fill" style="width:${pct}%"></span></span>`;
      body.appendChild(rem);
    }

    row.appendChild(no);
    row.appendChild(body);
    els.lines.appendChild(row);
  }

  els.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- 下载与复制 ---------------- */

function downloadBraille() {
  if (!lastResult) return;
  // 加 BOM，保证 Windows 记事本等工具正确识别 UTF-8
  const blob = new Blob(["﻿" + lastResult.braille_text], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "braille.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copyBraille() {
  if (!lastResult) return;
  const btn = els.copy;
  try {
    await navigator.clipboard.writeText(lastResult.braille_text);
    const old = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => (btn.textContent = old), 1500);
  } catch (e) {
    // 退化方案
    const ta = document.createElement("textarea");
    ta.value = lastResult.braille_text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

els.btn.addEventListener("click", doTypeset);
els.download.addEventListener("click", downloadBraille);
els.copy.addEventListener("click", copyBraille);

els.btnClear.addEventListener("click", () => {
  els.input.value = "";
  updateCount();
  els.errors.hidden = true;
  els.panel.hidden = true;
  els.input.focus();
});

els.btnSample.addEventListener("click", () => {
  els.input.value =
`Hello Braille
The quick brown fox
2026 007`;
  els.width.value = 16;
  updateCount();
  doTypeset();
});

els.input.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doTypeset();
  }
});

updateCount();

/* =======================================================================
 * 视图二：盲文识读
 * ===================================================================== */

const elsD = {
  input: $("#brInput"),
  count: $("#brCount"),
  btn: $("#btnDecode"),
  btnSample: $("#btnDecodeSample"),
  btnClear: $("#btnDecodeClear"),
  errors: $("#decodeErrorBox"),
  panel: $("#decodePanel"),
  output: $("#decodeOutput"),
  stats: $("#decodeStats"),
  copy: $("#btnDecodeCopy"),
};

let lastDecoded = null;

function updateBrCount() {
  const n = elsD.input.value.length;
  elsD.count.textContent = String(n);
  elsD.count.parentElement.classList.toggle("over", n > 500);
}
elsD.input.addEventListener("input", updateBrCount);

function showDecodeErrors(errors) {
  elsD.panel.hidden = true;
  elsD.errors.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = `发现 ${errors.length} 处问题，请修正后重试：`;
  elsD.errors.appendChild(h);
  const ul = document.createElement("ul");
  for (const err of errors) {
    const li = document.createElement("li");
    li.textContent = err.message;
    if (typeof err.pos === "number") {
      li.title = "点击定位到输入位置";
      li.addEventListener("click", () => {
        elsD.input.focus();
        elsD.input.setSelectionRange(err.pos, err.pos + (err.length || 1));
      });
    }
    ul.appendChild(li);
  }
  elsD.errors.appendChild(ul);
  elsD.errors.hidden = false;
}

async function doDecode() {
  const braille = elsD.input.value;
  const local = [];
  if (braille.length > 500) local.push("输入超过 500 格。");
  if (!braille) local.push("请输入至少一个盲文字母或数字格。");
  if (local.length) {
    showDecodeErrors([{ message: local.join("\n") }]);
    return;
  }

  elsD.btn.disabled = true;
  try {
    const resp = await fetch("/api/decode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ braille }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showDecodeErrors(data.errors || [{ message: "识读失败。" }]);
      return;
    }
    elsD.errors.hidden = true;
    lastDecoded = data;
    elsD.output.value = data.text;
    elsD.stats.innerHTML = [
      `输入：<b>${data.stats.input_cells}</b> 格`,
      `输出：<b>${data.stats.output_chars}</b> 个字符`,
      `行数：<b>${data.stats.lines}</b>`,
    ].map((s) => `<span>${s}</span>`).join("");
    elsD.panel.hidden = false;
    elsD.panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showDecodeErrors([{ message: "请求失败：" + e }]);
  } finally {
    elsD.btn.disabled = false;
  }
}

async function copyDecoded() {
  if (!lastDecoded) return;
  const btn = elsD.copy;
  try {
    await navigator.clipboard.writeText(lastDecoded.text);
    const old = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => (btn.textContent = old), 1500);
  } catch (e) {
    elsD.output.focus();
    elsD.output.select();
    document.execCommand("copy");
  }
}

elsD.btn.addEventListener("click", doDecode);
elsD.copy.addEventListener("click", copyDecoded);
elsD.btnClear.addEventListener("click", () => {
  elsD.input.value = "";
  updateBrCount();
  elsD.errors.hidden = true;
  elsD.panel.hidden = true;
  elsD.input.focus();
});
elsD.btnSample.addEventListener("click", () => {
  // Hello 2026 / Worldfamous 1026（World- 与 10- 为行尾断词续行，10 续行重新加 ⠼）
  const S = "⠀"; // 盲文空格 U+2800
  elsD.input.value =
    "⠠⠓⠑⠇⠇⠕" + S + "⠼⠃⠚⠃⠋\n" +
    "⠠⠺⠕⠗⠇⠙⠤\n" +
    "⠋⠁⠍⠕⠥⠎" + S + "⠼⠁⠚⠤\n" +
    "⠼⠃⠋";
  updateBrCount();
  doDecode();
});
elsD.input.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doDecode();
  }
});
updateBrCount();

/* ---------------- 视图切换 ---------------- */

const tabs = document.querySelectorAll("#viewTabs .tab");
const views = { typeset: $("#viewTypeset"), decode: $("#viewDecode") };

function switchView(name) {
  for (const tab of tabs) {
    tab.classList.toggle("active", tab.dataset.view === name);
  }
  views.typeset.hidden = name !== "typeset";
  views.decode.hidden = name !== "decode";
}
for (const tab of tabs) {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
}
