(function () {
  "use strict";

  var form = document.querySelector(".editor");
  if (!form) return;

  var area = document.getElementById("body_md");
  var preview = document.getElementById("preview");
  var hint = document.getElementById("editor-hint");
  var tabs = form.querySelectorAll(".editor-tabs button[data-tab]");
  var csrf = form.querySelector("[name=csrf_token]").value;
  var draftKey = "blog-draft:" + form.getAttribute("data-key");

  function say(text, isError) {
    hint.textContent = text;
    hint.classList.toggle("editor-hint--error", !!isError);
  }
  var defaultHint = hint.textContent;

  /* ---------- вкладки: текст / превью ---------- */

  function showTab(name) {
    tabs.forEach(function (b) { b.setAttribute("aria-selected", String(b.getAttribute("data-tab") === name)); });
    area.hidden = name !== "write";
    preview.hidden = name !== "preview";
    if (name === "preview") renderPreview();
  }

  function renderPreview() {
    preview.innerHTML = "<p class='editor-loading'>Собираю превью…</p>";
    var data = new FormData();
    data.append("body_md", area.value);
    data.append("csrf_token", csrf);
    fetch(form.getAttribute("data-preview-url"), { method: "POST", body: data, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        preview.innerHTML = j.html || "";
        if (window.hljs) {
          preview.querySelectorAll("pre code[class*='language-']").forEach(function (el) { hljs.highlightElement(el); });
        }
      })
      .catch(function () { preview.innerHTML = "<p class='editor-loading'>Не удалось собрать превью.</p>"; });
  }

  tabs.forEach(function (b) {
    b.addEventListener("click", function () { showTab(b.getAttribute("data-tab")); });
  });

  /* ---------- вставка текста в позицию курсора ---------- */

  function insertAtCursor(text) {
    var start = area.selectionStart, end = area.selectionEnd;
    area.value = area.value.slice(0, start) + text + area.value.slice(end);
    area.selectionStart = area.selectionEnd = start + text.length;
    area.focus();
    saveDraft();
  }

  /* ---------- загрузка картинок ---------- */

  function uploadFile(file) {
    if (!file || !/^image\//.test(file.type)) {
      say("Можно загружать только картинки.", true);
      return;
    }
    say("Загружаю " + file.name + "…");
    var data = new FormData();
    data.append("file", file);
    data.append("csrf_token", csrf);
    fetch(form.getAttribute("data-upload-url"), { method: "POST", body: data, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { say(res.j.error || "Не удалось загрузить файл.", true); return; }
        insertAtCursor("\n\n" + res.j.markdown + "\n\n");
        say("Картинка добавлена: " + res.j.url);
      })
      .catch(function () { say("Не удалось загрузить файл.", true); });
  }

  var fileInput = document.getElementById("image-input");
  document.getElementById("insert-image").addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (fileInput.files[0]) uploadFile(fileInput.files[0]);
    fileInput.value = "";
  });

  area.addEventListener("dragover", function (e) { e.preventDefault(); area.classList.add("md-input--drop"); });
  area.addEventListener("dragleave", function () { area.classList.remove("md-input--drop"); });
  area.addEventListener("drop", function (e) {
    e.preventDefault();
    area.classList.remove("md-input--drop");
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
  area.addEventListener("paste", function (e) {
    var items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === "file" && /^image\//.test(items[i].type)) {
        e.preventDefault();
        uploadFile(items[i].getAsFile());
        return;
      }
    }
  });

  /* ---------- Tab внутри текста ---------- */

  area.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      insertAtCursor("    ");
    }
  });

  /* ---------- черновик в браузере (на случай закрытой вкладки) ---------- */

  var saveTimer = null;
  function saveDraft() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try { localStorage.setItem(draftKey, JSON.stringify({ body: area.value, ts: Date.now() })); } catch (e) {}
    }, 500);
  }
  area.addEventListener("input", function () { saveDraft(); if (hint.textContent !== defaultHint) say(defaultHint); });

  try {
    var saved = JSON.parse(localStorage.getItem(draftKey) || "null");
    if (saved && saved.body && saved.body !== area.value) {
      var when = new Date(saved.ts).toLocaleString("ru-RU");
      if (confirm("В браузере остался несохранённый текст от " + when + ". Восстановить его?")) {
        area.value = saved.body;
      } else {
        localStorage.removeItem(draftKey);
      }
    }
  } catch (e) {}

  form.addEventListener("submit", function () {
    try { localStorage.removeItem(draftKey); } catch (e) {}
  });

  /* ---------- Ctrl+S сохраняет ---------- */

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();
