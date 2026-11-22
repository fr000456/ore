// ==UserScript==
// @name         result
// @match        https://db.netkeiba.com/race/*
// @exclude      https://db.netkeiba.com/race/list.html*
// @run-at       document-idle
// @grant        GM.xmlHttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/const.js?v=1
// @require      https://raw.githubusercontent.com/fr000456/ore/main/common.js?v=7
// @updateURL   https://raw.githubusercontent.com/fr000456/ore/main/result.js
// @downloadURL https://raw.githubusercontent.com/fr000456/ore/main/result.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/html.js?v=1
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
      return { status: "already_saved", race };
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
    return { status: "saved", race };
  }

  // 結果表から馬IDを収集（重複除去）
  function collectHorseIds(table) {
    const ids = [];
    table.querySelectorAll('a[href*="/horse/"]').forEach((a) => {
      const match = (a.getAttribute("href") || "").match(
        /horse\/([A-Za-z0-9-]*\d[A-Za-z0-9-]*)/,
      );
      if (match && !ids.includes(match[1])) ids.push(match[1]);
    });
    return ids;
  }

  // 'YYYY/MM/DD' の翌日を返す（今回のレースを保存対象に含めるため）
  function nextDay(dateStr) {
    const [y, m, d] = dateStr.split("/").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d + 1));
    return `${dt.getUTCFullYear()}/${String(dt.getUTCMonth() + 1).padStart(2, "0")}/${String(dt.getUTCDate()).padStart(2, "0")}`;
  }

  // kaiseki.js の saveAllHorsesForRace と同じロジック:
  // 隠しiframeで馬ページを1頭ずつ描画させ、kaiseki.js側の
  // handleIframeHorsePage が /save_horse_for_race へPOST→postMessageで結果を受け取る
  async function saveAllHorsesForRace(horseIds, cutoffDate, statusEl) {
    const results = { saved: 0, skipped: 0, failed: [] };

    let iframe = document.getElementById("horseSaveFrame");
    if (!iframe) {
      iframe = document.createElement("iframe");
      iframe.id = "horseSaveFrame";
      iframe.style.position = "fixed";
      iframe.style.width = "1px";
      iframe.style.height = "1px";
      iframe.style.left = "-9999px";
      iframe.style.top = "-9999px";
      iframe.style.visibility = "hidden";
      document.body.appendChild(iframe);
    }

    for (let i = 0; i < horseIds.length; i++) {
      const horseId = horseIds[i];
      statusEl.textContent = `[${i + 1}/${horseIds.length}頭] 馬データ描画・保存中... (${horseId})`;

      try {
        const result = await new Promise((resolve) => {
          let resolved = false;

          const onMessage = (event) => {
            if (
              event.data?.type === "horse_saved_from_iframe" &&
              event.data.horseId === horseId
            ) {
              window.removeEventListener("message", onMessage);
              resolved = true;
              resolve(event.data);
            }
          };
          window.addEventListener("message", onMessage);

          // タイムアウト監視（12秒）
          setTimeout(() => {
            if (!resolved) {
              window.removeEventListener("message", onMessage);
              resolve({
                success: false,
                error: "タイムアウト（描画が完了しませんでした）",
              });
            }
          }, 12000);

          iframe.src = `https://db.netkeiba.com/horse/${horseId}/?from_shutuba=1&race_date=${encodeURIComponent(cutoffDate)}`;
        });

        if (!result.success) {
          results.failed.push({ horseId, reason: result.error });
        } else if (result.result?.skipped) {
          results.skipped++;
        } else {
          results.saved++;
        }
      } catch (error) {
        console.error(`[horse save] ${horseId} 失敗:`, error);
        results.failed.push({ horseId, reason: error.message });
      }

      // アクセス制限防止のためのインターバル（約1秒）
      if (i < horseIds.length - 1) {
        statusEl.textContent = `[${i + 1}/${horseIds.length}頭] 待機中...`;
        await new Promise((r) => setTimeout(r, 1000));
      }
    }

    if (iframe && iframe.parentNode) {
      iframe.parentNode.removeChild(iframe);
    }

    // 保存完了後、horseHtmlCache を破棄して最新DBデータを読めるようにする
    if (typeof horseHtmlCache !== "undefined") {
      horseIds.forEach((id) => delete horseHtmlCache[id]);
    }

    let summary = ` / 馬データ: 更新${results.saved}頭 / スキップ${results.skipped}頭`;
    if (results.failed.length > 0) {
      summary += ` / 失敗${results.failed.length}頭`;
      console.warn("[horse save] 失敗した馬:", results.failed);
    }
    statusEl.textContent = summary;
    return results;
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
        status.textContent = saveResult.status === "already_saved"
          ? "保存成功（同一内容は保存済み） / 馬データ取得準備中..."
          : "保存成功 / 馬データ取得準備中...";

        // 出走馬の馬詳細（プロフィール＋過去走）を kaiseki.js と同じ
        // iframe描画待ちロジックで保存。カットオフはレース翌日とし、
        // 今回のレース結果も horse_data_dtl に含める。
        const horseIds = collectHorseIds(table);
        if (horseIds.length === 0) {
          status.textContent += "（出走馬IDが見つかりません）";
        } else {
          await saveAllHorsesForRace(
            horseIds,
            nextDay(saveResult.race.race_date),
            status,
          );
        }
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
