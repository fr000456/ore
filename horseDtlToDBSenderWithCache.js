// ==UserScript==
// @name         horseDtlToDBSenderWithCache
// @namespace    netkeiba
// @version      3.0
// @match        https://db.netkeiba.com/horse/*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";
  const STORAGE_KEY = "TimeIndexMode"; // 実際のキー名に注意
  localStorage.setItem(STORAGE_KEY, "normal");

  let sent = false;

  // =========================
  // 送信
  // =========================
  async function sendHtmlToServer(horseId, html, force = false) {
    if (sent && !force) return;

    if (!force) {
      sent = true;
    }

    try {
      const res = await fetch("http://localhost:5000/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ horseId, html, force }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);

      const data = await res.json();
      console.log(`📤 [${horseId}] 保存結果`, data);

      // 親ページキャッシュ更新
      if (!data.message?.includes("skipped") && window.opener) {
        window.opener.postMessage(
          { type: "updateHorseCache", horseId, html },
          "*",
        );
        console.log(`📝 [${horseId}] 親ページキャッシュ更新`);
      }
      return true;
    } catch (e) {
      console.error(`❌ [${horseId}] 保存失敗`, e);
      return false;
    }
  }

  // =========================
  // HTML抽出
  // =========================
  function extractHtmlAndSend() {
    const horseId = location.pathname.match(/horse\/([A-Za-z0-9\-]+)/)?.[1];
    if (!horseId) return;

    const prof = document.querySelector(".db_prof_table");
    const results = document.querySelector(".db_h_race_results");

    if (!results && !prof) return;

    const wrapper = document.createElement("div");

    if (prof) wrapper.appendChild(prof.cloneNode(true));
    if (results) wrapper.appendChild(results.cloneNode(true));

    const html = wrapper.innerHTML;

    console.log("🚀 送信開始");
    sendHtmlToServer(horseId, html);
  }

  function getVisibleTds(tr) {
    return Array.from(tr.querySelectorAll("td")).filter((td) => {
      return (
        !td.classList.contains("TimeIndexMasterCell01") &&
        !td.classList.contains("TimeIndexMasterHeadCell01")
      );
    });
  }

  // =========================
  // 完成判定（重要）
  // =========================
  function isTableReady() {
    const rows = document.querySelectorAll(".db_h_race_results tbody tr");

    // 未出走 → OK
    if (rows.length === 0) return true;

    // 何かしらテキストがあればOK（緩め判定）
    for (const tr of rows) {
      const tds = getVisibleTds(tr);

      for (const td of tds) {
        if (td.textContent.trim()) {
          return true;
        }
      }
    }

    return false;
  }

  // =========================
  // 待機処理（安定版）
  // =========================
  function waitForCompleteTable(callback, timeout = 15000) {
    const start = Date.now();

    function check() {
      if (isTableReady()) {
        console.log("✅ テーブル完成");
        callback();
        return;
      }

      if (Date.now() - start > timeout) {
        console.warn("⏰ タイムアウト → 強制取得");
        callback();
        return;
      }

      setTimeout(check, 300);
    }

    check();
  }

  // =========================
  // 起動
  // =========================
  function waitForPageReady() {
    const table = document.querySelector(".db_h_race_results");

    if (!table) {
      setTimeout(waitForPageReady, 200);
      return;
    }

    waitForCompleteTable(() => {
      extractHtmlAndSend();
      addForceButton();
    });
  }

  function addForceButton() {
    const btn = document.createElement("button");

    btn.textContent = "DB強制更新";

    btn.style.position = "fixed";
    btn.style.top = "10px";
    btn.style.right = "10px";
    btn.style.zIndex = "99999";

    btn.style.padding = "10px 20px";
    btn.style.fontSize = "16px";
    btn.style.fontWeight = "bold";

    btn.style.background = "#ff9800";
    btn.style.color = "white";

    btn.style.border = "none";
    btn.style.borderRadius = "8px";
    btn.style.cursor = "pointer";

    btn.onclick = async () => {
      btn.textContent = "更新中...";
      btn.disabled = true;

      const horseId = location.pathname.match(/horse\/([A-Za-z0-9\-]+)/)?.[1];

      const prof = document.querySelector(".db_prof_table");

      const results = document.querySelector(".db_h_race_results");

      const wrapper = document.createElement("div");

      if (prof) wrapper.appendChild(prof.cloneNode(true));
      if (results) wrapper.appendChild(results.cloneNode(true));

      const ok = await sendHtmlToServer(horseId, wrapper.innerHTML, true);

      if (ok) {
        btn.textContent = "完了";
        btn.style.background = "#4caf50";
      } else {
        btn.textContent = "失敗";
        btn.style.background = "#f44336";
        btn.disabled = false;
      }
    };

    document.body.appendChild(btn);
  }

  // =========================
  // エントリーポイント
  // =========================
  if (
    document.readyState === "complete" ||
    document.readyState === "interactive"
  ) {
    waitForPageReady();
  } else {
    window.addEventListener("DOMContentLoaded", waitForPageReady);
  }
})();
