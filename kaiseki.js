// ==UserScript==
// @name         kaiseki
// @namespace    http://tampermonkey.net/
// @version      0.2
// @updateURL   https://raw.githubusercontent.com/fr000456/ore/main/kaiseki.js
// @downloadURL https://raw.githubusercontent.com/fr000456/ore/main/kaiseki.js
// @match        https://race.netkeiba.com/race/shutuba.html*
// @match        https://nar.netkeiba.com/race/shutuba.html*
// @match        https://race.netkeiba.com/race/shutuba_abroad.html*
// @run-at       document-idle
// @grant       GM.xmlHttpRequest
// @connect     localhost
// @connect     127.0.0.1
// @require https://code.jquery.com/jquery-3.6.0.min.js
// @require https://raw.githubusercontent.com/fr000456/ore/main/const.js
// @require https://raw.githubusercontent.com/fr000456/ore/main/common.js
// @require https://raw.githubusercontent.com/fr000456/ore/main/html.js
// ==/UserScript==

(function ($) {
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

  async function kaiseki(aFunc, useFirstBlinker = true) {
    const a = $(".HorseName").find("a");

    $("#kaiseki").val("解析中...");

    const firstBlinkers = useFirstBlinker ? await getFirstBlinkerHorses() : [];

    const promises = [];

    for (let index = 0; index < a.length; index++) {
      const horse = a.eq(index);
      const href = horse.attr("href");
      const match = href.match(/horse\/([A-Za-z0-9\-]+)/);

      if (!match) continue;

      const horseId = match[1].trim();

      const p = getHtmlFromMap(horseId).then((html) => {
        if (!html) return;

        setIndex(html);

        return aFunc(html, horse, index, firstBlinkers);
      });

      promises.push(p);
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

  const funcKaiseki = function (html, a, index, firstBlinkers) {
    doKaiseki(html, a, firstBlinkers);
  };

  const funcTekisei = function (html, a, index) {
    tekisei(html, index);
    return Promise.resolve();
  };

  const funcBaba = function (html, a, index) {
    babakaiseki(html, a, index);
  };

  const funcRota = function (html, a, index) {
    rotation(html, a, index);
  };

  const funcUchi = function (html, a, index) {
    uchimawari(html, index);
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
      '<input type="button" value="AI予想" id="aiPredict">',
    );
    $("#aiPredict").on("click", aiPredict);
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

    seisekiVal = getSeisekiVal(data, babaIndex, babaVal);
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

  function tekisei(html, index) {
    const data = parseRaceData(html);

    if (data.length == 0) {
      return false;
    }
    let seisekiVal = [0, 0, 0, 0];

    const kyoriVal = $("#kyori").val();
    const corseVal = $("#corse").val();

    const hidariSeisekiVal = getSeisekiVal(data, corseIndex, corseHidari);
    //左回り
    if (corseHidari.includes(corseVal)) {
      addSeiseki($("#hidariTd" + index), hidariSeisekiVal);
    } else {
      //右回り
      seisekiVal = getSeisekiValNot(data, corseIndex, hidariSeisekiVal);
      addSeiseki($("#migiTd" + index), seisekiVal);
    }
    //コース
    seisekiVal = getSeisekiVal(data, corseIndex, [corseVal]);
    addSeiseki($("#corseTd" + index), seisekiVal);

    //距離
    seisekiVal = getSeisekiVal(data, kyoriIndex, [kyoriVal]);
    addSeiseki($("#kyoriTd" + index), seisekiVal);

    //両方
    seisekiVal = getMultiSeisekiVal(
      data,
      corseIndex,
      kyoriIndex,
      corseVal,
      kyoriVal,
    );
    addSeiseki($("#ryouTd" + index), seisekiVal);

    //通過順
    addTuuka($("#tuukaTd" + index), data);
  }

  function addTuuka(tgt, data) {
    const td = $(data).eq(0).find("td");
    const tuukaVal = td.eq(tuukaIndex).html();
    const color = td.eq(agariIndex).attr("class");

    const colorMap = {
      rank_1: classR1ml,
      rank_2: classR2ml,
      rank_3: classR3ml,
    };

    const cssClass = colorMap[color?.trim()];
    if (cssClass) {
      tgt.text(tuukaVal).addClass(cssClass);
    } else {
      tgt.text(tuukaVal);
    }
  }

  function tataki(data, raceDate) {
    let ren = 1;
    let prevDate = raceDate;
    let lastIndex = 0;
    for (let index = 0; index < 4; index++) {
      if (index == data.length) {
        return 0;
      }
      const tr = data.eq(index);
      const date = tr
        .find("td")
        .eq(hidukeIndex)
        .text()
        .trim()
        .slice(-10)
        .split("/");

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

  function syoukyu(data) {
    //前走が1着
    if (data.eq(0).find("td").eq(tyakuIndex).text() == "1") {
      return false;
    }
    //前々走がＯＰ以上
    if (getRank(data.eq(1).find("td").eq(raceIndex).text()) > 4) {
      return false;
    }
    //前々走が1着以外
    if (data.eq(1).find("td").eq(tyakuIndex).text() != "1") {
      return false;
    }
    return true;
  }

  function kyori(data) {
    const kyoriStr = $(".RaceData01").find("span").eq(0).text().slice(1, -1);
    //前走が同距離ではない
    if (data.eq(0).find("td").eq(kyoriIndex).text() != kyoriStr) {
      return false;
    }
    //二戦以上経験している
    if (
      data.find("td:eq(" + kyoriIndex + "):contains(" + kyoriStr + ")").length >
      1
    ) {
      return false;
    }
    return true;
  }

  function syougai(data) {
    //そもそも障害レースではない
    if (course != "障") {
      return false;
    }
    return data.find("td:eq(" + kyoriIndex + "):contains(障)").length == 1;
  }

  function dirt(data) {
    //そもそもダートレースではない
    if (course != "ダ") {
      return false;
    }
    return data.find("td:eq(" + kyoriIndex + "):contains(ダ)").length == 1;
  }

  function hatsu(data) {
    return (
      data.find("td:eq(" + kyoriIndex + "):contains(" + course + ")").length ==
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

  function analyzeRaceData(data, raceDate) {
    return {
      hatsu: hatsu(data),
      dirt: dirt(data),
      syougai: syougai(data),
      syoukyu: data.length > 1 ? syoukyu(data) : false,
      kyori: kyori(data),
      tataki: tataki(data, raceDate),
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
  function aiPredict() {
    $("#aiPredict").val("AI予想中...");

    // レース日付を取得（タイトルから）
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
    const raceDate = `${year}/${month}/${date}`;

    // 出走馬のhorse_idを取得（リンクから直接取得）
    const horseIds = [];
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
            horseLinks.push(href);
          }
        }
      });

    if (horseIds.length === 0) {
      alert("出走馬が見つかりません");
      $("#aiPredict").val("AI予想");
      return;
    }

    // 出馬表から距離、馬場、競馬場を取得
    const raceData = $(".RaceData01").find("span").eq(0).text();
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
      $("#aiPredict").val("AI予想");
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
      $("#aiPredict").val("AI予想");
      return;
    }

    // Flask APIにリクエスト
    $.ajax({
      url: "http://127.0.0.1:5000/predict",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({
        horse_ids: horseIds,
        race_date: raceDate,
        race_distance: raceDistance,
        race_surface: raceSurface,
        race_course: raceCourse,
        race_class: matchedRaceRank[1],
      }),
      success: function (response) {
        // 確率を出馬表に表示
        displayPredictions(response.predictions, horseLinks);
        $("#aiPredict").val("AI予想");
      },
      error: function (xhr, status, error) {
        console.error("AI予想エラー:", error);
        alert("AI予想エラー: " + (xhr.responseJSON?.error || error));
        $("#aiPredict").val("AI予想");
      },
    });
  }

  let sortOrder = "desc"; // 'desc' = 降順, 'asc' = 昇順

  function displayPredictions(predictions, horseLinks) {
    // ヘッダーに「俺指数」カラムを追加
    const table = $(".ShutubaTable");
    if (table.length > 0) {
      const headerRow = table.find("tr").first();
      // ヘッダーにカラム追加（クリックでソート）
      const indexHeader = `
        <th class="my-index-header" style="cursor: pointer;">
          <div class="tablesorter-header-inner">
            <div class="Inner_Shutuba">
              <span class="HorseName">俺指数</span>
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
      predictionMap[pred.horse_id] = pred.probability;
    });

    // 各馬の確率を表示
    horseLinks.forEach(function (href) {
      // horse_idを抽出
      const horseId = href
        .replace("https://db.netkeiba.com/horse/", "")
        .replace("/", "");

      const probability = predictionMap[horseId];
      if (probability !== undefined) {
        const percent = (probability * 100).toFixed(1) + "%";

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
                `<td class="my-index-cell" data-value="${probability}" style="text-align: center; font-weight: bold; color: red; cursor: pointer;">${percent}</td>`,
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

      const features = predictions.find(p => p.horse_id === horseId)?.features;

      let featureText = `【${horseId} の特徴量】\n確率: ${(probability * 100).toFixed(1)}%\n\n`;
      if (features) {
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

  function doKaiseki(html, a, firstBlinkers) {
    const data = parseRaceData(html);
    const raceDate = getRaceDate();

    a.find("td").remove();
    a.find("img").remove();

    if (data.length == 0) {
      addMark(a, txtHatsu, colHatsu);
      banushi(html, a);
      return false;
    }

    const flags = analyzeRaceData(data, raceDate);
    addMarks(a, flags, firstBlinkers);
    banushi(html, a);
  }
})(jQuery);
