// --- スリープ関数 ---
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- ランダムスリープ関数 (0.1〜0.5秒ランダム待機) ---
function randomSleep(minMs = 100, maxMs = 500) {
  const ms = Math.random() * (maxMs - minMs) + minMs;
  return sleep(ms);
}

// --- トークン制限用変数 ---
const MAX_TOKENS = 10; // 最大同時リクエスト許容量
const REFILL_INTERVAL = 1000; // 1秒ごとにトークン補充
const REFILL_AMOUNT = 1; // 1回に補充するトークン数
let tokens = MAX_TOKENS;

// --- トークン補充タイマー ---
setInterval(() => {
  tokens = Math.min(tokens + REFILL_AMOUNT, MAX_TOKENS);
}, REFILL_INTERVAL);

async function waitForToken() {
  while (tokens <= 0) {
    console.log("No tokens, waiting...");
    await sleep(100 + Math.random() * 200);
  }
}

async function ajax(linkUrl) {
  const cached = await getFromCache(linkUrl);
  if (cached) {
    console.log(linkUrl + ":IndexedDB cache hit");
    return $(cached.data);
  }

  await waitForToken();
  tokens--;
  await randomSleep(100, 500);

  return new Promise((resolve, reject) => {
    $.ajax({
      url: linkUrl,
      dataType: "html",
      beforeSend: (xhr) => {
        xhr.overrideMimeType("text/html;charset=euc-jp");
      },
      success: (html) => {
        const horseData = getHorseData(html);
        const htmlString = horseData[0].outerHTML;

        saveToCache(linkUrl, htmlString)
          .then(() => {
            resolve($(htmlString));
          })
          .catch((err) => {
            console.error("❌ saveToCache() でエラー", err);
            resolve($(htmlString)); // 保存できなくても処理は継続する場合
          });
      },
      error: (err) => {
        reject(err);
      },
    });
  });
}

function setItem(linkUrl, cachedData) {
  try {
    localStorage.setItem(linkUrl, JSON.stringify(cachedData));
  } catch (e) {
    if (
      e.name === "QuotaExceededError" ||
      e.name === "NS_ERROR_DOM_QUOTA_REACHED"
    ) {
      console.warn("Quota exceeded, clearing localStorage and retrying...");
      localStorage.clear();

      try {
        // 再挑戦（1回だけ）
        localStorage.setItem(linkUrl, JSON.stringify(cachedData));
      } catch (e2) {
        console.error("Retry failed after clearing localStorage", e2);
      }
    } else {
      console.error("localStorage error:", e);
    }
  }
}

async function loadHorseHtmlMap() {
  try {
    const res = await fetch("http://localhost:5000/all");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json(); // { horseId, html, saved_at } の配列
    console.log("fetch完了:", data);

    const horseHtmlMap = {};
    for (const row of data) {
      horseHtmlMap[row.horseId] = row.html;
    }

    console.log(
      `🗃️ DBから ${Object.keys(horseHtmlMap).length} 件の horseHtmlMap を読み込みました`,
    );
    return horseHtmlMap;
  } catch (e) {
    console.error("❌ horseHtmlMap の読み込みに失敗:", e);
    return {};
  }
}

function decodeHtml(encodedHtml) {
  try {
    // URL-safe Base64 → 標準 Base64
    let base64 = encodedHtml
      .replace(/\s+/g, "") // 空白・改行除去
      .replace(/-/g, "+")
      .replace(/_/g, "/");

    // パディング調整
    while (base64.length % 4) base64 += "=";

    // Base64 → Uint8Array
    const binaryString = atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }

    // gzip 解凍 → UTF-8
    const decoded = new TextDecoder("utf-8", { fatal: false }).decode(
      pako.ungzip(bytes),
    );

    // 制御文字を除去
    return decoded.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "");
  } catch (e) {
    console.error("decodeHtml error:", e);
    return "";
  }
}

