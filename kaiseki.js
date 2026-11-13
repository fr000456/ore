// ==UserScript==
// @name         kaiseki
// @namespace    http://tampermonkey.net/
// @version      0.8
// @updateURL   https://raw.githubusercontent.com/fr000456/ore/main/kaiseki.js
// @downloadURL https://raw.githubusercontent.com/fr000456/ore/main/kaiseki.js
// @match        https://race.netkeiba.com/race/shutuba.html*
// @match        https://nar.netkeiba.com/race/shutuba.html*
// @match        https://race.netkeiba.com/race/shutuba_abroad.html*
// @match        https://db.netkeiba.com/horse/*
// @run-at       document-idle
// @grant       GM.xmlHttpRequest
// @connect     localhost
// @connect     127.0.0.1
// @connect     db.netkeiba.com
// @require https://code.jquery.com/jquery-3.6.0.min.js
// @require https://raw.githubusercontent.com/fr000456/ore/main/const.js
// @require https://raw.githubusercontent.com/fr000456/ore/main/common.js?v=2
// @require https://raw.githubusercontent.com/fr000456/ore/main/html.js
// ==/UserScript==

(function ($) {
  // -----------------------------------------------------------------------
  // 出馬表から非表示iframeとして読み込まれた馬詳細ページの処理
  // -----------------------------------------------------------------------
  if (
    window.location.hostname === "db.netkeiba.com" &&
    window.location.search.includes("from_shutuba=1")
  ) {
    handleIframeHorsePage();
    return;
  }

  if (window.__kaisekiInitDone) return;
  window.__kaisekiInitDone = true;

  // DOM揃ったら初期化
  function waitForElement(selector, callback, interval = 100, timeout = 5000) {
    const start = Date.now();
    const timer = setInterval(() => {
      if ($(selector).length) {
        clearInterval(timer);
        callback();
      } else if (Date.now() - start > timeout) {
        clearInterval(timer);
        console.warn("waitForElement timeout: " + selector);
      }
    }, interval);
  }

  function getRaceClassValue(text, gradeTypeClass = "") {
    const gradeTypeMatch = gradeTypeClass.match(/\bIcon_GradeType([123])\b/);
    if (gradeTypeMatch) {
      return String({ 1: 9, 2: 8, 3: 7 }[gradeTypeMatch[1]]);
    }
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

  async function saveShutubaRacePage() {
    const raceId = new URL(window.location.href).searchParams.get("race_id");
    if (
      window.location.hostname !== "race.netkeiba.com" ||
      !window.location.pathname.endsWith("/race/shutuba.html") ||
      !/^\d{12}$/.test(raceId || "")
    ) {
      throw new Error("出馬表ページまたはレースIDが不正です。");
    }

    const table = document.querySelector("table.Shutuba_Table");
    if (!table) {
      throw new Error("出馬表テーブルが見つかりません。");
    }

    const title = document.querySelector("title")?.textContent || "";
    const dateMatch = title.match(
      /(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日/,
    );
    const raceData = document.querySelector(".RaceData01")?.textContent || "";
    const course = document.querySelectorAll(".RaceData02 span")[1]
      ?.textContent.trim() || null;
    const distanceMatch = raceData.match(/(\d+)\s*m/);
    const surfaceMatch = raceData.match(/(芝|ダ|障)/);
    const raceName = document.querySelector(".RaceName")?.textContent.trim() ||
      null;
    const gradeTypeClass =
      document.querySelector(".RaceName .Icon_GradeType")?.className || "";
    const raceClass = getRaceClassValue(
      `${raceName || ""} ${title}`,
      gradeTypeClass,
    );

    if (!dateMatch || !course || !distanceMatch || !surfaceMatch) {
      throw new Error(
        `出馬表からレース情報を取得できません (race_id=${raceId})`,
      );
    }

    const race = {
      race_id: raceId,
      race_date: `${dateMatch[1]}/${dateMatch[2].padStart(2, "0")}/${dateMatch[3].padStart(2, "0")}`,
      course,
      surface: { 芝: "芝", ダ: "ダート", 障: "障害" }[surfaceMatch[1]],
      distance: Number(distanceMatch[1]),
      race_class: raceClass,
      declared_field_size: table.querySelectorAll("tr.HorseList").length || null,
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
    const snapshotId = `shutuba-${raceId}-${hash}`;
    const sentKey = `raceEntrySaved:shutuba:${raceId}`;
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
          page_type: "shutuba",
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
      responseData.page_type !== "shutuba" ||
      responseData.snapshot_id !== snapshotId
    ) {
      throw new Error("API応答が保存内容と一致しません。");
    }

    markRaceSnapshotSaved(sentKey, snapshotId);
    return "saved";
  }

  // -----------------------------------------------------------------------
  // 出馬表ボタン用: 非表示iframeによる馬ページ描画待ち保存処理
  // -----------------------------------------------------------------------

  /**
   * db.netkeiba.com の iframe 内で実行される処理:
   * テーブル描画完了を待ってから /save_horse_for_race に送信し、親へ postMessage で通知する。
   */
  function handleIframeHorsePage() {
    const horseId = window.location.pathname.match(/horse\/([A-Za-z0-9\-]+)/)?.[1];
    const urlParams = new URLSearchParams(window.location.search);
    const raceDate = urlParams.get("race_date");

    if (!horseId) {
      window.parent.postMessage({ type: "horse_saved_from_iframe", horseId: null, error: "horseId not found" }, "*");
      return;
    }

    const start = Date.now();
    const timer = setInterval(() => {
      const resultsTable = document.querySelector(".db_h_race_results");
      const rows = document.querySelectorAll(".db_h_race_results tbody tr");
      const prof = document.querySelector(".db_prof_table");
      const elapsed = Date.now() - start;

      let isReady = false;
      if (resultsTable) {
        if (rows.length > 0) {
          // 行が存在し、テキストが描画されているか判定
          for (const tr of rows) {
            if (tr.textContent.trim()) {
              isReady = true;
              break;
            }
          }
        } else if (elapsed >= 2000) {
          // 2秒待っても行が0件なら、本当に未出走馬と判定
          isReady = true;
        }
      }

      // 描画完了または最大10秒待機で送信
      if (isReady || elapsed > 10000) {
        clearInterval(timer);

        const wrapper = document.createElement("div");
        if (prof) wrapper.appendChild(prof.cloneNode(true));
        if (resultsTable) wrapper.appendChild(resultsTable.cloneNode(true));

        const extractedHtml = wrapper.innerHTML;

        fetch("http://localhost:5000/save_horse_for_race", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ horseId, html: extractedHtml, raceDate, force: false }),
        })
          .then((res) => res.json())
          .then((data) => {
            window.parent.postMessage(
              { type: "horse_saved_from_iframe", horseId, success: true, result: data },
              "*",
            );
          })
          .catch((err) => {
            window.parent.postMessage(
              { type: "horse_saved_from_iframe", horseId, success: false, error: err.message },
              "*",
            );
          });
      }
    }, 250);
  }

  /**
   * 出馬表ページ側:
   * 非表示iframeを使い、1頭ずつ安全な間隔（1秒）を空けて順次描画・保存する。
   */
  async function saveAllHorsesForRace(horseIds, raceDate, statusEl) {
    const results = { saved: 0, skipped: 0, failed: [], skippedDetails: [] };

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
      statusEl.text(`[${i + 1}/${horseIds.length}頭] 馬データ描画・保存中... (${horseId})`);

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

          // iframe に対象馬のURLを設定
          iframe.src = `https://db.netkeiba.com/horse/${horseId}/?from_shutuba=1&race_date=${encodeURIComponent(raceDate)}`;
        });

        console.log(`[horse save iframe] ${horseId}:`, result);

        if (!result.success) {
          results.failed.push({ horseId, reason: result.error });
        } else if (result.result?.skipped) {
          results.skipped++;
          results.skippedDetails.push(`${horseId} (DB:${result.result.db_race_count} >= HTML:${result.result.html_race_count})`);
        } else {
          results.saved++;
        }
      } catch (error) {
        console.error(`[horse save] ${horseId} 失敗:`, error);
        results.failed.push({ horseId, reason: error.message });
      }

      // アクセス制限防止のためのインターバル（約1秒）
      if (i < horseIds.length - 1) {
        statusEl.text(`[${i + 1}/${horseIds.length}頭] 待機中...`);
        await new Promise((r) => setTimeout(r, 1000));
      }
    }

    // 後始末
    if (iframe && iframe.parentNode) {
      iframe.parentNode.removeChild(iframe);
    }

    // 保存完了後、親ページの horseHtmlCache を破棄して「適性」「解析」で最新DBデータを読めるようにする
    if (typeof horseHtmlCache !== "undefined") {
      horseIds.forEach((id) => delete horseHtmlCache[id]);
    }

    // 結果サマリーを表示
    let summary = `馬データ: 更新${results.saved}頭 / スキップ${results.skipped}頭`;
    if (results.skippedDetails.length > 0) {
      console.log("[horse save] スキップ内訳:", results.skippedDetails);
    }
    if (results.failed.length > 0) {
      summary += ` / 失敗${results.failed.length}頭`;
      console.warn("[horse save] 失敗した馬:", results.failed);
    }
    statusEl.text(summary);

    return results;
  }

  // -----------------------------------------------------------------------

  async function kaiseki(aFunc, useFirstBlinker = true) {
    const a = $(".HorseName").find("a");

    $("#kaiseki").val("解析中...");

    const firstBlinkers = useFirstBlinker ? await getFirstBlinkerHorses() : [];

    // 馬IDリストを収集
    const horseIds = [];
    const horseMap = {};
    for (let index = 0; index < a.length; index++) {
      const horse = a.eq(index);
      const href = horse.attr("href");
      const match = href.match(/horse\/([A-Za-z0-9\-]+)/);

      if (!match) continue;

      const horseId = match[1].trim();
      horseIds.push(horseId);
      horseMap[horseId] = { horse, index };
    }

    if (horseIds.length === 0) {
      $("#kaiseki").val("解析");
      return;
    }

    // 対象レース日付を取得（バッチAPIに渡し、未来レースを除外するため）
    // getRaceDate() は [year, month, date] 配列を返すので YYYY/MM/DD 形式に変換
    const raceDateArr = getRaceDate ? getRaceDate() : null;
    const raceDateStr = raceDateArr
      ? `${String(raceDateArr[0]).padStart(4, "0")}/${String(raceDateArr[1]).padStart(2, "0")}/${String(raceDateArr[2]).padStart(2, "0")}`
      : null;

    // 対象レースのコース・距離・馬場を出馬表ページから取得（解析・適性判定用）
    let targetCourse = null;
    let targetDistance = null;
    let targetSurface = null;
    const raceData01 = $(".RaceData01");
    if (raceData01.length > 0) {
      const rtext = raceData01.text();
      if (rtext.includes("障")) targetCourse = "障";
      else if (rtext.includes("芝")) targetCourse = "芝";
      else if (rtext.includes("ダ")) targetCourse = "ダ";
      const distMatch = rtext.match(/(\d{4})m/);
      if (distMatch) targetDistance = parseInt(distMatch[1], 10);
      // 馬場を取得
      if (rtext.includes("芝")) targetSurface = "芝";
      else if (rtext.includes("ダ")) targetSurface = "ダート";
    }

    // JSONを受け取る関数（解析・適性・馬場・ローテ・内回り）とHTMLを受け取る関数（備考・血統）に分岐
    const jsonFuncs = [funcKaiseki, funcTekisei, funcBaba, funcRota, funcUchi];
    const isJsonFunc = jsonFuncs.includes(aFunc);

    let horses = {};
    if (isJsonFunc) {
      // バッチAPIを1回呼び出し（全馬分の過去レースデータを一括取得）
      try {
        const response = await fetch("http://localhost:5000/batch_horse_data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            horse_ids: horseIds,
            race_date: raceDateStr,
          }),
        });

        if (response.ok) {
          const result = await response.json();
          horses = result.horses || {};
        } else {
          console.error("バッチデータ取得エラー:", response.status);
        }
      } catch (e) {
        console.error("バッチデータ取得失敗:", e);
      }
    }

    const promises = [];
    for (const horseId of horseIds) {
      const { horse, index } = horseMap[horseId];

      if (isJsonFunc) {
        // 解析・適性・馬場・ローテ・内回り：JSONデータを渡す
        const horseData = horses[horseId] || {
          horse_id: horseId,
          horse_name: null,
          sire: null,
          dam: null,
          banushi: null,
          race_history: [],
        };
        const p = aFunc(horseData, horse, index, firstBlinkers, targetCourse, targetDistance, targetSurface);
        promises.push(p);
      } else {
        // 馬場・ローテ・内回り・備考・血統など：従来通りHTMLを渡す
        const p = getHtmlFromMap(horseId).then((html) => {
          if (!html) return;
          setIndex(html);
          return aFunc(html, horse, index, firstBlinkers);
        });
        promises.push(p);
      }
    }

    await Promise.all(promises);

    changeCss();

    $("#kaiseki").val("解析");
  }

  // ページ初期化
  function initPageWrapper() {
    try {
      initPage(); // あなたの initPage 関数
    } catch (e) {
      console.error("initPage error:", e);
    }
  }

  waitForElement("#AllRaceSubMenu, #shutuba_menu", initPageWrapper);

  //functionたち
  const initFunc = function (html, a, index) {
    changeTableDtl(a, index);
  };

  const funcKaiseki = function (horseData, a, index, firstBlinkers, targetCourse, targetDistance, targetSurface) {
    doKaiseki(horseData, a, firstBlinkers, targetCourse, targetDistance, targetSurface);
  };

  const funcTekisei = function (horseData, a, index) {
    tekisei(horseData, index);
    return Promise.resolve();
  };

  const funcBaba = function (horseData, a, index) {
    tekisei(horseData, index, "baba");
    return Promise.resolve();
  };

  const funcRota = function (horseData, a, index) {
    tekisei(horseData, index, "rota");
    return Promise.resolve();
  };

  const funcUchi = function (horseData, a, index) {
    tekisei(horseData, index, "uchi");
    return Promise.resolve();
  };

  const funcBikou = function (html, a, index) {
    bikou(html, index);
  };

  function rota() {
    kaiseki(funcRota, false);
  }

  function kettou() {
    kaiseki(kettouFunc, false);
  }

  function baba() {
    kaiseki(funcBaba, false);
  }

  function uchi() {
    kaiseki(funcUchi, false);
  }

  function biko() {
    kaiseki(funcBikou, false);
  }

  function initPage() {
    //ボタン追加
    addButton();
    //イベント追加
    bindFunc();
    //定数設定
    setConst();
    changeTableHd();
    kaiseki(initFunc, false);

    //とりあえず
    $("#AllRaceSubMenu").append(
      '<input type="button" value="HTMLキャッシュ破棄" id="clearHorseCache">',
    );
    $("#clearHorseCache").on("click", () => {
      const count = Object.keys(horseHtmlCache).length;

      for (const k in horseHtmlCache) {
        delete horseHtmlCache[k];
      }

      console.log(`🗑️ horseHtmlCache を ${count} 件削除`);
      alert(`horseHtmlCache を ${count} 件削除しました`);
    });

    // AI予想ボタン追加
    $("#AllRaceSubMenu").append(
      '<input type="button" value="AI予想" id="aiPredict"> ' +
      '<input type="button" value="過去検証" id="aiBacktest">',
    );
    if (
      window.location.hostname === "race.netkeiba.com" &&
      window.location.pathname.endsWith("/race/shutuba.html")
    ) {
      $("#AllRaceSubMenu").append(
        ' <input type="button" value="出馬表をDBに保存" id="saveRaceEntry"> ' +
        '<span id="saveRaceEntryStatus" role="status" aria-live="polite"></span>',
      );
      $("#saveRaceEntry").on("click", async function () {
        const button = $(this);
        const status = $("#saveRaceEntryStatus");
        button.prop("disabled", true);

        try {
          // ① race_master / race_entry / race_entry_snapshot に保存（既存処理）
          status.text("出馬表保存中...");
          const raceResult = await saveShutubaRacePage();
          status.text(
            raceResult === "already_saved"
              ? "出馬表保存済み / 馬データ取得準備中..."
              : "出馬表保存成功 / 馬データ取得準備中...",
          );

          // ② レース日付を取得（タイトルから: "2026年11月1日" 形式）
          const title = $("title").text();
          const dateMatch = title.match(
            /(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日/,
          );
          if (!dateMatch) {
            throw new Error("レース日付をタイトルから取得できません");
          }
          const raceDate = `${dateMatch[1]}/${dateMatch[2].padStart(2, "0")}/${dateMatch[3].padStart(2, "0")}`;

          // ③ 出馬表から horse_id リストを収集
          const horseIds = [];
          $(".HorseName")
            .find("a")
            .each(function () {
              const href = $(this).attr("href");
              if (href) {
                const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
                if (match && !horseIds.includes(match[1])) {
                  horseIds.push(match[1]);
                }
              }
            });

          if (horseIds.length === 0) {
            status.text("出馬表保存成功（出走馬のIDが見つかりません）");
            return;
          }

          // ④ 各馬の過去走データを順次取得・更新（raceDate より前のみ保存）
          await saveAllHorsesForRace(horseIds, raceDate, status);
        } catch (error) {
          console.error("[race save] 出馬表保存失敗", error);
          status.text("保存失敗: " + error.message);
        } finally {
          button.prop("disabled", false);
        }
      });
    }
    $("#aiPredict").on("click", function () {
      aiPredict(false);
    });
    $("#aiBacktest").on("click", function () {
      aiPredict(true);
    });
  }

  function changeCss() {
    $(".HorseList td").css(horseCss);
    $(".HorseInfo").removeClass("HorseInfo");
    $(".Jockey").removeClass("Jockey");
    $(".Trainer").removeClass("Trainer");
    $(".selectBox").removeClass("selectBox");

    $(".Shutuba_Table")
      .find("tbody")
      .find("tr")
      .mouseover(function () {
        $(".Selected").removeClass("Selected");
        $(this).attr("style", "background-color:#C2EEFF");
        //$(this).attr("style","background-color:#fdf2c1");
      });
    $(".Shutuba_Table")
      .find("tbody")
      .find("tr")
      .mouseout(function () {
        $(this).attr("style", "background-color:");
      });
  }

  function bindFunc() {
    $("#kaiseki").on("click", function () {
      kaiseki(funcKaiseki);
    });
    $("#baba").on("click", function () {
      baba();
    });
    $("#tekisei").on("click", function () {
      kaiseki(funcTekisei, false);
    });
    $("#kettou").on("click", function () {
      kettou();
    });
    $("#rota").on("click", function () {
      rota();
    });
    $("#uchi").on("click", function () {
      uchi();
    });
    $("#bikou").on("click", function () {
      biko();
    });

    //血統初期値
    $("#AllRaceSubMenu")
      .append('<input type="button" value="ボールドルーラ―" id="bold">')
      .append('<input type="button" value="Vice Regent" id="vice">')
      .append('<input type="button" value="Danzig" id="danzig">');
    $("#bold").on("click", function () {
      bold();
    });
    $("#vice").on("click", function () {
      vice();
    });
    $("#danzig").on("click", function () {
      danzig();
    });
  }

  function bold() {
    $("#kettou1").val("Secretariat");
    $("#kettou2").val("Storm");
    kettou();
  }

  function vice() {
    $("#kettou1").val("Vice Regent");
    $("#kettou2").val("");
    kettou();
  }

  function danzig() {
    $("#kettou1").val("Danzig");
    $("#kettou2").val("Nijinsky");
    kettou();
  }

  function setConst() {
    //コース
    if ($(".RaceData01").find('span:contains("障")').length > 0) {
      course = "障";
    } else if ($(".RaceData01").find('span:contains("芝")').length > 0) {
      course = "芝";
    } else if ($(".RaceData01").find('span:contains("ダ")').length > 0) {
      course = "ダ";
    }
  }

  function parseRaceData(html) {
    return $("<div>").html(html).find("#data").find("tbody").find("tr");
  }

  function rotation(html, a, index) {
    const data = parseRaceData(html);

    let yasumi = [0, 0, 0, 0];
    let futu = [0, 0, 0, 0];
    let ni = [0, 0, 0, 0];
    let san = [0, 0, 0, 0];
    let tukai = [0, 0, 0, 0];
    let count = 0;
    let pDate = null;

    for (let i = data.length - 1; i >= 0; i--) {
      const tr = data.eq(i);
      const date = tr
        .find("td")
        .eq(hidukeIndex)
        .text()
        .trim()
        .slice(-10)
        .split("/");

      if (pDate != null) {
        if (kankaku(date, pDate) > 90) {
          //リセット
          count = 0;
          yasumi = getTyakujun(yasumi, tr);
        } else if (kankaku(date, pDate) > 53) {
          count = 0;
          futu = getTyakujun(futu, tr);
        }
      } else {
        yasumi = getTyakujun(yasumi, tr);
      }

      if (count == 1) {
        ni = getTyakujun(ni, tr);
      } else if (count == 2) {
        san = getTyakujun(san, tr);
      } else if (count > 2) {
        tukai = getTyakujun(tukai, tr);
      }

      count++;
      pDate = date;
    }

    switch (a.find("#tataki").val()) {
      case "0":
        addSeiseki($("#rotaTd" + index), futu);
        break;
      case "1":
        addSeiseki($("#rotaTd" + index), yasumi);
        break;
      case "2":
        addSeiseki($("#rotaTd" + index), ni);
        break;
      case "3":
        addSeiseki($("#rotaTd" + index), san);
        break;
      case "4":
        addSeiseki($("#rotaTd" + index), tukai);
        break;
    }
  }

  function addTatakiHtml(a, tatakiFlg) {
    const tatakiHidden = $("<input></input>", {
      type: "hidden",
      id: "tataki",
      value: tatakiFlg,
    });
    a.append(tatakiHidden);
  }

  function babakaiseki(html, a, index) {
    const data = parseRaceData(html);

    let seisekiVal = [0, 0, 0, 0];
    const babaVal = ["", "", "", ""];

    const babaMap = [
      { id: "#ryou", val: "良", index: 0 },
      { id: "#yaya", val: "稍", index: 1 },
      { id: "#omo", val: "重", index: 2 },
      { id: "#fu", val: "不", index: 3 },
    ];

    babaMap.forEach(({ id, val, index: idx }) => {
      if ($(id).prop("checked")) {
        babaVal[idx] = val;
      }
    });

    // 距離欄に馬場指定があれば馬場成績もそれに合わせる（getTyakujunはグローバルcourseを見る）
    const kyoriSurface = parseKyoriFilter($("#kyori").val()).surface;
    const prevCourse = course;
    if (kyoriSurface === "芝") course = "芝";
    else if (kyoriSurface === "ダート") course = "ダ";
    else if (kyoriSurface === "障害") course = "障";

    try {
      seisekiVal = getSeisekiVal(data, babaIndex, babaVal);
    } finally {
      course = prevCourse;
    }

    addSeiseki($("#babaTd" + index), seisekiVal);
  }

  function uchimawari(html, index) {
    const data = parseRaceData(html);

    if (data.length == 0) {
      return false;
    }

    let seisekiVal = [0, 0, 0, 0];

    for (let i = 0; i < corseUchi.length; i++) {
      const tgtTr = data
        .find("td:eq(" + corseIndex + "):contains(" + corseUchi[i][0] + ")")
        .parent()
        .find("td:eq(" + kyoriIndex + "):contains(" + corseUchi[i][1] + ")")
        .parent();
      for (let j = 0; j < tgtTr.length; j++) {
        seisekiVal = getTyakujun(seisekiVal, tgtTr.eq(j));
      }
    }

    addSeiseki($("#corseTd" + index), seisekiVal);
  }

  function bikou(html, index) {
    const data = parseRaceData(html);
    if (data.length == 0) {
      return false;
    }

    const td = data.find("td");
    const bikouVal = td.eq(bikouIndex).html();

    $("#bikouTd" + index).text(bikouVal.replace(/&nbsp;/g, ""));
  }

  // --- JSONデータ用ヘルパー関数（tekisei等で使用） ---

  function getSeisekiValFromJson(raceHistory, field, targetVals) {
    const result = [0, 0, 0, 0];
    for (const race of raceHistory) {
      const val = race[field];
      if (targetVals.length === 0 || targetVals.includes(val)) {
        const finish = race.finish_position;
        if (finish != null && finish <= 4) {
          result[finish - 1]++;
        } else if (finish != null) {
          result[3]++;
        }
      }
    }
    return result;
  }

  // 距離絞り込み値（例: "芝1200", "ダ1700", "1400m", "1200"）を距離と馬場に分解
  function parseKyoriFilter(kyoriVal) {
    const s = String(kyoriVal || "").trim();
    const distance = parseInt(s.replace(/[^0-9]/g, ""), 10);
    let surface = null;
    if (s.includes("芝")) surface = "芝";
    else if (s.includes("ダ")) surface = "ダート";
    else if (s.includes("障")) surface = "障害";
    return { distance: Number.isNaN(distance) ? null : distance, surface };
  }

  function matchKyoriFilter(race, filter) {
    if (filter.distance != null && race.distance != filter.distance) return false;
    if (filter.surface && normSurface(race.surface) !== filter.surface) return false;
    return true;
  }

  // "芝"/"ダート"/"ダ"/"障害"/"障" 等を "芝"/"ダート"/"障害" に正規化
  function normSurface(s) {
    s = s || "";
    if (s.includes("障")) return "障害";
    if (s.includes("ダ")) return "ダート";
    if (s.includes("芝")) return "芝";
    return s;
  }

  function addTuukaFromJson(tgt, raceHistory) {
    if (raceHistory.length === 0) return;
    const firstRace = raceHistory[0];
    const tuukaVal = firstRace.passing_order || "";
    const color = firstRace.last_3f_rank != null ? `rank_${firstRace.last_3f_rank}` : null;
    const colorMap = {
      rank_1: classR1ml,
      rank_2: classR2ml,
      rank_3: classR3ml,
    };
    const cssClass = colorMap[color];
    if (cssClass) {
      tgt.text(tuukaVal).addClass(cssClass);
    } else {
      tgt.text(tuukaVal);
    }
  }

  function tekisei(horseData, index, mode = "all") {
    const raceHistory = horseData.race_history || [];

    if (raceHistory.length == 0) {
      return false;
    }
    let seisekiVal = [0, 0, 0, 0];

    const kyoriVal = $("#kyori").val();
    const corseVal = $("#corse").val();
    const kyoriFilter = parseKyoriFilter(kyoriVal);

    // 表示成績は馬場ごとに独立して集計。
    // 距離欄に馬場指定（芝/ダ/障）があればそれを優先し、なければページの馬場を使う
    const pageSurface =
      course === "芝" ? "芝" : course === "ダ" ? "ダート" : course === "障" ? "障害" : null;
    const displaySurface = kyoriFilter.surface || pageSurface;
    const displayRaces = raceHistory.filter(
      (r) => !displaySurface || normSurface(r.surface) === displaySurface
    );

    const hidariSeisekiVal = getSeisekiValFromJson(displayRaces, "course", corseHidari);
    //左回り
    if (corseHidari.includes(corseVal)) {
      addSeiseki($("#hidariTd" + index), hidariSeisekiVal);
    } else {
      //右回り（左回りレースを除外）
      const migiRaces = displayRaces.filter(
        (r) => !corseHidari.includes(r.course || "")
      );
      const migiSeisekiVal = getSeisekiValFromJson(migiRaces, "course", []);
      addSeiseki($("#migiTd" + index), migiSeisekiVal);
    }
    //コース
    const corseRaces = displayRaces.filter((r) => r.course == corseVal);
    seisekiVal = getSeisekiValFromJson(corseRaces, "course", []);
    addSeiseki($("#corseTd" + index), seisekiVal);

    //距離
    const kyoriRaces = displayRaces.filter((r) => matchKyoriFilter(r, kyoriFilter));
    seisekiVal = getSeisekiValFromJson(kyoriRaces, "distance", []);
    addSeiseki($("#kyoriTd" + index), seisekiVal);

    //両方
    const ryouRaces = displayRaces.filter(
      (r) => r.course == corseVal && matchKyoriFilter(r, kyoriFilter)
    );
    seisekiVal = getSeisekiValFromJson(ryouRaces, "distance", []);
    addSeiseki($("#ryouTd" + index), seisekiVal);

    //通過順
    if (mode === "all" || mode === "tuuka") {
      addTuukaFromJson($("#tuukaTd" + index), raceHistory);
    }

    //馬場（JSON版）
    if (mode === "all" || mode === "baba") {
      const babaRaces = displayRaces.filter((r) => {
        const tc = r.track_condition || "";
        const checked = [];
        if ($("#ryou").prop("checked")) checked.push("良");
        if ($("#yaya").prop("checked")) checked.push("稍");
        if ($("#omo").prop("checked")) checked.push("重");
        if ($("#fu").prop("checked")) checked.push("不");
        return checked.length === 0 || checked.includes(tc);
      });
      const babaSeisekiVal = getSeisekiValFromJson(babaRaces, "finish_position", []);
      addSeiseki($("#babaTd" + index), babaSeisekiVal);
    }

    //ローテ（JSON版）
    if (mode === "all" || mode === "rota") {
      let yasumi = [0, 0, 0, 0];
      let futu = [0, 0, 0, 0];
      let ni = [0, 0, 0, 0];
      let san = [0, 0, 0, 0];
      let tukai = [0, 0, 0, 0];
      let count = 0;
      let pDate = null;

      for (let i = raceHistory.length - 1; i >= 0; i--) {
        const r = raceHistory[i];
        const dateStr = r.race_date || "";
        const date = dateStr.split("/").map(Number);

        if (pDate != null) {
          if (kankaku(date, pDate) > 90) {
            count = 0;
            yasumi = addSeisekiToArray(yasumi, r.finish_position);
          } else if (kankaku(date, pDate) > 53) {
            count = 0;
            futu = addSeisekiToArray(futu, r.finish_position);
          }
        } else {
          yasumi = addSeisekiToArray(yasumi, r.finish_position);
        }

        if (count == 1) {
          ni = addSeisekiToArray(ni, r.finish_position);
        } else if (count == 2) {
          san = addSeisekiToArray(san, r.finish_position);
        } else if (count > 2) {
          tukai = addSeisekiToArray(tukai, r.finish_position);
        }

        count++;
        pDate = date;
      }

      switch ($("#tataki").val()) {
        case "0":
          addSeiseki($("#rotaTd" + index), futu);
          break;
        case "1":
          addSeiseki($("#rotaTd" + index), yasumi);
          break;
        case "2":
          addSeiseki($("#rotaTd" + index), ni);
          break;
        case "3":
          addSeiseki($("#rotaTd" + index), san);
          break;
        case "4":
          addSeiseki($("#rotaTd" + index), tukai);
          break;
      }
    }

    //内回り（JSON版）
    if (mode === "all" || mode === "uchi") {
      let uchiSeisekiVal = [0, 0, 0, 0];
      for (let i = 0; i < corseUchi.length; i++) {
        const [c, d] = corseUchi[i];
        const dist = parseInt(d.replace("芝", "").replace("ダ", ""));
        const uchiRaces = displayRaces.filter(
          (r) => r.course === c && r.distance === dist
        );
        for (let j = 0; j < uchiRaces.length; j++) {
          uchiSeisekiVal = addSeisekiToArray(uchiSeisekiVal, uchiRaces[j].finish_position);
        }
      }
      addSeiseki($("#uchiTd" + index), uchiSeisekiVal);
    }
  }

  function addSeisekiToArray(arr, finishPos) {
    if (finishPos === 1) arr[0]++;
    else if (finishPos === 2) arr[1]++;
    else if (finishPos === 3) arr[2]++;
    else arr[3]++;
    return arr;
  }

  function tataki(raceHistory, targetDate) {
    let ren = 1;
    let prevDate = targetDate;
    let lastIndex = 0;
    for (let index = 0; index < 4; index++) {
      if (index == raceHistory.length) {
        return 0;
      }
      const race = raceHistory[index];
      const dateStr = race.race_date || "";
      const date = dateStr.split("/").map(Number);

      if (index == 0) {
        //前走
        if (kankaku(prevDate, date) < 9) {
          //連闘
          ren = -1;
        } else if (kankaku(prevDate, date) < 17) {
          //中一週
          ren = 10;
        }
        if (kankaku(prevDate, date) > 90) {
          //休み明け
          return 1;
        } else if (kankaku(prevDate, date) > 60) {
          //なんもなし
          return 0;
        }
      } else {
        //前々走 or 前々々走
        if (kankaku(prevDate, date) > 53) {
          //叩き二走目 or 三走目
          return (index + 1) * ren;
        }
      }
      prevDate = date;
      lastIndex = index;
    }
    return lastIndex * ren;
  }

  function syoukyu(raceHistory) {
    //前走が1着
    if (raceHistory[0].finish_position === 1) {
      return false;
    }
    //前々走がＯＰ以上（DBのrace_classは0-9の数値文字列、5以上がOP以上）
    const prevClass = parseInt(raceHistory[1].race_class, 10);
    if (!isNaN(prevClass) && prevClass >= 5) {
      return false;
    }
    //前々走が1着以外
    if (raceHistory[1].finish_position !== 1) {
      return false;
    }
    return true;
  }

  function kyori(raceHistory, targetDistance, targetSurface) {
    // 目標距離が不明な場合は判定不可
    if (!targetDistance) return false;
    // 前走が同距離ではない
    if (raceHistory[0].distance !== targetDistance) {
      return false;
    }
    // 前走が同馬場ではない
    if (raceHistory[0].surface !== targetSurface) {
      return false;
    }
    // 二戦以上経験している（同距離・同馬場の出走が1回だけ）
    const sameDistSurfaceCount = raceHistory.filter((r) => r.distance === targetDistance && r.surface === targetSurface).length;
    if (sameDistSurfaceCount !== 1) {
      return false;
    }
    // 二走前以前に同馬場でその距離以下の出走がない
    const pastDistances = raceHistory.slice(1).filter((r) => r.surface === targetSurface).map((r) => r.distance).filter((d) => d != null);
    return !pastDistances.some((d) => d <= targetDistance);
  }

  function syougai(raceHistory, targetCourse) {
    //そもそも障害レースではない
    if (targetCourse !== "障") {
      return false;
    }
    return raceHistory.filter((r) => (r.surface || "").includes("障")).length === 1;
  }

  function dirt(raceHistory, targetSurface) {
    //そもそもダートレースではない
    if (targetSurface !== "ダート") {
      return false;
    }
    return raceHistory.filter((r) => (r.surface || "").includes("ダ")).length === 1;
  }

  function hatsu(raceHistory, targetCourse) {
    // 過去に targetCourse で走ったことがないかチェック
    return (
      raceHistory.filter((r) => (r.surface || "").includes(targetCourse)).length ===
      0
    );
  }

  function getRaceDate() {
    const title = $("title").text();
    const year = title.substr(title.lastIndexOf("年") - 4, 4);
    const month = title.slice(
      title.lastIndexOf("年") + 1,
      title.lastIndexOf("月"),
    );
    const date = title.slice(
      title.lastIndexOf("月") + 1,
      title.lastIndexOf("日"),
    );

    return [year, month, date];
  }

  function getRaceId() {
    const url = window.location.href;
    const match = url.match(/race_id=([A-Za-z0-9]+)/);
    return match ? match[1] : null;
  }

  let firstBlinkersCache = null;

  async function getFirstBlinkerHorses() {
    if (firstBlinkersCache !== null) {
      return firstBlinkersCache;
    }

    const raceId = getRaceId();
    if (!raceId) return [];

    return new Promise((resolve) => {
      const iframe = document.createElement("iframe");
      iframe.style.display = "none";
      iframe.src = `https://race.netkeiba.com/race/newspaper.html?race_id=${raceId}&rf=shutuba_submenu`;

      iframe.onload = function () {
        setTimeout(() => {
          try {
            const iframeDoc =
              iframe.contentDocument || iframe.contentWindow.document;
            const $iframeDoc = $(iframeDoc);
            const firstBlinkers = [];

            $iframeDoc.find(".Horse02").each(function () {
              const $horse = $(this);
              const $mark = $horse.find(".Mark.First");
              if ($mark.length > 0) {
                const horseLink = $horse.find("a").first();
                const horseId = horseLink
                  .attr("href")
                  ?.match(/horse\/([A-Za-z0-9\-]+)/)?.[1];
                if (horseId) {
                  firstBlinkers.push(horseId);
                }
              }
            });

            document.body.removeChild(iframe);
            firstBlinkersCache = firstBlinkers;
            resolve(firstBlinkers);
          } catch (e) {
            console.error("iframe access error:", e);
            document.body.removeChild(iframe);
            resolve([]);
          }
        }, 3000);
      };

      iframe.onerror = function () {
        console.error("iframe load error");
        document.body.removeChild(iframe);
        resolve([]);
      };

      document.body.appendChild(iframe);
    });
  }

  function analyzeRaceData(raceHistory, raceDate, targetCourse, targetDistance, targetSurface) {
    const hatsuFlag = hatsu(raceHistory, targetCourse);
    return {
      hatsu: hatsuFlag,
      dirt: dirt(raceHistory, targetSurface),
      syougai: syougai(raceHistory, targetCourse),
      syoukyu: raceHistory.length > 1 ? syoukyu(raceHistory) : false,
      kyori: hatsuFlag ? false : kyori(raceHistory, targetDistance, targetSurface),
      tataki: tataki(raceHistory, raceDate),
    };
  }

  function addMarks(a, flags, firstBlinkers) {
    if (flags.syougai) addMark(a, txtSyougai, colSyougai);
    if (flags.kyori) addMark(a, txtKyori, colKyori);

    let tatakiFlg = flags.tataki;
    if (tatakiFlg < 0) {
      addMark(a, txtRen, colRen); //連闘
      tatakiFlg = tatakiFlg * -1;
    }
    if (tatakiFlg > 9) {
      addMark(a, txtNaka, colNaka); //中一週
      tatakiFlg = tatakiFlg / 10;
    }
    switch (tatakiFlg) {
      case 0:
        break; //なんもなし
      case 1:
        addMark(a, txtYa, colYa);
        break; //休み明け
      case 2:
        addMark(a, txtNi, colNi);
        break; //二走目
      case 3:
        addMark(a, txtSan, colSan);
        break; //三走目
    }
    addTatakiHtml(a, tatakiFlg);

    if (flags.syoukyu) addMark(a, txtSyo, colSyo);
    if (flags.hatsu) addMark(a, txtHatsu, colHatsu);
    if (flags.dirt) addMark(a, txtDa, colDa);

    const horseId = a.attr("href")?.match(/horse\/([A-Za-z0-9\-]+)/)?.[1];
    if (firstBlinkers && horseId && firstBlinkers.includes(horseId)) {
      addMark(a, txtBlinker, colBlinker);
    }
  }

  // AI予想関数
  function aiPredict(forceBacktest = false) {
    const activeButton = forceBacktest ? $("#aiBacktest") : $("#aiPredict");
    activeButton.val(forceBacktest ? "過去検証中..." : "AI予想中...");

    // レース日付を取得（タイトルから）
    const title = $("title").text();
    const raceDateMatch = title.match(
      /(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日/,
    );
    if (!raceDateMatch) {
      alert("レース日付を取得できませんでした");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }
    const [, year, month, day] = raceDateMatch;
    const parsedRaceDate = new Date(
      Date.UTC(Number(year), Number(month) - 1, Number(day)),
    );
    if (
      parsedRaceDate.getUTCFullYear() !== Number(year) ||
      parsedRaceDate.getUTCMonth() !== Number(month) - 1 ||
      parsedRaceDate.getUTCDate() !== Number(day)
    ) {
      alert("レース日付を正しく読み取れませんでした");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }
    const raceDate = `${year}/${month.padStart(2, "0")}/${day.padStart(2, "0")}`;
    console.info("AI予想対象日:", raceDate);
    const now = new Date();
    const today = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("/");
    const isHistoricalRace = forceBacktest || raceDate < today;
    const raceId = new URL(window.location.href).searchParams.get("race_id");
    if (isHistoricalRace && !/^\d{12}$/.test(raceId || "")) {
      alert("過去レースの検証に必要なレースIDを取得できませんでした");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }

    // 出走馬のhorse_idを取得（リンクから直接取得）
    const horseIds = [];
    const horseGates = [];
    const horseLinks = [];

    $(".HorseName")
      .find("a")
      .each(function () {
        const href = $(this).attr("href");
        if (href) {
          // URLからhorse_idを抽出（例: /horse/2023104876 -> 2023104876）
          const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
          if (match) {
            horseIds.push(match[1]);
            const gateText = $(this)
              .closest("tr")
              .find('td[class*="Waku"]')
              .first()
              .text()
              .trim();
            horseGates.push(/^[1-8]$/.test(gateText) ? parseInt(gateText, 10) : null);
            horseLinks.push(href);
          }
        }
      });

    if (horseIds.length === 0) {
      alert("出走馬が見つかりません");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }

    // 出馬表から距離、馬場、競馬場を取得
    const raceData = $(".RaceData01").text();
    let raceDistance = null;
    let raceSurface = null;
    const raceCourse = $(".RaceData02").find("span").eq(1).text().trim();

    // 距離を抽出（例：芝1400m -> 1400）
    const distanceMatch = raceData.match(/(\d+)m/);
    if (distanceMatch) {
      raceDistance = parseInt(distanceMatch[1]);
    }

    // 馬場を抽出（芝・ダート）
    if (raceData.includes("芝")) {
      raceSurface = "芝";
    } else if (raceData.includes("ダ")) {
      raceSurface = "ダート";
    }

    const supportedCourses = [
      "東京",
      "中山",
      "京都",
      "阪神",
      "新潟",
      "中京",
      "札幌",
      "函館",
      "福島",
      "小倉",
    ];
    if (
      !raceDistance ||
      !raceSurface ||
      !supportedCourses.includes(raceCourse)
    ) {
      alert("レース条件（競馬場・芝/ダート・距離）を取得できませんでした");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }

    const raceName = `${$(".RaceName").first().text().trim()} ${$("title").text().trim()}`;
    const gradeTypeClass =
      $(".RaceName .Icon_GradeType").first().attr("class") || "";
    const gradeTypeMatch = gradeTypeClass.match(/\bIcon_GradeType([123])\b/);
    const gradeTypeRank = gradeTypeMatch
      ? { 1: 9, 2: 8, 3: 7 }[gradeTypeMatch[1]]
      : null;
    const matchedRaceRank = gradeTypeRank !== null
      ? [null, gradeTypeRank]
      : raceRank.find(([name]) => raceName.includes(name));
    if (!matchedRaceRank) {
      alert("レースクラスを取得できませんでした");
      activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      return;
    }

    // Historical races use a model trained only on races before that date.
    $.ajax({
      url: isHistoricalRace
        ? "http://127.0.0.1:5000/backtest/run"
        : "http://127.0.0.1:5000/predict",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(
        isHistoricalRace
          ? {
              race_id: raceId,
              target_race: {
                race_date: raceDate,
                course: raceCourse,
                surface: raceSurface,
                distance: raceDistance,
                race_class: matchedRaceRank[1],
                field_size: horseIds.length,
                horses: horseIds.map((horseId, index) => ({
                  horse_id: horseId,
                  gate: horseGates[index],
                })),
              },
            }
          : {
              horse_ids: horseIds,
              race_date: raceDate,
              race_distance: raceDistance,
              race_surface: raceSurface,
              race_course: raceCourse,
              race_class: matchedRaceRank[1],
              race_id: raceId,
              horse_gates: horseGates,
              field_size: horseIds.length,
            },
      ),
      success: function (response) {
        // 確率を出馬表に表示
        displayPredictions(
          response.predictions,
          horseLinks,
          response.prediction_mode === "backtest" || isHistoricalRace
            ? "backtest"
            : "live",
        );
        activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      },
      error: function (xhr, status, error) {
        console.error("AI予想エラー:", error);
        alert("AI予想エラー: " + (xhr.responseJSON?.error || error));
        activeButton.val(forceBacktest ? "過去検証" : "AI予想");
      },
    });
  }

  let sortOrder = "desc"; // 'desc' = 降順, 'asc' = 昇順

  function displayPredictions(predictions, horseLinks, predictionMode = "live") {
    // ヘッダーに「俺指数」カラムを追加
    const table = $(".ShutubaTable");
    if (table.length > 0) {
      const headerRow = table.find("tr").first();
      // ヘッダーにカラム追加（クリックでソート）
      const indexHeader = `
        <th class="my-index-header" style="cursor: pointer;">
          <div class="tablesorter-header-inner">
            <div class="Inner_Shutuba">
              <span class="HorseName">${predictionMode === "backtest" ? "俺指数（過去検証）" : "俺指数"}</span>
              <span class="sort_icon" style="display: block;">
                <i class="fas fa-sort"></i>
              </span>
            </div>
          </div>
        </th>
      `;
      headerRow.append(indexHeader);

      // ソート機能を追加
      headerRow.find(".my-index-header").on("click", function () {
        sortTableByIndex(table);
      });
    }

    // horse_idから予測値へのマップを作成
    const predictionMap = {};
    predictions.forEach(function (pred) {
      predictionMap[pred.horse_id] = pred;
    });

    // 各馬の確率を表示
    horseLinks.forEach(function (href) {
      // horse_idを抽出
      const horseId = href
        .replace("https://db.netkeiba.com/horse/", "")
        .replace("/", "");

      const prediction = predictionMap[horseId];
      if (prediction !== undefined) {
        const hasError = Boolean(prediction.error);
        const isExcluded = Boolean(prediction.excluded);
        const probability = prediction.probability;
        const displayValue = isExcluded || hasError
          ? "予測エラー"
          : `${(probability * 100).toFixed(1)}%`;

        // 該当する馬の行を探す
        $(".HorseName")
          .find("a")
          .each(function () {
            if ($(this).attr("href") === href) {
              // 馬の行の一番右のセルに指数を追加
              const row = $(this).closest("tr");
              // featuresを取得
              // 指数セルを追加
              row.append(
                `<td class="my-index-cell" data-value="${hasError || isExcluded ? 0 : probability}" style="text-align: center; font-weight: bold; color: ${hasError || isExcluded ? "#777" : "red"}; cursor: pointer;"${hasError || isExcluded ? ' title="クリックして理由を確認"' : ""}>${displayValue}</td>`,
              );
            }
          });
      }
    });

    // テーブル全体にクリックイベントを設定（イベントデリゲーション）
    table.off('click', '.my-index-cell').on('click', '.my-index-cell', function() {
      const probability = $(this).data('value');
      const row = $(this).closest('tr');
      const horseLink = row.find('.HorseName a');
      const href = horseLink.attr('href');
      const horseId = href.replace('https://db.netkeiba.com/horse/', '').replace('/', '');

      const prediction = predictions.find(p => p.horse_id === horseId);
      const features = prediction?.features;

      if (prediction?.excluded) {
        alert(`【${horseId}】\n${prediction.error || "予測対象外です。"}`);
        return;
      }

      let featureText = `【${horseId} の特徴量】\n確率: ${(probability * 100).toFixed(1)}%\n\n`;
      if (prediction?.error) {
        featureText = `【${horseId} の予測エラー】\n${prediction.error}`;
      } else if (features) {
        for (const [key, value] of Object.entries(features)) {
          featureText += `${key}: ${value}\n`;
        }
      } else {
        featureText += '特徴量がありません';
      }
      alert(featureText);
    });
  }

  function sortTableByIndex(table) {
    // ソート順を切り替え
    sortOrder = sortOrder === "desc" ? "asc" : "desc";

    // アイコンを更新
    const icon = table.find(".my-index-header .sort_icon i");
    icon.removeClass("fa-sort fa-sort-down fa-sort-up");
    icon.addClass(sortOrder === "desc" ? "fa-sort-down" : "fa-sort-up");

    // 行を取得（ヘッダーを除外）
    const rows = table.find("tr").slice(1).toArray();

    // 値でソート
    rows.sort(function (a, b) {
      const valA =
        parseFloat($(a).find(".my-index-cell").attr("data-value")) || 0;
      const valB =
        parseFloat($(b).find(".my-index-cell").attr("data-value")) || 0;

      if (sortOrder === "desc") {
        return valB - valA;
      } else {
        return valA - valB;
      }
    });

    // テーブルに行を再追加
    table.find("tr").slice(1).remove();
    rows.forEach(function (row) {
      table.append(row);
    });
  }

  function doKaiseki(horseData, a, firstBlinkers, targetCourse, targetDistance, targetSurface) {
    const raceHistory = horseData.race_history || [];
    const raceDate = getRaceDate();
    const banushiUrl = horseData.banushi;

    a.find("td").remove();
    a.find("img").remove();

    if (raceHistory.length == 0) {
      addMark(a, txtHatsu, colHatsu);
      if (banushiUrl) {
        const mark = $("<img></img>", { src: banushiUrl }).css({
          display: "inline-block",
          width: "16px",
          margin: "-1px 0",
          "margin-right": "8px",
        });
        a.prepend(mark);
      }
      return false;
    }

    const flags = analyzeRaceData(raceHistory, raceDate, targetCourse, targetDistance, targetSurface);
    addMarks(a, flags, firstBlinkers);

    if (banushiUrl) {
      const mark = $("<img></img>", { src: banushiUrl }).css({
        display: "inline-block",
        width: "16px",
        margin: "-1px 0",
        "margin-right": "8px",
      });
      a.prepend(mark);
    }
  }
})(jQuery);
