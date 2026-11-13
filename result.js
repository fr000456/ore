// ==UserScript==
// @name         result
// @match        https://db.netkeiba.com/race/*
// @exclude      https://db.netkeiba.com/race/list.html*
// @run-at       document-idle
// @grant        GM.xmlHttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @require      https://cdn.jsdelivr.net/gh/fr000456/ore@main/const.js
// @require      https://cdn.jsdelivr.net/gh/fr000456/ore@main/common.js
// @updateURL   https://cdn.jsdelivr.net/gh/fr000456/ore@main/result.js
// @downloadURL https://cdn.jsdelivr.net/gh/fr000456/ore@main/result.js
// @require      https://cdn.jsdelivr.net/gh/fr000456/ore@main/html.js
// ==/UserScript==

(function () {
  "use strict";
  const $ = window.jQuery || jQuery;

  function getRaceClassValue(text) {
    const matchedRaceRank = raceRank.find(([name]) => text.includes(name));
    return matchedRaceRank ? String(matchedRaceRank[1]) : null;
  }

  function hasSavedRaceSnapshot(key, snapshotId) {
    try {
      return localStorage.getItem(key) === snapshotId;
    } catch (error) {
      console.warn("[race save] 保存済み状態を確認できません。", error);
      return false;
    }
  }

  function markRaceSnapshotSaved(key, snapshotId) {
    try {
      localStorage.setItem(key, snapshotId);
    } catch (error) {
      console.warn("[race save] 保存済み状態を記録できません。", error);
    }
  }

  function waitForResultTable(callback, timeout = 15000) {
    const startedAt = Date.now();
    const check = () => {
      const table = document.querySelector("table.race_table_01");
      const horseRows = table?.querySelectorAll('a[href*="/horse/"]').length || 0;
      if (horseRows > 0) {
        callback(table);
        return;
      }
      if (Date.now() - startedAt >= timeout) {
        console.error("[race save] 結果表の取得がタイムアウトしました。");
        return;
      }
      setTimeout(check, 250);
    };
    check();
  }

  async function saveResultRacePage(table) {
    const raceId = window.location.pathname.match(/\/race\/(\d{12})\/?$/)?.[1];
    if (!raceId || window.location.hostname !== "db.netkeiba.com") {
      throw new Error("結果ページまたはレースIDが不正です。");
    }

    const intro = document.querySelector(".data_intro");
    const introText = intro?.textContent.replace(/\s+/g, " ").trim() || "";
    const dateMatch = introText.match(
      /(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日/,
    );
    const courseMatch = introText.match(
      /(東京|中山|京都|阪神|新潟|中京|札幌|函館|福島|小倉)/,
    );
    const surfaceDistanceMatch = introText.match(
      /(芝|ダ|障)[^0-9]{0,12}(\d+)\s*m/,
    );
    const raceName = intro?.querySelector("h1")?.textContent.trim() || null;

    if (!dateMatch || !courseMatch || !surfaceDistanceMatch) {
      throw new Error(
        `結果ページからレース情報を取得できません (race_id=${raceId})`,
      );
    }

    const trackCondMatch = introText.match(
      /(?:芝|ダ|障|馬場)[^0-9]*?:\s*(良|稍重|稍|重|不良|不)/,
    );
    const trackCondition = trackCondMatch
      ? { 稍重: "稍", 不良: "不" }[trackCondMatch[1]] || trackCondMatch[1]
      : null;

    const race = {
      race_id: raceId,
      race_date: `${dateMatch[1]}/${dateMatch[2].padStart(2, "0")}/${dateMatch[3].padStart(2, "0")}`,
      course: courseMatch[1],
      surface: { 芝: "芝", ダ: "ダート", 障: "障害" }[surfaceDistanceMatch[1]],
      distance: Number(surfaceDistanceMatch[2]),
      race_class: getRaceClassValue(`${raceName || ""} ${introText}`),
      track_condition: trackCondition,
      declared_field_size: Array.from(table.querySelectorAll("tr"))
        .filter((row) => row.querySelector('a[href*="/horse/"]')).length,
      race_name: raceName,
    };

    const html = document.documentElement.outerHTML;
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(html),
    );
    const hash = Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    const snapshotId = `result-${raceId}-${hash}`;
    const sentKey = `raceEntrySaved:result:${raceId}`;
    if (hasSavedRaceSnapshot(sentKey, snapshotId)) {
      return "already_saved";
    }

    const response = await new Promise((resolve, reject) => {
      GM.xmlHttpRequest({
        method: "POST",
        url: "http://localhost:5000/save_race",
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify({
          race,
          page_type: "result",
          source_url: window.location.href,
          html,
          snapshot_id: snapshotId,
        }),
        timeout: 20000,
        onload: resolve,
        onerror: reject,
        ontimeout: () => reject(new Error("API通信がタイムアウトしました。")),
      });
    });
    if (response.status < 200 || response.status >= 300) {
      throw new Error(
        `HTTP ${response.status}: ${response.responseText || "保存に失敗しました。"}`,
      );
    }

    let responseData;
    try {
      responseData = JSON.parse(response.responseText);
    } catch (error) {
      throw new Error("APIの成功応答を解析できません。");
    }
    if (
      responseData.race_id !== raceId ||
      responseData.page_type !== "result" ||
      responseData.snapshot_id !== snapshotId
    ) {
      throw new Error("API応答が保存内容と一致しません。");
    }

    markRaceSnapshotSaved(sentKey, snapshotId);
    return "saved";
  }

  function addResultSaveButton(table) {
    if (document.getElementById("saveRaceResult")) return;

    const controls = document.createElement("div");
    controls.style.margin = "0.75em 0";
    const button = document.createElement("button");
    button.id = "saveRaceResult";
    button.type = "button";
    button.textContent = "結果をDBに保存";
    const status = document.createElement("span");
    status.id = "saveRaceResultStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.style.marginLeft = "0.5em";
    controls.append(button, status);
    table.parentNode.insertBefore(controls, table);

    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "保存中...";
      try {
        const saveResult = await saveResultRacePage(table);
        status.textContent = saveResult === "already_saved"
          ? "保存成功（同一内容は保存済み）"
          : "保存成功";
      } catch (error) {
        console.error("[race save] 結果保存失敗", error);
        status.textContent = "保存失敗";
      } finally {
        button.disabled = false;
      }
    });
  }

  (function ($$) {
    function kettou() {
      $$(".race_table_01")
        .find('a[href*="/horse/"]')
        .each(function (index) {
          ajax($$(this).attr("href")).then((html) => {
            kettouFunc(html, $$(this), index, "all");
          });
        });
    }
    function appendMenu() {
      try {
        var kaisekiUl = $$("<ul></ul>", {
          id: "kaisekiUl",
          class: "race_deta_menu",
        });

        // race_deta_menu 内に追加
        $$(".race_deta_menu").append(kaisekiUl);

        // UI構築
        kaisekiUl.append("<br><br>");
        kaisekiUl.append(
          '<li><input placeholder="血統1" type="text" id="kettou1" size="12"></li>',
        );
        kaisekiUl.append(
          '<li><input placeholder="血統2" type="text" id="kettou2" size="12"></li>',
        );
        kaisekiUl.append(
          '<li><input type="button" value="血統" id="kettou"></li>',
        );

        // イベント設定
        $$("#kettou").on("click", () => kettou());

        // 初期値
        $$("#kettou1").val("Danzig");
        $$("#kettou2").val("Nijinsky");

        // 別処理
        sonogo();
      } catch (e) {
        console.log("メニュー生成エラー:", e);
      }
    }
    function init() {
      appendMenu();
      waitForResultTable(addResultSaveButton);
    }

    init();
  })($); // ← ★ Tampermonkey jQuery を $$ として安全渡し
})();