function getHorseData(html) {
  if (!html) {
    return;
  }
  const $html = $("<div>").html(html);
  //レースタイトル
  const hinbaDiv = $("<div>", { id: "hinba" }).append(
    $html.find(".mainrace_data"),
  );
  //ラップ
  const lapDiv = $("<div>", { id: "lap" }).append(
    $html.find(".race_lap_cell").eq(0),
  );
  //プロフィール
  const profDiv = $("<div>", { id: "prof" }).append(
    $html.find(".db_prof_table"),
  );
  //血統URL
  const kettouUrlDiv = $("<div>", { id: "kettouUrl" }).append(
    $html
      .find("#db_main_box")
      .find(".db_head_regist")
      .find('a:contains("血統")')
      .attr("href"),
  );
  //血統
  const kettouDiv = $("<div>", { id: "kettou" }).append(
    $html.find(".blood_table"),
  );
  //レース結果
  const receResultDiv = $("<div>", { id: "raceResult" }).append(
    $html.find(".race_table_01"),
  );
  //成績
  const dataDiv = $("<div>", { id: "data" }).append(
    $html.find(".db_h_race_results"),
  );

  return $("<div>", { id: "horse_wrapper" }).append(
    hinbaDiv,
    lapDiv,
    profDiv,
    kettouUrlDiv,
    kettouDiv,
    receResultDiv,
    dataDiv,
  );
}

let horseHtmlMapCache = null;

async function getHorseHtmlMap(forceReload = false) {
  if (horseHtmlMapCache === null || forceReload) {
    horseHtmlMapCache = await loadHorseHtmlMap();
  }
  return horseHtmlMapCache;
}

// horseHtmlCache を親ページで保持
const horseHtmlCache = {};

// 子タブからキャッシュ更新メッセージを受信
window.addEventListener("message", (e) => {
  const data = e.data;
  if (data?.type === "updateHorseCache") {
    const { horseId, html } = data;
    horseHtmlCache[horseId] = html;
    console.log(`📝 [${horseId}] 親ページキャッシュ更新完了`);
  }
});

// 1頭ずつDBからHTMLを取得
async function getHtmlFromMap(horseId) {
  if (horseHtmlCache[horseId]) return horseHtmlCache[horseId];

  return new Promise((resolve) => {
    GM.xmlHttpRequest({
      method: "GET",
      url: `http://localhost:5000/html/${horseId}`,
      onload: (res) => {
        try {
          const data = JSON.parse(res.responseText);
          const html = getHorseData(data.html);
          horseHtmlCache[horseId] = html;
          resolve(html);
        } catch (e) {
          console.error(e);
          resolve(null);
        }
      },
      onerror: (err) => {
        console.error(err);
        resolve(null);
      },
    });
  });
}

// 非同期で「その後」の成績を集計してテーブルに反映する関数
var totalArray = new Array();
async function changeSonogoFunc(a, index) {
  const raceResulthtml = await ajax(a.attr("href"));

  // 開催日を yyyy/mm/dd 形式に変換
  const dateStr = $(raceResulthtml)
    .find(".data_intro p.smalltxt")
    .text()
    .substr(0, 10);
  const sonogoRaceDate = dateStr
    .replace("年", "/")
    .replace("月", "/")
    .replace("日", "");

  totalArray[index] = [0, 0, 0, 0];
  const promises = [];

  // レース結果表から馬リンクを全部取得
  const links = $(raceResulthtml)
    .find('#raceResult a[href*="/horse/"]')
    .toArray();

  for (const el of links) {
    const href = el.getAttribute("href");
    const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
    if (!match) {
      console.warn("馬IDが取れませんでした:", href);
      continue;
    }

    const horseId = match[1].trim();

    // HTML取得（await使える）
    const html = await getHtmlFromMap(horseId);
    setIndex(html);

    // 集計用Promiseをpush
    const p = addTotalVal(html, sonogoRaceDate, totalArray[index]);
    promises.push(p);
  }

  // 全部終わるのを待つ
  await Promise.all(promises);

  // 結果をテーブルに反映
  const result = $("<td>", { text: getSeisekiTxt(totalArray[index]) });
  $(".db_h_race_results tbody tr")
    .eq(index)
    .find("td")
    .eq(eizouIndex)
    .replaceWith(result);
}

