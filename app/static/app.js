(function () {
  "use strict";

  /* ---------- тема (тёмная по умолчанию, хранится только выбор) ---------- */

  var root = document.documentElement;
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var light = root.getAttribute("data-theme") !== "light";
      if (light) root.setAttribute("data-theme", "light");
      else root.removeAttribute("data-theme");
      try { localStorage.setItem("blog-theme", light ? "light" : "dark"); } catch (e) {}
    });
  }

  /* ---------- сайдбар на мобильных ---------- */

  var aside = document.querySelector(".sidebar");
  var overlay = document.querySelector(".sidebar-overlay");
  var menuBtn = document.getElementById("menu-toggle");
  function setSidebar(open) {
    if (aside) aside.setAttribute("data-open", open ? "true" : "false");
    if (overlay) overlay.setAttribute("data-open", open ? "true" : "false");
    if (menuBtn) menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (menuBtn) menuBtn.addEventListener("click", function () {
    setSidebar(aside.getAttribute("data-open") !== "true");
  });
  if (overlay) overlay.addEventListener("click", function () { setSidebar(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setSidebar(false); });

  /* ---------- копирование ---------- */

  function copyText(text, btn, okLabel) {
    var restLabel = btn.textContent;
    function done(ok) {
      btn.textContent = ok ? okLabel : "Не удалось скопировать";
      setTimeout(function () { btn.textContent = restLabel; }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      return;
    }
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      done(true);
    } catch (e) {
      done(false);
    }
  }

  document.addEventListener("click", function (e) {
    var codeBtn = e.target.closest(".code-copy");
    if (codeBtn) {
      var code = codeBtn.parentNode.querySelector("code");
      if (code) copyText(code.textContent, codeBtn, "Скопировано");
      return;
    }
    if (e.target.id === "share-article-btn") {
      copyText(location.href.split("#")[0], e.target, "Ссылка скопирована");
    }
  });

  /* ---------- подсветка кода ---------- */

  // Подсвечиваем только блоки с явно указанным языком (```bash и т.п.).
  if (window.hljs) {
    document.querySelectorAll(".article-body pre code[class*='language-']").forEach(function (el) {
      hljs.highlightElement(el);
    });
  }

  /* ---------- cookie-баннер и Яндекс.Метрика ---------- */

  var CONSENT = "cookie_consent";
  var banner = document.getElementById("cookie-banner");
  var metrikaId = document.body.getAttribute("data-metrika-id");

  function getConsent() {
    var m = document.cookie.match(/(?:^|;\s*)cookie_consent=(accepted|declined)/);
    return m ? m[1] : null;
  }

  function setConsent(value) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = CONSENT + "=" + value + "; Max-Age=31536000; Path=/; SameSite=Lax" + secure;
  }

  function removeAnalyticsCookies() {
    document.cookie.split(";").forEach(function (c) {
      var name = c.split("=")[0].trim();
      if (/^_ym/.test(name)) {
        document.cookie = name + "=; Max-Age=0; Path=/";
        document.cookie = name + "=; Max-Age=0; Path=/; Domain=." + location.hostname;
      }
    });
  }

  function loadMetrika() {
    if (!metrikaId || window.ym) return;
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0];
      k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");
    window.ym(Number(metrikaId), "init", { clickmap: true, trackLinks: true, accurateTrackBounce: true });
  }

  if (banner) {
    var consent = getConsent();
    if (consent === "accepted") loadMetrika();
    else if (!consent) banner.hidden = false;

    banner.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-consent]");
      if (!btn) return;
      var value = btn.getAttribute("data-consent");
      var wasAccepted = getConsent() === "accepted";
      setConsent(value);
      banner.hidden = true;
      if (value === "accepted") loadMetrika();
      else if (wasAccepted) {
        removeAnalyticsCookies();
        location.reload(); // выгрузить уже запущенный счётчик
      }
    });

    var settingsBtn = document.getElementById("cookie-settings");
    if (settingsBtn) settingsBtn.addEventListener("click", function () { banner.hidden = false; });
  }
})();