function addTotalVal(html, sonogoRaceDate, totalVal) {
  setIndex(html);
  var seisekiVal = getSonogoSeisekiVal(html, sonogoRaceDate);
  totalVal[0] = totalVal[0] + seisekiVal[0];
  totalVal[1] = totalVal[1] + seisekiVal[1];
  totalVal[2] = totalVal[2] + seisekiVal[2];
  totalVal[3] = totalVal[3] + seisekiVal[3];
}

function setRaceDate() {
  var dateStr = $(".data_intro").find("p.smalltxt").text().substr(0, 10);
  raceDate = dateStr.replace("年", "/").replace("月", "/").replace("日", "");
}

// 「その後」ボタン押下時に呼ぶ関数
async function sonogo() {
  changeResultTableHd();
  setRaceDate();

  // 馬リンクを全部とる
  const links = $('.race_table_01 a[href^="/horse/"][title]').toArray();

  for (let index = 0; index < links.length; index++) {
    const a = $(links[index]);
    const href = a.attr("href");
    const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
    if (!match) {
      console.warn("馬IDが取れませんでした:", href);
      continue;
    }
    const horseId = match[1].trim();

    // awaitでHTML取得
    const html = await getHtmlFromMap(horseId);
    setIndex(html);

    // テーブル詳細更新
    await changeResultTableDtl(a, index);

    // 成績値算出して反映
    const seisekiVal = getSonogoSeisekiVal(html, raceDate);
    addSeiseki($("#sonogoTd" + index), seisekiVal);
  }
}

// その後
function sonogoFunc(a, index) {
  const horse = a.eq(index);
  const href = horse.attr("href");
  const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
  if (!match) {
    console.warn("馬IDが取れませんでした:", href);
    return;
  }
  const horseId = match[1].trim();
  const html = getHtmlFromMap(horseId);
  setIndex(html);
  changeResultTableDtl(a, index);
  const seisekiVal = getSonogoSeisekiVal(html, raceDate);
  addSeiseki($("#sonogoTd" + index), seisekiVal);
}

//血統
const kettouFunc = function (html, a, index, all) {
  const kettouUrl = $("<div>").html(html).find("#kettouUrl").text();
  ajax(kettouUrl).then(function (kettouHtml) {
    kettouColorFunc(kettouHtml, a, all);
  });
};

var kettouColorFunc = function (html, a, all) {
  var kettou1Flg = false;
  var kettou2Flg = false;

  var kettou1 = $("#kettou1").val();
  var kettou2 = $("#kettou2").val();
  if (!all) {
    all = $("#kettouAll").prop("checked");
  }

  a.closest("td").css("background", "");
  if (kettou1.length == 0 && kettou2.length == 0) {
    return true;
  }

  var kettouHtml = $(html).find(".blood_table");

  if (all) {
    if (
      kettou1.length > 0 &&
      kettouHtml.find("a:contains(" + kettou1 + ")").length > 0
    ) {
      kettou1Flg = true;
    }
    if (
      kettou2.length > 0 &&
      kettouHtml.find("a:contains(" + kettou2 + ")").length > 0
    ) {
      kettou2Flg = true;
    }
  } else {
    //母系のみ
    if (
      kettou1.length > 0 &&
      kettouHtml.find("tr:gt(15)").find("a:contains(" + kettou1 + ")").length >
        0
    ) {
      kettou1Flg = true;
    }
    if (
      kettou2.length > 0 &&
      kettouHtml.find("tr:gt(15)").find("a:contains(" + kettou2 + ")").length >
        0
    ) {
      kettou2Flg = true;
    }
  }

  if (kettou1Flg) {
    a.closest("td").css("background", kettouColor);
    if (kettou2Flg) {
      a.closest("td").css("background", kettou3Color);
    }
  } else if (kettou2Flg) {
    a.closest("td").css("background", kettou2Color);
  }
};

function addMark(a, txt, col, end) {
  var mark = $("<td></td>", { text: txt }).css("background-color", col);
  if (end) {
    a.append(mark);
  } else {
    a.prepend(mark);
  }
}

function kankaku(date1, date2) {
  var year1 = date1[0];
  var month1 = date1[1];
  var day1 = date1[2];
  var year2 = date2[0];
  var month2 = date2[1];
  var day2 = date2[2];

  return (year1 - year2) * 365 + (month1 - month2) * 30 + (day1 - day2);
}

function addSeiseki(tgt, seiseki) {
  var ritu = Math.round(
    ((seiseki[0] + seiseki[1] + seiseki[2]) /
      (seiseki[0] + seiseki[1] + seiseki[2] + seiseki[3])) *
      100,
  );
  if (ritu >= 80) {
    tgt.text(getSeisekiTxt(seiseki)).addClass(classR1ml);
  } else if (seiseki[0] + seiseki[1] + seiseki[2] == 0 && seiseki[3] > 0) {
    tgt.text(getSeisekiTxt(seiseki)).addClass(classR3ml);
  } else {
    tgt.text(getSeisekiTxt(seiseki)).removeClass();
  }
}

function getSeisekiTxt(seiseki) {
  return (
    "[" +
    seiseki[0] +
    "-" +
    seiseki[1] +
    "-" +
    seiseki[2] +
    "-" +
    seiseki[3] +
    "]"
  );
}

function getSeisekiVal(data, tgtIndex, tgtVal) {
  var result = [0, 0, 0, 0];
  var data = $(data);

  if (tgtVal.length == 0) {
    //全部
    var tgtTr = data.find("td:eq(" + tgtIndex + ")").parent();
    for (var j = 0; j < tgtTr.length; j++) {
      result = getTyakujun(result, tgtTr.eq(j));
    }
  }
  for (var i = 0; i < tgtVal.length; i++) {
    if (tgtVal[i].length == 0) {
      continue;
    }
    var tgtTr = data
      .find("td:eq(" + tgtIndex + "):contains(" + tgtVal[i] + ")")
      .parent();
    for (var j = 0; j < tgtTr.length; j++) {
      result = getTyakujun(result, tgtTr.eq(j));
    }
  }

  return result;
}

function getSeisekiValNot(data, tgtIndex, seiseki) {
  var allResult = getSeisekiVal(data, tgtIndex, []);
  var data = $(data);

  return [
    allResult[0] - seiseki[0],
    allResult[1] - seiseki[1],
    allResult[2] - seiseki[2],
    allResult[3] - seiseki[3],
  ];
}

function getMultiSeisekiVal(data, tgtIndex, tgtIndex2, tgtVal, tgtVal2) {
  var result = [0, 0, 0, 0];
  var data = $(data);

  var tgtTr = data
    .find("td:eq(" + tgtIndex + "):contains(" + tgtVal + ")")
    .parent()
    .find("td:eq(" + tgtIndex2 + "):contains(" + tgtVal2 + ")")
    .parent();
  for (var j = 0; j < tgtTr.length; j++) {
    result = getTyakujun(result, tgtTr.eq(j));
  }

  return result;
}

function getTyakujun(result, data) {
  //コース違い
  if (
    data.find("td:eq(" + kyoriIndex + "):contains(" + course + ")").length == 0
  ) {
    return result;
  }
  var tyakujun = data.find("td:eq(" + tyakuIndex + ")").text();
  if (tyakujun > 3) {
    tyakujun = 4;
  }
  result[tyakujun - 1]++;

  return result;
}

function getSonogoSeisekiVal(data, tgtDate) {
  var result = [0, 0, 0, 0];
  var data = $("<div>").html(data).find("#data").find("tbody").find("tr");
  for (var i = 0; i < data.length; i++) {
    result = getSonogoTyakujun(result, data.eq(i), tgtDate);
  }
  return result;
}

function isJRA(data) {
  //   var isJRARace = false;
  //   for (var i = 0; i < corseJRA.length; i++){
  //     if ($('.race_head_inner').find('p.smalltxt').text().indexOf(corseJRA[i]) > 0) {
  //       isJRARace = true;
  //     }
  //   }
  //   //地方競馬だったら例外的に対象とする
  //   if (!isJRARace) {
  //     return true;
  //   }
  var corse = data.find("td").eq(corseIndex).text();
  for (var i = 0; i < corseJRA.length; i++) {
    if (corse.indexOf(corseJRA[i]) != -1) {
      return true;
    }
  }
  return false;
}

function getSonogoTyakujun(result, data, tgtDate) {
  var date1 = data
    .find("td")
    .eq(hidukeIndex)
    .text()
    .trim()
    .slice(-10)
    .split("/");
  var date2 = tgtDate.split("/");

  //日付が過去
  if (kankaku(date1, date2) <= 0) {
    return result;
  }
  //地方競馬場
  if (!isJRA(data)) {
    return result;
  }

  var tyakujun = data.find("td:eq(" + tyakuIndex + ")").text();
  if (tyakujun > 3) {
    tyakujun = 4;
  }
  result[tyakujun - 1]++;
  return result;
}

function getRank(raceName) {
  for (var i = 0; i < raceRank.length; i++) {
    if (raceName.indexOf(raceRank[i][0]) != -1) {
      return raceRank[i][1];
    }
  }
  return 0;
}

function banushi(html, a) {
  var prof = $("<div>").html(html).find(".db_prof_table");
  var imgSrc = prof.find("img").attr("src");
  var mark = $("<img></img>", { src: imgSrc }).css({
    display: "inline-block",
    width: "16px",
    margin: "-1px 0",
    "margin-right": "8px",
  });
  a.prepend(mark);
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("MyCacheDB", 1);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains("cache")) {
        db.createObjectStore("cache", { keyPath: "key" });
      }
    };
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

async function getFromCache(url) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("cache", "readonly");
    const store = tx.objectStore("cache");
    const request = store.get(url);
    request.onsuccess = () => {
      resolve(request.result || null);
    };
    request.onerror = () => {
      console.error("Cache retrieval error for URL:", url, request.error);
      reject(request.error);
    };
  });
}

async function saveToCache(key, data) {
  const db = await openDB();

  const tx = db.transaction("cache", "readwrite");
  const store = tx.objectStore("cache");
  const timestamp = Date.now();

  await store.put({ key, data, timestamp });

  await tx.done;

  await enforceSizeLimit(db, 10 * 1024 * 1024); // 10MB
}

async function enforceSizeLimit(db, maxBytes) {
  const tx = db.transaction("cache", "readwrite");
  const store = tx.objectStore("cache");

  const allItems = await new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  let totalSize = 0;
  const items = allItems.map((item) => {
    const size = item.key.length + item.data.length;
    totalSize += size;
    return { ...item, size };
  });

  if (totalSize > maxBytes) {
    items.sort((a, b) => a.timestamp - b.timestamp);
    for (const item of items) {
      if (totalSize <= maxBytes) break;
      await new Promise((resolve, reject) => {
        const del = store.delete(item.key);
        del.onsuccess = () => resolve();
        del.onerror = () => reject(del.error);
      });
      totalSize -= item.size;
    }
  }

  await new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function estimateIndexedDBSize(dbName, storeName) {
  const db = await new Promise((resolve, reject) => {
    const req = indexedDB.open(dbName);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  const tx = db.transaction(storeName, "readonly");
  const store = tx.objectStore(storeName);
  const getAllReq = store.getAll();

  return new Promise((resolve, reject) => {
    getAllReq.onsuccess = () => {
      const items = getAllReq.result;
      let totalSize = 0;

      for (const item of items) {
        const json = JSON.stringify(item);
        totalSize += new Blob([json]).size;
      }

      resolve(totalSize); // bytes
    };
    getAllReq.onerror = () => reject(getAllReq.error);
  });
}
